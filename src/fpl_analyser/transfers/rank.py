from __future__ import annotations

from collections import Counter
from typing import Any

from fpl_analyser.fpl_rules import (
    ELEMENT_TYPE_DEF,
    ELEMENT_TYPE_FWD,
    ELEMENT_TYPE_GKP,
    ELEMENT_TYPE_MID,
    MAX_PLAYERS_PER_CLUB,
    STARTING_XI,
)
from fpl_analyser.models import ManagerSquad, TransferOption
from fpl_analyser.xp.model import ModelContext, expected_points


def club_counts(team_ids: list[int]) -> Counter[int]:
    return Counter(team_ids)


def is_valid_replacement(
    squad: ManagerSquad,
    out_id: int,
    incoming: dict[str, Any],
    players_by_id: dict[int, dict[str, Any]],
) -> bool:
    outgoing = next((p for p in squad.players if p.element_id == out_id), None)
    if outgoing is None:
        return False
    in_id = int(incoming["id"])
    if in_id == out_id:
        return False
    if any(p.element_id == in_id for p in squad.players):
        return False
    if int(incoming["element_type"]) != outgoing.element_type:
        return False
    teams = [p.team_id for p in squad.players if p.element_id != out_id]
    teams.append(int(incoming["team"]))
    if club_counts(teams)[int(incoming["team"])] > MAX_PLAYERS_PER_CLUB:
        return False
    sell = outgoing.selling_price
    if sell + squad.bank < int(incoming["now_cost"]):
        return False
    _ = players_by_id
    return True


def _xp_map(player_ids: list[int], event_ids: list[int], context: ModelContext) -> dict[int, dict[int, float]]:
    result: dict[int, dict[int, float]] = {}
    for pid in player_ids:
        xp = expected_points(pid, event_ids, context)
        result[pid] = xp.per_event
    return result


def best_xi_points(
    players: list[tuple[int, int, float]],
) -> float:
    """Greedy best XI under 1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD."""
    by_type: dict[int, list[float]] = {
        ELEMENT_TYPE_GKP: [],
        ELEMENT_TYPE_DEF: [],
        ELEMENT_TYPE_MID: [],
        ELEMENT_TYPE_FWD: [],
    }
    for _pid, etype, pts in sorted(players, key=lambda row: row[2], reverse=True):
        by_type.setdefault(etype, []).append(pts)

    gk = by_type[ELEMENT_TYPE_GKP][:1]
    if not gk:
        return 0.0
    defs = by_type[ELEMENT_TYPE_DEF]
    mids = by_type[ELEMENT_TYPE_MID]
    fwds = by_type[ELEMENT_TYPE_FWD]

    best = 0.0
    for n_def in range(3, 6):
        for n_mid in range(2, 6):
            n_fwd = STARTING_XI - 1 - n_def - n_mid
            if n_fwd < 1 or n_fwd > 3:
                continue
            if len(defs) < n_def or len(mids) < n_mid or len(fwds) < n_fwd:
                continue
            total = sum(gk) + sum(defs[:n_def]) + sum(mids[:n_mid]) + sum(fwds[:n_fwd])
            best = max(best, total)
    return best


def squad_horizon_xi(
    element_ids: list[int],
    players_by_id: dict[int, dict[str, Any]],
    xp_by_player: dict[int, dict[int, float]],
    event_ids: list[int],
) -> tuple[float, dict[int, float]]:
    per_event: dict[int, float] = {}
    for event_id in event_ids:
        lineup = []
        for eid in element_ids:
            meta = players_by_id.get(eid) or {}
            pts = xp_by_player.get(eid, {}).get(event_id, 0.0)
            lineup.append((eid, int(meta.get("element_type") or 0), pts))
        per_event[event_id] = best_xi_points(lineup)
    return sum(per_event.values()), per_event


def horizon_event_ids(bootstrap: dict[str, Any], horizon: int) -> list[int]:
    events = bootstrap.get("events") or []
    current = next((e for e in events if e.get("is_next") or e.get("is_current")), None)
    start = int(current["id"]) if current else 1
    if current and current.get("is_current") and current.get("finished"):
        start = int(current["id"]) + 1
    elif current and current.get("is_current") and not current.get("finished"):
        start = int(current["id"])
    ids = [int(e["id"]) for e in events if int(e["id"]) >= start]
    return ids[:horizon]


def rank_replacements(
    squad: ManagerSquad,
    bootstrap: dict[str, Any],
    horizon: int = 1,
    context: ModelContext | None = None,
    limit: int | None = None,
) -> list[TransferOption]:
    ctx = context or ModelContext(bootstrap=bootstrap)
    event_ids = horizon_event_ids(bootstrap, horizon)
    players_by_id = {int(p["id"]): p for p in bootstrap.get("elements") or []}
    squad_ids = [p.element_id for p in squad.players]
    candidate_ids = list(players_by_id.keys())
    needed = list(dict.fromkeys(squad_ids + candidate_ids))
    xp_by_player = _xp_map(needed, event_ids, ctx)

    current_sum, current_per = squad_horizon_xi(squad_ids, players_by_id, xp_by_player, event_ids)
    options: list[TransferOption] = []
    for outgoing in squad.players:
        for incoming in bootstrap.get("elements") or []:
            if not is_valid_replacement(squad, outgoing.element_id, incoming, players_by_id):
                continue
            in_id = int(incoming["id"])
            new_ids = [in_id if eid == outgoing.element_id else eid for eid in squad_ids]
            new_sum, new_per = squad_horizon_xi(new_ids, players_by_id, xp_by_player, event_ids)
            bank_after = squad.bank + outgoing.selling_price - int(incoming["now_cost"])
            incoming_xp = sum(xp_by_player.get(in_id, {}).values())
            options.append(
                TransferOption(
                    element_out=outgoing.element_id,
                    element_in=in_id,
                    out_name=outgoing.web_name,
                    in_name=incoming.get("web_name") or str(in_id),
                    selling_price=outgoing.selling_price,
                    purchase_price_out=outgoing.purchase_price,
                    now_cost_in=int(incoming["now_cost"]),
                    bank_after=bank_after,
                    price_source=outgoing.price_source,
                    delta=new_sum - current_sum,
                    incoming_horizon_xp=incoming_xp,
                    per_event_delta={
                        eid: new_per.get(eid, 0.0) - current_per.get(eid, 0.0) for eid in event_ids
                    },
                    placeholder=True,
                )
            )
    options.sort(key=lambda o: (o.delta, o.incoming_horizon_xp), reverse=True)
    if limit is not None:
        return options[:limit]
    return options
