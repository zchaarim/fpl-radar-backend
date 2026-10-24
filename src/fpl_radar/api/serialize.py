from __future__ import annotations

import unicodedata
from datetime import datetime, timezone

from fpl_radar.api.schemas import (
    BoardEvent,
    BoardPlayerRow,
    BoardResponse,
    EntrySummary,
    Money,
    PlanMoveRow,
    PlanRequest,
    PlanResponse,
    PlanSquadPlayer,
    PlayerSearchResponse,
    PlayerSearchRow,
    RecommendationRow,
    RecommendationsResponse,
    SquadPlayerRow,
    SquadResponse,
    XgiPlayerRow,
    XgiResponse,
    XpPlayerRow,
    XpResponse,
)
from fpl_radar.clients.fpl import FplApiError, FplClient
from fpl_radar.features import availability_fields, availability_note, rank_xgi_rates
from fpl_radar.fpl_rules import POSITION_ORDER, tenths_to_pounds
from fpl_radar.models import ManagerSquad
from fpl_radar.squad import apply_event_transfers, pin_armbands_to_xi, resolve_owned_players
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


_FOLD_EXTRA = str.maketrans(
    {
        "ß": "ss",
        "ẞ": "ss",
        "æ": "ae",
        "Æ": "ae",
        "œ": "oe",
        "Œ": "oe",
        "ø": "o",
        "Ø": "o",
        "ł": "l",
        "Ł": "l",
        "đ": "d",
        "Đ": "d",
    }
)


def fold_search_text(value: str) -> str:
    """Fold accents so 'gue' matches Guéhi and 'gros' matches Groß."""
    folded = unicodedata.normalize("NFKD", value.translate(_FOLD_EXTRA))
    return "".join(ch for ch in folded if not unicodedata.combining(ch)).casefold()


def event_has_started(
    *,
    finished: bool,
    is_current: bool,
    deadline_time: str | None,
) -> bool:
    """True once the GW deadline has passed (or FPL marked it current) and it is not finished."""
    if finished:
        return False
    if is_current:
        return True
    if not deadline_time:
        return False
    try:
        deadline = datetime.fromisoformat(str(deadline_time).replace("Z", "+00:00"))
    except ValueError:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return deadline <= datetime.now(timezone.utc)


def first_unfinished_event_id(bootstrap: dict) -> int | None:
    for event in bootstrap.get("events") or []:
        if event.get("finished"):
            continue
        eid = int(event.get("id") or 0)
        if eid:
            return eid
    return current_event_id(bootstrap)


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


def _event_chips(bootstrap: dict) -> list[BoardEvent]:
    chips: list[BoardEvent] = []
    for event in bootstrap.get("events") or []:
        eid = int(event.get("id") or 0)
        if not eid:
            continue
        finished = bool(event.get("finished"))
        is_current = bool(event.get("is_current"))
        deadline = event.get("deadline_time")
        chips.append(
            BoardEvent(
                id=eid,
                name=str(event.get("name") or f"GW {eid}"),
                finished=finished,
                is_current=is_current,
                is_next=bool(event.get("is_next")),
                started=event_has_started(
                    finished=finished,
                    is_current=is_current,
                    deadline_time=str(deadline) if deadline else None,
                ),
                deadline_time=deadline,
            )
        )
    return chips


def _live_stats(client: FplClient, event_id: int) -> dict[int, tuple[float, int]]:
    """Map element id → (total_points, minutes)."""
    try:
        live = client.event_live(event_id)
    except FplApiError:
        return {}
    out: dict[int, tuple[float, int]] = {}
    for row in live.get("elements") or []:
        pid = int(row.get("id") or 0)
        if not pid:
            continue
        stats = row.get("stats") or {}
        try:
            minutes = int(float(stats.get("minutes") or 0))
        except (TypeError, ValueError):
            minutes = 0
        out[pid] = (float(stats.get("total_points") or 0), minutes)
    return out


def _try_picks(client: FplClient, entry_id: int, event_id: int) -> list[dict] | None:
    try:
        payload = client.entry_picks(entry_id, event_id)
    except FplApiError:
        return None
    picks = list(payload.get("picks") or [])
    return picks or None


def _opponent(fixtures: list[dict], team_id: int, event_id: int, teams: dict[int, str]) -> tuple[str, int]:
    labels: list[str] = []
    for fixture in fixtures:
        if int(fixture.get("event") or 0) != event_id:
            continue
        home = int(fixture.get("team_h") or 0)
        away = int(fixture.get("team_a") or 0)
        if team_id == home:
            labels.append(f"{teams.get(away, '?')} (H)")
        elif team_id == away:
            labels.append(f"{teams.get(home, '?')} (A)")
    if not labels:
        return "Blank", 0
    return " + ".join(labels), len(labels)


def _team_fixture_started(fixtures: list[dict], team_id: int, event_id: int) -> bool:
    now = datetime.now(timezone.utc)
    for fixture in fixtures:
        if int(fixture.get("event") or 0) != event_id:
            continue
        home = int(fixture.get("team_h") or 0)
        away = int(fixture.get("team_a") or 0)
        if team_id not in (home, away):
            continue
        if fixture.get("started") or fixture.get("finished"):
            return True
        raw = fixture.get("kickoff_time")
        if not raw:
            continue
        try:
            kickoff = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if kickoff.tzinfo is None:
            kickoff = kickoff.replace(tzinfo=timezone.utc)
        if kickoff <= now:
            return True
    return False


def board_payload(
    squad: ManagerSquad,
    context: ModelContext,
    client: FplClient,
    event_id: int | None,
    element_ids: list[int] | None = None,
) -> BoardResponse:
    catalog = _event_chips(context.bootstrap)
    upcoming = [e for e in catalog if not e.finished]
    by_id = {e.id: e for e in catalog}
    selected_id = int(event_id) if event_id is not None else first_unfinished_event_id(context.bootstrap)
    if selected_id not in by_id:
        raise ValueError(f"Unknown event {selected_id}")
    selected = by_id[selected_id]
    if selected.finished:
        raise ValueError("Board only covers unfinished gameweeks")
    live_gw = selected.started
    mode = "actual" if live_gw else "predicted"
    events = upcoming
    picks = _try_picks(client, squad.entry_id, selected_id)
    players_by_id = {int(p["id"]): p for p in context.bootstrap.get("elements") or []}
    teams = _club_map(context)
    fixtures = client.fixtures()
    live = _live_stats(client, selected_id) if live_gw else {}
    if picks is not None and not selected.finished:
        picks = apply_event_transfers(picks, client.entry_transfers(squad.entry_id), selected_id)

    if element_ids is not None and not selected.finished:
        ordered = []
        for index, pid in enumerate(element_ids, start=1):
            meta = players_by_id.get(pid)
            if meta is None:
                raise ValueError(f"Unknown player {pid}")
            held = next((p for p in squad.players if p.element_id == pid), None)
            ordered.append(
                (
                    {
                        "element": pid,
                        "position": index,
                        "is_captain": bool(held.is_captain) if held else False,
                        "is_vice_captain": bool(held.is_vice_captain) if held else False,
                    },
                    meta,
                )
            )
    elif picks is not None:
        ordered = []
        for pick in picks:
            pid = int(pick.get("element") or 0)
            meta = players_by_id.get(pid)
            if meta is None:
                continue
            ordered.append((pick, meta))
    else:
        ordered = [
            (
                {
                    "element": p.element_id,
                    "position": p.position,
                    "is_captain": p.is_captain,
                    "is_vice_captain": p.is_vice_captain,
                },
                players_by_id.get(p.element_id) or {},
            )
            for p in squad.players
        ]

    rows: list[BoardPlayerRow] = []
    placeholder = context.features is None
    for pick, meta in ordered:
        pid = int(meta.get("id") or pick.get("element") or 0)
        team_id = int(meta.get("team") or 0)
        xp = player_xp(pid, [selected_id], context)
        rates = context.features.players.get(pid) if context.features else None
        opponent, fixture_count = _opponent(fixtures, team_id, selected_id, teams)
        fixture_started = live_gw and _team_fixture_started(fixtures, team_id, selected_id)
        ownership = meta.get("selected_by_percent")
        try:
            ownership_f = float(ownership) if ownership not in (None, "") else None
        except (TypeError, ValueError):
            ownership_f = None
        photo = meta.get("code")
        status, chance, news = availability_fields(meta)
        pos = int(pick["position"]) if pick.get("position") is not None else None
        now_cost = int(meta.get("now_cost") or 0)
        held = next((p for p in squad.players if p.element_id == pid), None)
        selling = held.selling_price if held is not None else now_cost
        live_row = live.get(pid)
        actual = live_row[0] if live_row is not None else None
        minutes = live_row[1] if live_row is not None else None
        rows.append(
            BoardPlayerRow(
                element_id=pid,
                web_name=str(meta.get("web_name") or pid),
                team_id=team_id,
                team_short=teams.get(team_id, "?"),
                element_type=int(meta.get("element_type") or 0),
                position=pos,
                is_captain=bool(pick.get("is_captain")),
                is_vice_captain=bool(pick.get("is_vice_captain")),
                photo_code=int(photo) if photo not in (None, "") else None,
                selected_by_percent=ownership_f,
                now_cost=money(now_cost),
                selling_price=money(int(selling)),
                xgi90=rates.xgi90 if rates is not None else None,
                flag=availability_note(meta),
                status=status,
                chance_of_playing=chance,
                news=news,
                metric_xp=float(xp.per_event.get(selected_id, 0.0)),
                metric_actual=actual if live_gw else None,
                minutes_played=minutes if live_gw else None,
                fixture_started=fixture_started,
                opponent=opponent,
                fixture_count=fixture_count,
            )
        )
        placeholder = placeholder or xp.placeholder

    pin_armbands_to_xi(rows)
    team_xp = 0.0
    for row in rows:
        if row.position is not None and row.position > 11:
            continue
        applied = row.metric_xp * (2.0 if row.is_captain else 1.0)
        team_xp += applied

    header = entry_summary(squad)
    return BoardResponse(
        **header.model_dump(),
        event=selected,
        events=events,
        mode=mode,
        picks_published=picks is not None,
        xp_source=xp_source(context),
        placeholder=placeholder,
        team_xp=round(team_xp, 3),
        players=rows,
    )


def player_search(
    context: ModelContext,
    q: str,
    element_type: int | None,
    limit: int,
) -> PlayerSearchResponse:
    needle = fold_search_text(q.strip())
    teams = _club_map(context)
    scored: list[tuple[int, PlayerSearchRow]] = []
    for player in context.bootstrap.get("elements") or []:
        if element_type is not None and int(player.get("element_type") or 0) != element_type:
            continue
        web_name = str(player.get("web_name") or "")
        first = str(player.get("first_name") or "")
        second = str(player.get("second_name") or "")
        blob = fold_search_text(f"{web_name} {first} {second}")
        if needle not in blob:
            continue
        pid = int(player.get("id") or 0)
        team_id = int(player.get("team") or 0)
        status, chance, news = availability_fields(player)
        photo = player.get("code")
        rank = 0 if fold_search_text(web_name).startswith(needle) else 1
        scored.append(
            (
                rank,
                PlayerSearchRow(
                    element_id=pid,
                    web_name=web_name or str(pid),
                    team_id=team_id,
                    team_short=teams.get(team_id, "?"),
                    element_type=int(player.get("element_type") or 0),
                    now_cost=money(int(player.get("now_cost") or 0)),
                    photo_code=int(photo) if photo not in (None, "") else None,
                    status=status,
                    chance_of_playing=chance,
                    news=news,
                ),
            )
        )
    scored.sort(key=lambda item: (item[0], item[1].web_name.lower()))
    return PlayerSearchResponse(q=q.strip(), limit=limit, players=[row for _, row in scored[:limit]])


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
