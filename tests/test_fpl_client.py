from __future__ import annotations

from fpl_analyser.clients.fpl import FplApiError
from tests.conftest import FakeResponse, client_from_routes, public_routes


def test_bootstrap_and_fixtures() -> None:
    client = client_from_routes(public_routes())
    boot = client.bootstrap_static()
    assert len(boot["elements"]) >= 15
    assert client.fixtures()[0]["id"] == 1
    assert client.entry(99)["name"] == "Test FC"
    assert client.event_status()["status"] == []
    assert client.set_piece_notes()["teams"] == []


def test_live_match_log_reads_bps_and_bonus() -> None:
    routes = public_routes()
    routes["event/1/live/"] = {
        "elements": [
            {
                "id": 8,
                "stats": {"minutes": 90, "bps": 28, "bonus": 2, "defensive_contribution": 4},
            }
        ]
    }
    client = client_from_routes(routes)
    log = client.live_match_log()
    assert log[8][0]["bps"] == 28
    assert log[8][0]["bonus"] == 2


def test_http_error() -> None:
    client = client_from_routes({"bootstrap-static/": FakeResponse("nope", status_code=500)})
    try:
        client.bootstrap_static()
    except FplApiError:
        return
    raise AssertionError("expected FplApiError")
