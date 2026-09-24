from __future__ import annotations

from fastapi.testclient import TestClient

from fpl_radar.api.app import create_app
from fpl_radar.api.runtime import Runtime
from fpl_radar.fpl_rules import tenths_to_pounds
from fpl_radar.xp.model import ModelContext
from tests.conftest import client_from_routes, public_routes
from tests.fixtures import bootstrap_sample


def _app(monkeypatch) -> TestClient:
    monkeypatch.setenv("FPL_SYNC_TOKEN", "secret")
    boot = bootstrap_sample()
    runtime = Runtime(
        client_factory=lambda: client_from_routes(public_routes()),
        context=ModelContext(bootstrap=boot),
    )
    return TestClient(create_app(runtime))


def test_tenths_to_pounds() -> None:
    assert tenths_to_pounds(12) == 1.2
    assert tenths_to_pounds(6) == 0.6


def test_status_uses_seeded_context(monkeypatch) -> None:
    client = _app(monkeypatch)
    response = client.get("/v1/status")
    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is True
    assert body["current_event"] == 2
    assert body["placeholder_xp"] is True
    assert body["features_ready"] is False


def test_sync_requires_token(monkeypatch) -> None:
    monkeypatch.delenv("FPL_SYNC_TOKEN", raising=False)
    boot = bootstrap_sample()
    runtime = Runtime(
        client_factory=lambda: client_from_routes(public_routes()),
        context=ModelContext(bootstrap=boot),
    )
    client = TestClient(create_app(runtime))
    assert client.post("/v1/sync").status_code == 503


def test_sync_rejects_bad_token(monkeypatch) -> None:
    client = _app(monkeypatch)
    assert client.post("/v1/sync", headers={"X-Sync-Token": "nope"}).status_code == 401


def test_sync_rebuilds_context(monkeypatch) -> None:
    monkeypatch.setenv("FPL_SYNC_TOKEN", "secret")
    boot = bootstrap_sample()
    runtime = Runtime(
        client_factory=lambda: client_from_routes(public_routes()),
        context=ModelContext(bootstrap=boot),
    )

    def fake_sync() -> dict:
        runtime.last_sync_at = 1.0
        return {
            "fpl": {"players": 1},
            "understat": {"players": 1},
            "identity": {
                "fpl_players": 1,
                "understat_players": 1,
                "matched": 1,
                "unmatched_fpl": 0,
                "unmatched_fpl_with_minutes": 0,
                "unmatched_understat": 0,
                "unmatched_understat_with_minutes": 0,
            },
        }

    monkeypatch.setattr(runtime, "sync", fake_sync)
    client = TestClient(create_app(runtime))
    response = client.post("/v1/sync", headers={"X-Sync-Token": "secret"})
    assert response.status_code == 200
    assert response.json()["fpl"]["players"] == 1


def test_entry_and_squad(monkeypatch) -> None:
    client = _app(monkeypatch)
    entry = client.get("/v1/entries/99")
    assert entry.status_code == 200
    body = entry.json()
    assert body["entry_id"] == 99
    assert body["name"] == "Test FC"
    assert body["bank"] == {"tenths": 12, "pounds": 1.2}
    assert body["authenticated"] is False

    squad = client.get("/v1/entries/99/squad?horizon=2")
    assert squad.status_code == 200
    payload = squad.json()
    assert payload["horizon"] == 2
    assert payload["event_ids"] == [2]
    assert len(payload["players"]) == 15
    assert "horizon_xp" in payload["players"][0]
    assert payload["placeholder"] is True
