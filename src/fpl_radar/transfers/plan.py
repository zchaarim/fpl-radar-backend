from __future__ import annotations

from typing import Any, Literal

from ortools.sat.python import cp_model

from fpl_radar.features import availability_note
from fpl_radar.fpl_rules import (
    ELEMENT_TYPE_DEF,
    ELEMENT_TYPE_FWD,
    ELEMENT_TYPE_GKP,
    ELEMENT_TYPE_MID,
    MAX_PLAYERS_PER_CLUB,
    PLAN_POOL_PER_POSITION,
    SQUAD_SHAPE,
    SQUAD_SIZE,
    STARTING_XI,
    scoring_table,
    transfer_hit_cost,
)
from fpl_radar.models import ManagerSquad, PlanMove, TransferPlan
from fpl_radar.transfers.rank import best_xi_ids, squad_horizon_xi, xp_map
from fpl_radar.xp.model import ModelContext, horizon_event_ids

Chip = Literal["wildcard", "freehit"]

XP_SCALE = 1000
SOLVE_SECONDS = 5.0

_POSITIONS = (ELEMENT_TYPE_GKP, ELEMENT_TYPE_DEF, ELEMENT_TYPE_MID, ELEMENT_TYPE_FWD)


def _horizon_total(per_event: dict[int, float], event_ids: list[int]) -> float:
    return sum(per_event.get(eid, 0.0) for eid in event_ids)


def _player_horizon(
    xp_by_player: dict[int, dict[int, float]],
    player_id: int,
    event_ids: list[int],
) -> float:
    return _horizon_total(xp_by_player.get(player_id, {}), event_ids)


def candidate_pool(
    squad: ManagerSquad,
    bootstrap: dict[str, Any],
    xp_by_player: dict[int, dict[int, float]],
    event_ids: list[int],
    per_position: int = PLAN_POOL_PER_POSITION,
) -> list[int]:
    """Current 15 plus top xP, value, and cheapest players per position."""
    squad_ids = {p.element_id for p in squad.players}
    by_pos: dict[int, list[dict[str, Any]]] = {etype: [] for etype in _POSITIONS}
    for row in bootstrap.get("elements") or []:
        etype = int(row.get("element_type") or 0)
        if etype not in by_pos:
            continue
        pid = int(row["id"])
        if pid in squad_ids:
            continue
        cost = max(int(row.get("now_cost") or 1), 1)
        total = _player_horizon(xp_by_player, pid, event_ids)
        by_pos[etype].append({"id": pid, "xp": total, "cost": cost, "value": total / cost})

    picked: set[int] = set(squad_ids)
    n = max(int(per_position), 1)
    cheap_n = max(n // 4, 5)
    for etype, rows in by_pos.items():
        for key, cap in (("xp", n), ("value", n), ("cost", cheap_n)):
            reverse = key != "cost"
            ranked = sorted(rows, key=lambda item: item[key], reverse=reverse)
            for item in ranked[:cap]:
                picked.add(int(item["id"]))
        _ = etype
    return sorted(picked)


def _lineup_ids(
    squad_ids: list[int],
    players_by_id: dict[int, dict[str, Any]],
    xp_by_player: dict[int, dict[int, float]],
    event_id: int,
) -> list[int]:
    lineup = []
    for eid in squad_ids:
        meta = players_by_id.get(eid) or {}
        pts = xp_by_player.get(eid, {}).get(event_id, 0.0)
        lineup.append((eid, int(meta.get("element_type") or 0), pts))
    return best_xi_ids(lineup)


def _order_moves(moves: list[PlanMove]) -> list[PlanMove]:
    return sorted(moves, key=lambda move: (move.cash_delta, move.selling_price), reverse=True)


def _pair_moves(
    sold: list[int],
    bought: list[int],
    squad: ManagerSquad,
    players_by_id: dict[int, dict[str, Any]],
) -> list[PlanMove]:
    by_owned = {p.element_id: p for p in squad.players}
    sold_by_pos: dict[int, list[int]] = {etype: [] for etype in _POSITIONS}
    bought_by_pos: dict[int, list[int]] = {etype: [] for etype in _POSITIONS}
    for pid in sold:
        etype = int((players_by_id.get(pid) or {}).get("element_type") or 0)
        sold_by_pos.setdefault(etype, []).append(pid)
    for pid in bought:
        etype = int((players_by_id.get(pid) or {}).get("element_type") or 0)
        bought_by_pos.setdefault(etype, []).append(pid)
    moves: list[PlanMove] = []
    for etype in _POSITIONS:
        outs = sold_by_pos.get(etype) or []
        ins = bought_by_pos.get(etype) or []
        outs.sort(key=lambda pid: by_owned[pid].selling_price if pid in by_owned else 0, reverse=True)
        ins.sort(key=lambda pid: int((players_by_id.get(pid) or {}).get("now_cost") or 0), reverse=True)
        for out_id, in_id in zip(outs, ins, strict=False):
            owned = by_owned[out_id]
            incoming = players_by_id.get(in_id) or {}
            sell = owned.selling_price
            buy = int(incoming.get("now_cost") or 0)
            moves.append(
                PlanMove(
                    element_out=out_id,
                    element_in=in_id,
                    out_name=owned.web_name,
                    in_name=str(incoming.get("web_name") or in_id),
                    selling_price=sell,
                    now_cost_in=buy,
                    cash_delta=sell - buy,
                    element_type=etype,
                    out_flag=availability_note(players_by_id.get(out_id)),
                    in_flag=availability_note(incoming),
                )
            )
    return _order_moves(moves)


def _solve_squad(
    *,
    pool: list[int],
    players_by_id: dict[int, dict[str, Any]],
    xp_by_player: dict[int, dict[int, float]],
    event_ids: list[int],
    cost_of: dict[int, int],
    budget: int,
    required: dict[int, int] | None = None,
    max_sold: int | None = None,
    current_ids: set[int] | None = None,
    hit_points: float = 4.0,
    free_transfers: int = 1,
    apply_hits: bool = False,
) -> list[int]:
    current_ids = current_ids or set()
    model = cp_model.CpModel()
    chosen = {pid: model.NewBoolVar(f"x_{pid}") for pid in pool}
    model.Add(sum(chosen[pid] for pid in pool) == SQUAD_SIZE)
    for etype, n in SQUAD_SHAPE.items():
        model.Add(
            sum(chosen[pid] for pid in pool if int((players_by_id.get(pid) or {}).get("element_type") or 0) == etype)
            == n
        )
    clubs = {int((players_by_id.get(pid) or {}).get("team") or 0) for pid in pool}
    for club in clubs:
        if not club:
            continue
        model.Add(
            sum(chosen[pid] for pid in pool if int((players_by_id.get(pid) or {}).get("team") or 0) == club)
            <= MAX_PLAYERS_PER_CLUB
        )
    if required:
        for pid, must in required.items():
            if pid in chosen:
                model.Add(chosen[pid] == must)

    model.Add(sum(cost_of[pid] * chosen[pid] for pid in pool) <= budget)

    n_sold = None
    hits = None
    if max_sold is not None:
        owned = [pid for pid in pool if pid in current_ids]
        market = [pid for pid in pool if pid not in current_ids]
        n_sold = model.NewIntVar(0, max_sold, "n_sold")
        n_bought = model.NewIntVar(0, max_sold, "n_bought")
        model.Add(n_sold == sum(1 - chosen[pid] for pid in owned))
        model.Add(n_bought == sum(chosen[pid] for pid in market))
        model.Add(n_sold == n_bought)
        model.Add(n_sold <= max_sold)

    starts: dict[tuple[int, int], cp_model.IntVar] = {}
    for event_id in event_ids:
        gw_starts = []
        by_type: dict[int, list[cp_model.IntVar]] = {etype: [] for etype in _POSITIONS}
        for pid in pool:
            var = model.NewBoolVar(f"s_{pid}_{event_id}")
            model.Add(var <= chosen[pid])
            starts[pid, event_id] = var
            gw_starts.append(var)
            etype = int((players_by_id.get(pid) or {}).get("element_type") or 0)
            by_type.setdefault(etype, []).append(var)
        model.Add(sum(gw_starts) == STARTING_XI)
        model.Add(sum(by_type[ELEMENT_TYPE_GKP]) == 1)
        model.Add(sum(by_type[ELEMENT_TYPE_DEF]) >= 3)
        model.Add(sum(by_type[ELEMENT_TYPE_DEF]) <= 5)
        model.Add(sum(by_type[ELEMENT_TYPE_MID]) >= 2)
        model.Add(sum(by_type[ELEMENT_TYPE_MID]) <= 5)
        model.Add(sum(by_type[ELEMENT_TYPE_FWD]) >= 1)
        model.Add(sum(by_type[ELEMENT_TYPE_FWD]) <= 3)

    xi_terms = []
    for pid in pool:
        for event_id in event_ids:
            pts = xp_by_player.get(pid, {}).get(event_id, 0.0)
            xi_terms.append(starts[pid, event_id] * int(round(pts * XP_SCALE)))

    if apply_hits and n_sold is not None:
        hits = model.NewIntVar(0, max_sold or SQUAD_SIZE, "hits")
        model.Add(hits >= n_sold - max(int(free_transfers), 0))
        model.Maximize(sum(xi_terms) - hits * int(round(hit_points * XP_SCALE)))
    else:
        model.Maximize(sum(xi_terms))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = SOLVE_SECONDS
    solver.parameters.num_search_workers = 8
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise RuntimeError("Could not find a legal plan (infeasible squad/budget).")
    return [pid for pid in pool if solver.Value(chosen[pid]) == 1]


def _build_result(
    squad: ManagerSquad,
    new_ids: list[int],
    players_by_id: dict[int, dict[str, Any]],
    xp_by_player: dict[int, dict[int, float]],
    event_ids: list[int],
    *,
    chip: str | None,
    free_transfers: int,
    hit_points: float,
    apply_hits: bool,
    placeholder: bool,
) -> TransferPlan:
    current_ids = [p.element_id for p in squad.players]
    current_sum, current_per = squad_horizon_xi(current_ids, players_by_id, xp_by_player, event_ids)
    new_sum, new_per = squad_horizon_xi(new_ids, players_by_id, xp_by_player, event_ids)
    sold = [pid for pid in current_ids if pid not in set(new_ids)]
    bought = [pid for pid in new_ids if pid not in set(current_ids)]
    n_transfers = len(sold)
    if apply_hits:
        hits, hit_xp = transfer_hit_cost(n_transfers, free_transfers, hit_points)
    else:
        hits, hit_xp = 0, 0.0
    delta_xi = new_sum - current_sum
    sell_map = {p.element_id: p.selling_price for p in squad.players}
    bank_after = squad.bank + sum(sell_map[pid] for pid in sold) - sum(
        int((players_by_id.get(pid) or {}).get("now_cost") or 0) for pid in bought
    )
    first_gw = event_ids[0] if event_ids else 0
    starters = _lineup_ids(new_ids, players_by_id, xp_by_player, first_gw) if first_gw else []
    moves = [] if chip else _pair_moves(sold, bought, squad, players_by_id)
    return TransferPlan(
        chip=chip,
        n_transfers=n_transfers,
        free_transfers=free_transfers,
        hits=hits,
        hit_cost=hit_xp,
        delta_xi=delta_xi,
        delta_net=delta_xi - hit_xp,
        current_xi=current_sum,
        planned_xi=new_sum,
        bank_after=bank_after,
        squad_ids=new_ids,
        starter_ids=starters,
        moves=moves,
        per_event_delta={
            eid: new_per.get(eid, 0.0) - current_per.get(eid, 0.0) for eid in event_ids
        },
        placeholder=placeholder,
    )


def plan_transfers(
    squad: ManagerSquad,
    bootstrap: dict[str, Any],
    horizon: int = 1,
    max_transfers: int = 3,
    context: ModelContext | None = None,
    free_transfers: int | None = None,
    pool_per_position: int = PLAN_POOL_PER_POSITION,
) -> TransferPlan:
    ctx = context or ModelContext(bootstrap=bootstrap)
    event_ids = horizon_event_ids(bootstrap, horizon)
    players_by_id = {int(p["id"]): p for p in bootstrap.get("elements") or []}
    ft = squad.free_transfers if free_transfers is None else int(free_transfers)
    hit_points = float(scoring_table(bootstrap.get("game_settings")).get("transfer_cost", 4))
    needed = list(players_by_id.keys())
    xp_by_player = xp_map(needed, event_ids, ctx)
    pool = candidate_pool(squad, bootstrap, xp_by_player, event_ids, per_position=pool_per_position)
    current_ids = {p.element_id for p in squad.players}
    sell_of = {p.element_id: p.selling_price for p in squad.players}
    cost_of = {}
    for pid in pool:
        if pid in current_ids:
            cost_of[pid] = sell_of[pid]
        else:
            cost_of[pid] = int((players_by_id.get(pid) or {}).get("now_cost") or 0)
    budget = squad.bank + sum(sell_of.values())
    k = max(0, min(int(max_transfers), SQUAD_SIZE))
    new_ids = _solve_squad(
        pool=pool,
        players_by_id=players_by_id,
        xp_by_player=xp_by_player,
        event_ids=event_ids,
        cost_of=cost_of,
        budget=budget,
        required={},
        max_sold=k,
        current_ids=current_ids,
        hit_points=hit_points,
        free_transfers=ft,
        apply_hits=True,
    )
    return _build_result(
        squad,
        new_ids,
        players_by_id,
        xp_by_player,
        event_ids,
        chip=None,
        free_transfers=ft,
        hit_points=hit_points,
        apply_hits=True,
        placeholder=ctx.features is None,
    )


def plan_chip(
    squad: ManagerSquad,
    bootstrap: dict[str, Any],
    chip: Chip,
    horizon: int = 1,
    context: ModelContext | None = None,
    pool_per_position: int = PLAN_POOL_PER_POSITION,
) -> TransferPlan:
    ctx = context or ModelContext(bootstrap=bootstrap)
    use_horizon = 1 if chip == "freehit" else horizon
    event_ids = horizon_event_ids(bootstrap, use_horizon)
    players_by_id = {int(p["id"]): p for p in bootstrap.get("elements") or []}
    xp_by_player = xp_map(list(players_by_id.keys()), event_ids, ctx)
    pool = candidate_pool(squad, bootstrap, xp_by_player, event_ids, per_position=pool_per_position)
    cost_of = {
        pid: int((players_by_id.get(pid) or {}).get("now_cost") or 0) for pid in pool
    }
    budget = squad.bank + sum(p.selling_price for p in squad.players)
    new_ids = _solve_squad(
        pool=pool,
        players_by_id=players_by_id,
        xp_by_player=xp_by_player,
        event_ids=event_ids,
        cost_of=cost_of,
        budget=budget,
        required={},
        apply_hits=False,
    )
    return _build_result(
        squad,
        new_ids,
        players_by_id,
        xp_by_player,
        event_ids,
        chip=chip,
        free_transfers=squad.free_transfers,
        hit_points=0.0,
        apply_hits=False,
        placeholder=ctx.features is None,
    )


def make_plan(
    squad: ManagerSquad,
    bootstrap: dict[str, Any],
    horizon: int = 1,
    max_transfers: int = 3,
    chip: str | None = None,
    context: ModelContext | None = None,
    free_transfers: int | None = None,
    pool_per_position: int = PLAN_POOL_PER_POSITION,
) -> TransferPlan:
    if chip in {"wildcard", "freehit"}:
        return plan_chip(
            squad,
            bootstrap,
            chip=chip,  # type: ignore[arg-type]
            horizon=horizon,
            context=context,
            pool_per_position=pool_per_position,
        )
    return plan_transfers(
        squad,
        bootstrap,
        horizon=horizon,
        max_transfers=max_transfers,
        context=context,
        free_transfers=free_transfers,
        pool_per_position=pool_per_position,
    )
