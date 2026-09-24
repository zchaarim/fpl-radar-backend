from __future__ import annotations

from fpl_radar.api.schemas import EntrySummary, Money, SquadPlayerRow, SquadResponse
from fpl_radar.features import availability_note
from fpl_radar.fpl_rules import tenths_to_pounds
from fpl_radar.models import ManagerSquad
from fpl_radar.xp.model import ModelContext, horizon_event_ids, player_xp


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
