from __future__ import annotations

from fpl_radar.clients.auth import FplAuthClient
from fpl_radar.models import PriceSource
from fpl_radar.squad import load_manager_squad, purchase_ledger, remaining_free_transfers, resolve_owned_players
from tests.conftest import FakeSession, client_from_routes, public_routes
from tests.fixtures import bootstrap_sample


def test_public_squad_bank_and_estimated_prices() -> None:
    client = client_from_routes(public_routes())
    squad = load_manager_squad(client, 99)
    assert squad.bank == 12
    assert squad.bank_source == "last_deadline_bank"
    assert len(squad.players) == 15
    assert not squad.authenticated
    assert squad.free_transfers == 1
    assert squad.free_transfers_source == "default"
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
