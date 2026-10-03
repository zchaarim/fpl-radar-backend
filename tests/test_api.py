from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient
from tests.conftest import client_from_routes, public_routes
from tests.fixtures import bootstrap_sample

from fpl_radar import config
from fpl_radar.api.app import create_app, resolve_sync_interval
from fpl_radar.api.runtime import Runtime, SyncInProgress
from fpl_radar.clients.fpl import FplApiError
from fpl_radar.fpl_rules import tenths_to_pounds
from fpl_radar.xp import model as xp_model
from fpl_radar.xp.model import ModelContext, precompute_player_xp


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


def test_recommendations(monkeypatch) -> None:
    from collections import Counter

    client = _app(monkeypatch)
    response = client.get("/v1/entries/99/recommendations?horizon=2&limit=1")
    assert response.status_code == 200
    body = response.json()
    assert body["entry_id"] == 99
    assert body["horizon"] == 2
    assert body["limit"] == 1
    assert body["options"]
    counts = Counter(row["element_type"] for row in body["options"])
    assert all(n <= 1 for n in counts.values())
    first = body["options"][0]
    assert "delta" in first
    assert first["selling_price"]["tenths"] > 0
    assert "pounds" in first["bank_after"]


def test_recommendations_remove_player(monkeypatch) -> None:
    client = _app(monkeypatch)
    response = client.get("/v1/entries/99/recommendations?horizon=2&limit=10&remove_player=MID3")
    assert response.status_code == 200
    body = response.json()
    assert body["remove_player_id"] == 10
    assert body["remove_player_name"] == "MID3"
    assert body["options"]
    assert all(row["element_out"] == 10 for row in body["options"])


def test_recommendations_unknown_player(monkeypatch) -> None:
    client = _app(monkeypatch)
    response = client.get("/v1/entries/99/recommendations?remove_player=Nobody")
    assert response.status_code == 400


def test_precompute_player_xp_covers_roster() -> None:
    boot = bootstrap_sample()
    ctx = precompute_player_xp(ModelContext(bootstrap=boot), horizon=2)
    assert ctx.xp_event_ids == [2]
    assert set(ctx.xp_by_player) == {int(p["id"]) for p in boot["elements"]}


def test_xp_listing_per_position_limit(monkeypatch) -> None:
    from collections import Counter

    from fpl_radar.fpl_rules import POSITION_ORDER

    client = _app(monkeypatch)
    response = client.get("/v1/xp?horizon=2&limit=1")
    assert response.status_code == 200
    body = response.json()
    assert body["horizon"] == 2
    assert body["limit"] == 1
    assert body["placeholder"] is True
    counts = Counter(row["element_type"] for row in body["players"])
    assert all(n <= 1 for n in counts.values())
    assert set(counts) <= set(POSITION_ORDER)
    assert "horizon_xp" in body["players"][0]
    assert body["players"][0]["now_cost"]["tenths"] > 0


def test_xgi_requires_features(monkeypatch) -> None:
    client = _app(monkeypatch)
    response = client.get("/v1/xgi")
    assert response.status_code == 503


def test_xgi_listing(monkeypatch) -> None:
    from collections import Counter

    from tests.test_features import _us_league

    from fpl_radar.features import build_feature_set

    boot = bootstrap_sample()
    runtime = Runtime(
        client_factory=lambda: client_from_routes(public_routes()),
        context=ModelContext(bootstrap=boot, features=build_feature_set(boot, _us_league())),
    )
    client = _app(monkeypatch, runtime)
    response = client.get("/v1/xgi?limit=2&min_minutes=0")
    assert response.status_code == 200
    body = response.json()
    assert body["limit"] == 2
    assert body["min_minutes"] == 0
    assert body["players"]
    assert "xgi90" in body["players"][0]
    counts = Counter(row["element_type"] for row in body["players"])
    assert all(n <= 2 for n in counts.values())


def test_plan_returns_one_object(monkeypatch) -> None:
    from fpl_radar.models import PlanMove, TransferPlan

    def fake_make(*_args, **kwargs) -> TransferPlan:
        return TransferPlan(
            chip=kwargs.get("chip"),
            n_transfers=1,
            free_transfers=1,
            hits=0,
            hit_cost=0.0,
            current_xi=10.0,
            planned_xi=12.0,
            delta_xi=2.0,
            delta_net=2.0,
            bank_after=5,
            squad_ids=list(range(1, 16)),
            starter_ids=list(range(1, 12)),
            moves=[
                PlanMove(
                    element_out=10,
                    element_in=16,
                    out_name="MID3",
                    in_name="MID6",
                    selling_price=60,
                    now_cost_in=85,
                    cash_delta=-25,
                    element_type=3,
                )
            ],
            placeholder=True,
        )

    monkeypatch.setattr("fpl_radar.api.serialize.make_plan", fake_make)
    client = _app(monkeypatch)
    response = client.post(
        "/v1/entries/99/plan",
        json={"horizon": 5, "transfers": 3, "chip": "none"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["entry_id"] == 99
    assert body["chip"] is None
    assert body["n_transfers"] == 1
    assert body["delta_net"] == 2.0
    assert body["bank_after"] == {"tenths": 5, "pounds": 0.5}
    assert len(body["moves"]) == 1
    assert body["moves"][0]["out_name"] == "MID3"
    assert len(body["squad"]) == 15
    assert body["squad"][0]["role"] in {"XI", "bench"}
    assert isinstance(body, dict) and "plans" not in body


def test_plan_freehit_forces_horizon_one(monkeypatch) -> None:
    from fpl_radar.models import TransferPlan

    captured: dict = {}

    def fake_make(*_args, **kwargs) -> TransferPlan:
        captured["horizon"] = kwargs.get("horizon")
        captured["chip"] = kwargs.get("chip")
        return TransferPlan(chip="freehit", squad_ids=list(range(1, 16)), starter_ids=list(range(1, 12)))

    monkeypatch.setattr("fpl_radar.api.serialize.make_plan", fake_make)
    client = _app(monkeypatch)
    response = client.post("/v1/entries/99/plan", json={"horizon": 5, "chip": "freehit"})
    assert response.status_code == 200
    assert captured["chip"] == "freehit"
    assert captured["horizon"] == 1
    assert response.json()["horizon"] == 1
    assert response.json()["chip"] == "freehit"


def test_plan_unknown_remove_player(monkeypatch) -> None:
    client = _app(monkeypatch)
    response = client.post("/v1/entries/99/plan", json={"remove_player": ["Nobody"]})
    assert response.status_code == 400


def test_plan_infeasible(monkeypatch) -> None:
    def boom(*_args, **_kwargs):
        raise RuntimeError("Could not find a legal plan (infeasible squad/budget).")

    monkeypatch.setattr("fpl_radar.api.serialize.make_plan", boom)
    client = _app(monkeypatch)
    response = client.post("/v1/entries/99/plan", json={"chip": "wildcard"})
    assert response.status_code == 422


def test_plan_conflict(monkeypatch) -> None:
    from fpl_radar.api.runtime import PlanInProgress

    runtime = _runtime()

    def busy() -> None:
        raise PlanInProgress("Plan already in progress")

    monkeypatch.setattr(runtime, "begin_plan", busy)
    client = _app(monkeypatch, runtime)
    response = client.post("/v1/entries/99/plan", json={})
    assert response.status_code == 409


def test_unknown_entry_is_404_without_upstream_body(monkeypatch) -> None:
    client = _app(monkeypatch)
    response = client.get("/v1/entries/1")
    assert response.status_code == 404
    assert response.json()["detail"] == "Entry not found"
    assert "fantasy.premierleague" not in response.text


def test_bank_override_on_entry(monkeypatch) -> None:
    client = _app(monkeypatch)
    response = client.get("/v1/entries/99?bank=2.5")
    assert response.status_code == 200
    body = response.json()
    assert body["bank"] == {"tenths": 25, "pounds": 2.5}
    assert body["bank_source"] == "caller_override"


def test_status_hides_cache_dir_without_sync_token(monkeypatch) -> None:
    client = _app(monkeypatch)
    public = client.get("/v1/status")
    assert public.status_code == 200
    assert public.json()["cache_dir"] == ""
    authed = client.get("/v1/status", headers={"X-Sync-Token": "secret"})
    assert authed.json()["cache_dir"]


def test_invalid_sync_interval_falls_back(monkeypatch) -> None:
    monkeypatch.setenv("FPL_SYNC_INTERVAL_SECONDS", "hourly")
    assert resolve_sync_interval(None) == config.DEFAULT_SYNC_INTERVAL_SECONDS


def test_get_context_rebuild_serves_stale_and_does_not_hold_lock() -> None:
    boot = bootstrap_sample()
    runtime = Runtime(
        client_factory=lambda: client_from_routes(public_routes()),
        context=ModelContext(bootstrap=boot),
    )
    runtime.context_built_at = time.time() - config.CONTEXT_TTL_SECONDS - 1
    started = threading.Event()
    unblock = threading.Event()

    def slow_build(client=None) -> ModelContext:
        started.set()
        assert unblock.wait(timeout=5)
        ctx = ModelContext(bootstrap=boot)
        precompute_player_xp(ctx)
        return ctx

    runtime._build_context = slow_build  # type: ignore[method-assign]
    worker = threading.Thread(target=runtime.get_context)
    worker.start()
    assert started.wait(timeout=2)
    t0 = time.time()
    assert runtime.syncing() is False
    runtime.begin_plan()
    runtime.end_plan()
    assert time.time() - t0 < 0.5
    assert runtime.get_context().bootstrap is boot
    unblock.set()
    worker.join(timeout=5)
    assert not worker.is_alive()


def test_scheduled_sync_runs_immediately(monkeypatch) -> None:
    runtime = _runtime()
    hits = {"n": 0}

    def fake_sync() -> dict:
        hits["n"] += 1
        return {
            "fpl": {},
            "understat": {},
            "identity": {
                "fpl_players": 0,
                "understat_players": 0,
                "matched": 0,
                "unmatched_fpl": 0,
                "unmatched_fpl_with_minutes": 0,
                "unmatched_understat": 0,
                "unmatched_understat_with_minutes": 0,
            },
        }

    monkeypatch.setattr(runtime, "sync", fake_sync)
    monkeypatch.setenv("FPL_SYNC_TOKEN", "secret")
    with TestClient(create_app(runtime, sync_interval_seconds=3600)):
        time.sleep(0.2)
    assert hits["n"] >= 1


def test_plan_duplicate_remove_player_is_ok(monkeypatch) -> None:
    captured: dict = {}

    def fake_make(*_args, **kwargs):
        from fpl_radar.models import TransferPlan

        captured["remove"] = kwargs.get("remove_player_ids")
        return TransferPlan(squad_ids=list(range(1, 16)), starter_ids=list(range(1, 12)))

    monkeypatch.setattr("fpl_radar.api.serialize.make_plan", fake_make)
    client = _app(monkeypatch)
    response = client.post(
        "/v1/entries/99/plan",
        json={"remove_player": ["MID3", "MID3"]},
    )
    assert response.status_code == 200
    assert captured["remove"] == [10]


def test_plan_fpl_error_is_502_not_422(monkeypatch) -> None:
    runtime = _runtime()

    def boom() -> ModelContext:
        raise FplApiError("GET https://fantasy.premierleague.com/api/bootstrap-static/ failed: 500 oops", status_code=500)

    monkeypatch.setattr(runtime, "get_context", boom)
    client = _app(monkeypatch, runtime)
    response = client.post("/v1/entries/99/plan", json={})
    assert response.status_code == 502
    assert response.json()["detail"] == "FPL API request failed"
    assert "fantasy.premierleague" not in response.text
    assert runtime._planning is False


def test_plan_solver_through_api(monkeypatch) -> None:
    import importlib

    from tests.test_plan import _squad

    app_mod = importlib.import_module("fpl_radar.api.app")
    monkeypatch.setattr(app_mod, "load_manager_squad", lambda *_args, **_kwargs: _squad())
    client = _app(monkeypatch)
    response = client.post(
        "/v1/entries/99/plan",
        json={"horizon": 1, "transfers": 1, "chip": "none"},
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["squad"]) == 15
    assert "plans" not in body
    assert body["n_transfers"] == 1
