from __future__ import annotations

import logging
from typing import Any

from fpl_radar.clients.auth import FplAuthClient
from fpl_radar.clients.fpl import FplApiError, FplClient
from fpl_radar.fpl_rules import (
    DEFAULT_FREE_TRANSFERS,
    estimated_selling_price,
    sell_on_fee,
    start_price,
)
from fpl_radar.models import ManagerSquad, PriceSource, SquadPlayer

logger = logging.getLogger(__name__)


def current_event(events: list[dict[str, Any]]) -> tuple[int, bool]:
    for event in events:
        if event.get("is_current"):
            return int(event["id"]), bool(event.get("finished"))
    for event in events:
        if event.get("is_next"):
            return int(event["id"]), False
    finished = [e for e in events if e.get("finished")]
    if finished:
        last = max(finished, key=lambda e: int(e["id"]))
        return int(last["id"]), True
    raise FplApiError("Could not determine current event from bootstrap.")


def first_event_id(events: list[dict[str, Any]]) -> int:
    return min(int(e["id"]) for e in events)


def last_finished_event_id(events: list[dict[str, Any]], current_id: int) -> int:
    finished = [int(e["id"]) for e in events if e.get("finished")]
    if finished:
        return max(finished)
    return max(1, current_id - 1)


def _picks_or_none(client: FplClient, entry_id: int, event_id: int) -> dict[str, Any] | None:
    try:
        payload = client.entry_picks(entry_id, event_id)
    except FplApiError:
        return None
    if not payload or not payload.get("picks"):
        return None
    return payload


def reconstruct_pick_elements(
    client: FplClient,
    entry_id: int,
    events: list[dict[str, Any]],
    transfers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    current_id, finished = current_event(events)
    current_picks = _picks_or_none(client, entry_id, current_id)
    if current_picks:
        return current_picks["picks"], current_id

    prev_id = last_finished_event_id(events, current_id)
    prev_picks = _picks_or_none(client, entry_id, prev_id)
    if not prev_picks:
        raise FplApiError(f"No published picks for entry {entry_id}")

    squad = [int(p["element"]) for p in prev_picks["picks"]]
    pending = [t for t in transfers if int(t.get("event") or 0) == current_id]
    pending.sort(key=lambda t: t.get("time") or "")
    for transfer in pending:
        out_id = int(transfer["element_out"])
        in_id = int(transfer["element_in"])
        if out_id in squad:
            squad[squad.index(out_id)] = in_id
        else:
            squad.append(in_id)
    picks = []
    for i, element_id in enumerate(squad, start=1):
        picks.append({"element": element_id, "position": i})
    return picks, current_id if not finished else prev_id


def purchase_ledger(
    gw1_picks: list[dict[str, Any]],
    transfers: list[dict[str, Any]],
    players_by_id: dict[int, dict[str, Any]],
) -> dict[int, int]:
    purchases: dict[int, int] = {}
    gw1_in_costs = {
        int(t["element_in"]): int(t["element_in_cost"])
        for t in transfers
        if int(t.get("event") or 0) == 1
    }
    for pick in gw1_picks:
        element_id = int(pick["element"])
        if element_id in gw1_in_costs:
            purchases[element_id] = gw1_in_costs[element_id]
        elif element_id in players_by_id:
            purchases[element_id] = start_price(players_by_id[element_id])
    ordered = sorted(transfers, key=lambda t: (int(t.get("event") or 0), t.get("time") or ""))
    for transfer in ordered:
        out_id = int(transfer["element_out"])
        in_id = int(transfer["element_in"])
        purchases.pop(out_id, None)
        purchases[in_id] = int(transfer["element_in_cost"])
    return purchases


def _bank_from_public(
    entry: dict[str, Any],
    history: dict[str, Any],
) -> tuple[int, str]:
    if entry.get("last_deadline_bank") is not None:
        return int(entry["last_deadline_bank"]), "last_deadline_bank"
    current = history.get("current") or []
    if current:
        last = current[-1]
        if last.get("bank") is not None:
            return int(last["bank"]), "entry_history.bank"
    return 0, "missing"


def remaining_free_transfers(transfers_block: dict[str, Any] | None) -> int | None:
    """``my-team.transfers``: remaining FT = limit − made. None if the payload omits limit."""
    if not transfers_block or transfers_block.get("limit") is None:
        return None
    limit = int(transfers_block["limit"])
    made = int(transfers_block.get("made") or 0)
    return max(0, limit - made)


def resolve_owned_players(squad: ManagerSquad, tokens: list[str]) -> list[int]:
    """Map CLI tokens (element id or web_name) to squad player ids. Order preserved."""
    by_id = {p.element_id: p for p in squad.players}
    by_name: dict[str, list] = {}
    for player in squad.players:
        by_name.setdefault(player.web_name.lower(), []).append(player)
    resolved: list[int] = []
    for raw in tokens:
        token = str(raw).strip()
        if not token:
            continue
        if token.isdigit():
            pid = int(token)
            if pid not in by_id:
                raise ValueError(f"Player {pid} is not in the squad")
            if pid not in resolved:
                resolved.append(pid)
            continue
        matches = by_name.get(token.lower()) or []
        if not matches:
            raise ValueError(f"No squad player matching {token!r}")
        if len(matches) > 1:
            raise ValueError(f"Ambiguous web name {token!r}")
        pid = matches[0].element_id
        if pid not in resolved:
            resolved.append(pid)
    return resolved


def load_manager_squad(
    client: FplClient,
    entry_id: int,
    budget_remaining: float | None = None,
    auth_client: FplAuthClient | None = None,
) -> ManagerSquad:
    bootstrap = client.bootstrap_static()
    events = bootstrap.get("events") or []
    players_by_id = client.players_by_id(bootstrap)
    game_settings = bootstrap.get("game_settings") or {}
    fee = sell_on_fee(game_settings)

    entry = client.entry(entry_id)
    history = client.entry_history(entry_id)
    transfers = client.entry_transfers(entry_id) or []

    picks, event_used = reconstruct_pick_elements(client, entry_id, events, transfers)
    gw1_payload = _picks_or_none(client, entry_id, first_event_id(events))
    gw1_picks = gw1_payload["picks"] if gw1_payload else picks
    purchases = purchase_ledger(gw1_picks, transfers, players_by_id)

    bank, bank_source = _bank_from_public(entry, history)
    authenticated = False
    my_team: dict[str, Any] | None = None
    free_transfers = DEFAULT_FREE_TRANSFERS
    free_transfers_source = "default"

    if auth_client is not None:
        auth_client.require_entry_match(entry_id)
        my_team = auth_client.my_team(entry_id)
        authenticated = True
        transfers_block = my_team.get("transfers") or {}
        if transfers_block.get("bank") is not None:
            bank, bank_source = int(transfers_block["bank"]), "my_team.transfers.bank"
        remaining = remaining_free_transfers(transfers_block)
        if remaining is not None:
            free_transfers = remaining
            free_transfers_source = "my_team.transfers"
        auth_ids = {int(p["element"]) for p in my_team.get("picks") or []}
        public_ids = {int(p["element"]) for p in picks}
        if auth_ids and public_ids and auth_ids != public_ids:
            logger.warning(
                "Authenticated squad %s differs from public reconstruction %s; using my-team picks",
                sorted(auth_ids),
                sorted(public_ids),
            )
            picks = my_team["picks"]

    if budget_remaining is not None:
        bank = int(round(budget_remaining * 10))
        bank_source = "caller_override"

    auth_prices: dict[int, dict[str, Any]] = {}
    if my_team:
        for pick in my_team.get("picks") or []:
            auth_prices[int(pick["element"])] = pick

    squad_players: list[SquadPlayer] = []
    for pick in picks:
        element_id = int(pick["element"])
        meta = players_by_id.get(element_id) or {}
        now_cost = int(meta.get("now_cost") or 0)
        source = PriceSource.ESTIMATED
        purchase = purchases.get(element_id)
        if purchase is None:
            purchase = now_cost
            source = PriceSource.FALLBACK_NOW_COST
            logger.warning("Missing purchase price for element %s; using now_cost", element_id)
        selling = estimated_selling_price(purchase, now_cost, fee)

        auth_pick = auth_prices.get(element_id)
        if auth_pick:
            if auth_pick.get("purchase_price") is not None:
                purchase = int(auth_pick["purchase_price"])
            if auth_pick.get("selling_price") is not None:
                selling = int(auth_pick["selling_price"])
            source = PriceSource.MY_TEAM

        squad_players.append(
            SquadPlayer(
                element_id=element_id,
                web_name=meta.get("web_name") or str(element_id),
                team_id=int(meta.get("team") or 0),
                element_type=int(meta.get("element_type") or 0),
                now_cost=now_cost,
                purchase_price=int(purchase),
                selling_price=int(selling),
                price_source=source,
                position=pick.get("position"),
                is_captain=bool(pick.get("is_captain")),
                is_vice_captain=bool(pick.get("is_vice_captain")),
                multiplier=int(pick.get("multiplier") or 1),
            )
        )

    return ManagerSquad(
        entry_id=entry_id,
        name=entry.get("name"),
        current_event=event_used,
        bank=bank,
        bank_source=bank_source,
        players=squad_players,
        authenticated=authenticated,
        free_transfers=free_transfers,
        free_transfers_source=free_transfers_source,
    )
