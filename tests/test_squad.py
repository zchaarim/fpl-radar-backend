from __future__ import annotations

from tests.conftest import FakeSession, client_from_routes, public_routes
from tests.fixtures import bootstrap_sample

from fpl_radar.clients.auth import FplAuthClient
from fpl_radar.models import PriceSource
from fpl_radar.squad import (
    apply_event_transfers,
    estimate_free_transfers,
    load_manager_squad,
    purchase_ledger,
    remaining_free_transfers,
    resolve_owned_players,
)


def test_public_squad_bank_and_estimated_prices() -> None:
    client = client_from_routes(public_routes())
    squad = load_manager_squad(client, 99)
    assert squad.bank == 12
    assert squad.bank_source == "last_deadline_bank"
    assert len(squad.players) == 15
    assert not squad.authenticated
    assert squad.free_transfers == 2
    assert squad.free_transfers_source == "history_estimate"
    assert all(p.price_source in {PriceSource.ESTIMATED, PriceSource.FALLBACK_NOW_COST} for p in squad.players)


def test_bank_override() -> None:
    client = client_from_routes(public_routes())
    squad = load_manager_squad(client, 99, budget_remaining=2.4)
    assert squad.bank == 24
    assert squad.bank_source == "caller_override"


def test_auth_prices_preferred() -> None:
    routes = public_routes()
    session = FakeSession(
        {
            "me/": {"player": {"entry": 99}},
            "my-team/99/": {
                "picks": [
                    {"element": i, "position": i, "purchase_price": 40, "selling_price": 41}
                    for i in range(1, 16)
                ],
                "transfers": {"bank": 33, "limit": 2, "made": 1},
            },
        }
    )
    auth = FplAuthClient(
        api_token="tok",
        session=session,
        base_url="https://fantasy.premierleague.com/api/",
    )
    client = client_from_routes(routes)
    squad = load_manager_squad(client, 99, auth_client=auth)
    assert squad.authenticated
    assert squad.bank == 33
    assert squad.players[0].selling_price == 41
    assert squad.players[0].price_source == PriceSource.MY_TEAM
    assert squad.free_transfers == 1
    assert squad.free_transfers_source == "my_team.transfers"


def test_purchase_ledger_applies_transfers() -> None:
    boot = bootstrap_sample()
    players = {int(p["id"]): p for p in boot["elements"]}
    gw1 = [{"element": i} for i in range(1, 16)]
    transfers = [
        {
            "event": 2,
            "element_out": 12,
            "element_in": 16,
            "element_in_cost": 85,
            "time": "t",
        }
    ]
    ledger = purchase_ledger(gw1, transfers, players)
    assert 12 not in ledger
    assert ledger[16] == 85


def test_estimate_free_transfers_rolls_and_consumes() -> None:
    events = [
        {"id": 1, "finished": True},
        {"id": 2, "finished": False},
        {"id": 3, "finished": False},
    ]
    history = {"current": [{"event": 1, "event_transfers": 0}], "chips": []}
    ft, src = estimate_free_transfers(events, history, [], current_id=2)
    assert src == "history_estimate"
    assert ft == 2
    used = [{"event": 2, "element_out": 1, "element_in": 2}]
    ft_used, _ = estimate_free_transfers(events, history, used, current_id=2)
    assert ft_used == 1


def test_estimate_free_transfers_wildcard_skips_spend() -> None:
    events = [{"id": 1, "finished": True}, {"id": 2, "finished": False}]
    history = {
        "current": [{"event": 1, "event_transfers": 8}],
        "chips": [{"name": "wildcard", "event": 1}],
    }
    ft, _ = estimate_free_transfers(events, history, [], current_id=2)
    assert ft == 2


def test_apply_event_transfers_is_idempotent_if_already_in_picks() -> None:
    picks = [{"element": i, "position": i} for i in range(1, 16)]
    moved = apply_event_transfers(
        picks,
        [{"event": 2, "element_out": 12, "element_in": 16, "time": "t"}],
        2,
    )
    assert [p["element"] for p in moved][11] == 16
    again = apply_event_transfers(
        moved,
        [{"event": 2, "element_out": 12, "element_in": 16, "time": "t"}],
        2,
    )
    assert [p["element"] for p in again][11] == 16


def test_reconstruct_applies_current_gw_transfers_on_published_picks() -> None:
    routes = public_routes()
    routes["entry/99/transfers/"] = [
        {
            "event": 2,
            "element_in": 16,
            "element_out": 12,
            "element_in_cost": 85,
            "element_out_cost": 50,
            "time": "2026-08-20T12:00:00Z",
        }
    ]
    client = client_from_routes(routes)
    squad = load_manager_squad(client, 99)
    ids = [p.element_id for p in squad.players]
    assert 16 in ids
    assert 12 not in ids
    assert squad.free_transfers == 1


def test_remaining_free_transfers() -> None:
    assert remaining_free_transfers(None) is None
    assert remaining_free_transfers({}) is None
    assert remaining_free_transfers({"limit": 2, "made": 0}) == 2
    assert remaining_free_transfers({"limit": 1, "made": 1}) == 0
    assert remaining_free_transfers({"limit": 1, "made": 3}) == 0


def test_resolve_owned_players_id_and_name() -> None:
    client = client_from_routes(public_routes())
    squad = load_manager_squad(client, 99)
    assert resolve_owned_players(squad, ["1", "GK2"]) == [1, 2]
