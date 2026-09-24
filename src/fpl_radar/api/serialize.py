from __future__ import annotations

from fpl_radar.api.schemas import (
    EntrySummary,
    Money,
    PlanMoveRow,
    PlanRequest,
    PlanResponse,
    PlanSquadPlayer,
    RecommendationRow,
    RecommendationsResponse,
    SquadPlayerRow,
    SquadResponse,
    XgiPlayerRow,
    XgiResponse,
    XpPlayerRow,
    XpResponse,
)
from fpl_radar.features import availability_note, rank_xgi_rates
from fpl_radar.fpl_rules import POSITION_ORDER, tenths_to_pounds
from fpl_radar.models import ManagerSquad
from fpl_radar.squad import resolve_owned_players
from fpl_radar.transfers.plan import make_plan
from fpl_radar.transfers.rank import rank_replacements
from fpl_radar.xp.model import ModelContext, horizon_event_ids, player_xp, rank_horizon_xp


def money(tenths: int) -> Money:
    return Money(tenths=int(tenths), pounds=tenths_to_pounds(tenths))


def xp_source(context: ModelContext) -> str:
    if context.features is None:
        return "placeholder xP from FPL ep_next"
    return "minutes + xGI + CS/GC + DefCon + bonus + saves + cards"


def current_event_id(bootstrap: dict) -> int | None:
    for event in bootstrap.get("events") or []:
        if event.get("is_current"):
            return int(event["id"])
    for event in bootstrap.get("events") or []:
        if event.get("is_next"):
            return int(event["id"])
    return None


def entry_summary(squad: ManagerSquad) -> EntrySummary:
    return EntrySummary(
        entry_id=squad.entry_id,
        name=squad.name,
        current_event=squad.current_event,
        bank=money(squad.bank),
        bank_source=squad.bank_source,
        free_transfers=squad.free_transfers,
        free_transfers_source=squad.free_transfers_source,
        authenticated=squad.authenticated,
    )


def squad_payload(squad: ManagerSquad, context: ModelContext, horizon: int) -> SquadResponse:
    event_ids = horizon_event_ids(context.bootstrap, horizon)
    players_by_id = {int(p["id"]): p for p in context.bootstrap.get("elements") or []}
    teams = {int(t["id"]): t.get("short_name") or "?" for t in context.bootstrap.get("teams") or []}
    placeholder = context.features is None
    rows: list[SquadPlayerRow] = []
    for player in squad.players:
        meta = players_by_id.get(player.element_id) or {}
        xp = player_xp(player.element_id, event_ids, context)
        rates = context.features.players.get(player.element_id) if context.features else None
        rows.append(
            SquadPlayerRow(
                element_id=player.element_id,
                web_name=player.web_name,
                team_id=player.team_id,
                team_short=teams.get(player.team_id, "?"),
                element_type=player.element_type,
                now_cost=money(player.now_cost),
                purchase_price=money(player.purchase_price),
                selling_price=money(player.selling_price),
                price_source=player.price_source,
                position=player.position,
                horizon_xp=xp.horizon_sum,
                xgi90=rates.xgi90 if rates is not None else None,
                flag=availability_note(meta),
            )
        )
        placeholder = placeholder or xp.placeholder
    header = entry_summary(squad)
    return SquadResponse(
        **header.model_dump(),
        horizon=horizon,
        event_ids=event_ids,
        xp_source=xp_source(context),
        placeholder=placeholder,
        players=rows,
    )


def _club_map(context: ModelContext) -> dict[int, str]:
    return {int(t["id"]): t.get("short_name") or "?" for t in context.bootstrap.get("teams") or []}


def xp_listing(context: ModelContext, horizon: int, limit: int) -> XpResponse:
    event_ids = horizon_event_ids(context.bootstrap, horizon)
    teams = _club_map(context)
    ranked = rank_horizon_xp(context, horizon=horizon, limit_per_position=limit)
    rows: list[XpPlayerRow] = []
    placeholder = context.features is None
    for player, xp in ranked:
        pid = int(player.get("id") or 0)
        team_id = int(player.get("team") or 0)
        rows.append(
            XpPlayerRow(
                element_id=pid,
                web_name=str(player.get("web_name") or pid),
                team_id=team_id,
                team_short=teams.get(team_id, "?"),
                element_type=int(player.get("element_type") or 0),
                now_cost=money(int(player.get("now_cost") or 0)),
                flag=availability_note(player),
                horizon_xp=xp.horizon_sum,
                per_event=xp.per_event,
            )
        )
        placeholder = placeholder or xp.placeholder
    return XpResponse(
        horizon=horizon,
        event_ids=event_ids,
        limit=limit,
        xp_source=xp_source(context),
        placeholder=placeholder,
        players=rows,
    )


def xgi_listing(context: ModelContext, limit: int, min_minutes: float) -> XgiResponse:
    features = context.features
    if features is None:
        raise ValueError("No feature set; run sync first.")
    teams = _club_map(context)
    ranked = rank_xgi_rates(
        context.bootstrap,
        features,
        limit_per_position=limit,
        min_minutes=min_minutes,
    )
    rows: list[XgiPlayerRow] = []
    for player, rates in ranked:
        pid = int(player.get("id") or 0)
        team_id = int(player.get("team") or 0)
        rows.append(
            XgiPlayerRow(
                element_id=pid,
                web_name=str(player.get("web_name") or pid),
                team_id=team_id,
                team_short=teams.get(team_id, "?"),
                element_type=int(player.get("element_type") or 0),
                now_cost=money(int(player.get("now_cost") or 0)),
                flag=availability_note(player),
                source=rates.source,
                minutes=rates.minutes,
                xg90=rates.xg90,
                xa90=rates.xa90,
                xgi90=rates.xgi90,
                raw_xgi=rates.xg90_raw + rates.xa90_raw,
                bps_avg=rates.bps_avg,
                bonus_e=rates.bonus_e,
            )
        )
    matched = len(features.players) - len(features.unmatched_players)
    return XgiResponse(
        limit=limit,
        min_minutes=min_minutes,
        matched=matched,
        players_in_features=len(features.players),
        players=rows,
    )


def recommendations_payload(
    squad: ManagerSquad,
    context: ModelContext,
    horizon: int,
    limit: int,
    remove_player: str | None = None,
) -> RecommendationsResponse:
    remove_id = None
    remove_name = None
    if remove_player and str(remove_player).strip():
        resolved = resolve_owned_players(squad, [str(remove_player).strip()])
        if not resolved:
            raise ValueError(f"No squad player matching {remove_player!r}")
        remove_id = resolved[0]
        remove_name = next(p.web_name for p in squad.players if p.element_id == remove_id)
    options = rank_replacements(
        squad,
        context.bootstrap,
        horizon=horizon,
        context=context,
        limit=limit,
        remove_player_id=remove_id,
    )
    event_ids = horizon_event_ids(context.bootstrap, horizon)
    rows = [
        RecommendationRow(
            element_out=option.element_out,
            element_in=option.element_in,
            out_name=option.out_name,
            in_name=option.in_name,
            element_type=option.element_type,
            selling_price=money(option.selling_price),
            now_cost_in=money(option.now_cost_in),
            bank_after=money(option.bank_after),
            price_source=option.price_source,
            delta=option.delta,
            incoming_horizon_xp=option.incoming_horizon_xp,
            out_flag=option.out_flag,
            in_flag=option.in_flag,
        )
        for option in options
    ]
    placeholder = bool(options and options[0].placeholder) or context.features is None
    header = entry_summary(squad)
    return RecommendationsResponse(
        **header.model_dump(),
        horizon=horizon,
        event_ids=event_ids,
        limit=limit,
        remove_player_id=remove_id,
        remove_player_name=remove_name,
        xp_source=xp_source(context),
        placeholder=placeholder,
        options=rows,
    )


def plan_payload(
    squad: ManagerSquad,
    context: ModelContext,
    request: PlanRequest,
) -> PlanResponse:
    chip = None if request.chip == "none" else request.chip
    horizon = 1 if chip == "freehit" else request.horizon
    remove_ids: list[int] | None = None
    tokens = [str(token).strip() for token in request.remove_player if str(token).strip()]
    if tokens:
        remove_ids = resolve_owned_players(squad, tokens)
    plan = make_plan(
        squad,
        context.bootstrap,
        horizon=horizon,
        max_transfers=request.transfers,
        chip=chip,
        context=context,
        free_transfers=request.ft,
        remove_player_ids=remove_ids,
    )
    event_ids = horizon_event_ids(context.bootstrap, horizon)
    players_by_id = {int(p["id"]): p for p in context.bootstrap.get("elements") or []}
    teams = _club_map(context)
    starters = set(plan.starter_ids)
    moves = [
        PlanMoveRow(
            element_out=move.element_out,
            element_in=move.element_in,
            out_name=move.out_name,
            in_name=move.in_name,
            element_type=move.element_type,
            cash_delta=money(move.cash_delta),
            out_flag=move.out_flag,
            in_flag=move.in_flag,
        )
        for move in plan.moves
    ]
    by_type: dict[int, list[int]] = {etype: [] for etype in POSITION_ORDER}
    for pid in plan.squad_ids:
        meta = players_by_id.get(pid) or {}
        by_type.setdefault(int(meta.get("element_type") or 0), []).append(pid)
    squad_rows: list[PlanSquadPlayer] = []
    for etype in POSITION_ORDER:
        for pid in by_type.get(etype) or []:
            meta = players_by_id.get(pid) or {}
            team_id = int(meta.get("team") or 0)
            squad_rows.append(
                PlanSquadPlayer(
                    element_id=pid,
                    web_name=str(meta.get("web_name") or pid),
                    team_id=team_id,
                    team_short=teams.get(team_id, "?"),
                    element_type=int(meta.get("element_type") or 0),
                    role="XI" if pid in starters else "bench",
                    now_cost=money(int(meta.get("now_cost") or 0)),
                    flag=availability_note(meta),
                )
            )
    header = entry_summary(squad)
    header.free_transfers = plan.free_transfers
    if request.ft is not None:
        header.free_transfers_source = "caller_override"
    return PlanResponse(
        **header.model_dump(),
        chip=plan.chip,
        horizon=horizon,
        event_ids=event_ids,
        n_transfers=plan.n_transfers,
        hits=plan.hits,
        hit_cost=plan.hit_cost,
        current_xi=plan.current_xi,
        planned_xi=plan.planned_xi,
        delta_xi=plan.delta_xi,
        delta_net=plan.delta_net,
        bank_after=money(plan.bank_after),
        xp_source=xp_source(context),
        placeholder=plan.placeholder,
        moves=moves,
        squad=squad_rows,
    )
