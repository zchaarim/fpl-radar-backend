from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from fpl_radar import config
from fpl_radar.api.app import create_app
from fpl_radar.api.runtime import Runtime, SyncInProgress
from fpl_radar.fpl_rules import tenths_to_pounds
from fpl_radar.xp import model as xp_model
from fpl_radar.xp.model import ModelContext, precompute_player_xp
from tests.conftest import client_from_routes, public_routes
from tests.fixtures import bootstrap_sample


def _runtime() -> Runtime:
    boot = bootstrap_sample()
    return Runtime(
        client_factory=lambda: client_from_routes(public_routes()),
        context=ModelContext(bootstrap=boot),
    )


def _app(monkeypatch, runtime: Runtime | None = None) -> TestClient:
    monkeypatch.setenv("FPL_SYNC_TOKEN", "secret")
    return TestClient(create_app(runtime or _runtime(), sync_interval_seconds=0))


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
    assert body["syncing"] is False
    assert body["context_stale"] is False
    assert body["xp_precomputed"] > 0
    assert body["sync_interval_seconds"] == 0


def test_sync_requires_token(monkeypatch) -> None:
    monkeypatch.delenv("FPL_SYNC_TOKEN", raising=False)
    client = TestClient(create_app(_runtime(), sync_interval_seconds=0))
    assert client.post("/v1/sync").status_code == 503


def test_sync_rejects_bad_token(monkeypatch) -> None:
    client = _app(monkeypatch)
    assert client.post("/v1/sync", headers={"X-Sync-Token": "nope"}).status_code == 401


def test_sync_rebuilds_context(monkeypatch) -> None:
    monkeypatch.setenv("FPL_SYNC_TOKEN", "secret")
    runtime = _runtime()

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
    client = TestClient(create_app(runtime, sync_interval_seconds=0))
    response = client.post("/v1/sync", headers={"X-Sync-Token": "secret"})
    assert response.status_code == 200
    assert response.json()["fpl"]["players"] == 1


def test_sync_conflict_http(monkeypatch) -> None:
    monkeypatch.setenv("FPL_SYNC_TOKEN", "secret")
    runtime = _runtime()

    def busy() -> dict:
        raise SyncInProgress("Sync already in progress")

    monkeypatch.setattr(runtime, "sync", busy)
    client = TestClient(create_app(runtime, sync_interval_seconds=0))
    response = client.post("/v1/sync", headers={"X-Sync-Token": "secret"})
    assert response.status_code == 409


def test_overlapping_sync_raises(monkeypatch) -> None:
    boot = bootstrap_sample()
    runtime = Runtime(
        client_factory=lambda: client_from_routes(public_routes()),
        context=ModelContext(bootstrap=boot),
    )
    started = threading.Event()
    unblock = threading.Event()

    def slow_fpl(client=None):
        started.set()
        unblock.wait(timeout=5)
        return {"players": 1}

    monkeypatch.setattr("fpl_radar.api.runtime.sync_fpl", slow_fpl)
    monkeypatch.setattr("fpl_radar.api.runtime.sync_understat", lambda: {"players": 0})
    monkeypatch.setattr(
        "fpl_radar.api.runtime.load_model_context",
        lambda client=None: ModelContext(bootstrap=boot),
    )
    worker = threading.Thread(target=runtime.sync)
    worker.start()
    assert started.wait(timeout=2)
    with pytest.raises(SyncInProgress):
        runtime.sync()
    unblock.set()
    worker.join(timeout=5)
    assert not worker.is_alive()


def test_stale_context_reloads(monkeypatch) -> None:
    boot = bootstrap_sample()
    loads = {"n": 0}

    def fake_load(client=None) -> ModelContext:
        loads["n"] += 1
        return ModelContext(bootstrap=boot)

    monkeypatch.setattr("fpl_radar.api.runtime.load_model_context", fake_load)
    runtime = Runtime(
        client_factory=lambda: client_from_routes(public_routes()),
        context=ModelContext(bootstrap=boot),
    )
    runtime.get_context()
    assert loads["n"] == 0
    runtime.context_built_at = time.time() - config.CONTEXT_TTL_SECONDS - 1
    runtime.get_context()
    assert loads["n"] == 1


def test_squad_uses_precomputed_xp(monkeypatch) -> None:
    client = _app(monkeypatch)
    first = client.get("/v1/entries/99/squad?horizon=2")
    assert first.status_code == 200
    cached_xp = first.json()["players"][0]["horizon_xp"]

    def boom(*_args, **_kwargs):
        raise AssertionError("expected_points should not run when xP is precomputed")

    monkeypatch.setattr(xp_model, "expected_points", boom)
    second = client.get("/v1/entries/99/squad?horizon=2")
    assert second.status_code == 200
    assert second.json()["players"][0]["horizon_xp"] == cached_xp


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


def test_precompute_player_xp_covers_roster() -> None:
    boot = bootstrap_sample()
    ctx = precompute_player_xp(ModelContext(bootstrap=boot), horizon=2)
    assert ctx.xp_event_ids == [2]
    assert set(ctx.xp_by_player) == {int(p["id"]) for p in boot["elements"]}
