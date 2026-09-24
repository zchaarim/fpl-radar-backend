from __future__ import annotations

import hmac
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from fpl_radar import config
from fpl_radar.api.runtime import PlanInProgress, Runtime, SyncInProgress
from fpl_radar.api.schemas import PlanRequest, StatusResponse, SyncResponse
from fpl_radar.api.serialize import (
    current_event_id,
    entry_summary,
    plan_payload,
    recommendations_payload,
    squad_payload,
    xgi_listing,
    xp_listing,
)
from fpl_radar.clients.fpl import FplApiError
from fpl_radar.identity.match import identity_coverage
from fpl_radar.squad import load_manager_squad

logger = logging.getLogger(__name__)


def cors_origins() -> list[str]:
    raw = os.environ.get(config.CORS_ORIGINS_ENV, "")
    if raw.strip():
        origins = [part.strip() for part in raw.split(",") if part.strip()]
    else:
        origins = list(config.DEFAULT_CORS_ORIGINS)
    if "*" in origins:
        logger.warning(
            "FPL_CORS_ORIGINS cannot include * while credentials are enabled; listing explicit origins"
        )
        origins = [origin for origin in origins if origin != "*"]
    return origins or list(config.DEFAULT_CORS_ORIGINS)


def resolve_sync_interval(override: int | None) -> int:
    if override is not None:
        return max(0, int(override))
    raw = os.environ.get(config.SYNC_INTERVAL_ENV)
    if raw is None or not str(raw).strip():
        return config.DEFAULT_SYNC_INTERVAL_SECONDS
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", config.SYNC_INTERVAL_ENV, raw, config.DEFAULT_SYNC_INTERVAL_SECONDS)
        return config.DEFAULT_SYNC_INTERVAL_SECONDS


def sync_token_matches(provided: str | None, expected: str) -> bool:
    got = (provided or "").encode("utf-8")
    want = expected.encode("utf-8")
    return hmac.compare_digest(got, want)


def raise_fpl_http(exc: FplApiError, *, not_found_detail: str | None = None) -> None:
    logger.warning("FPL request failed: %s", exc)
    if not_found_detail is not None and exc.status_code == 404:
        raise HTTPException(status_code=404, detail=not_found_detail) from exc
    raise HTTPException(status_code=502, detail="FPL API request failed") from exc


def create_app(
    runtime: Runtime | None = None,
    sync_interval_seconds: int | None = None,
) -> FastAPI:
    rt = runtime or Runtime()
    interval = resolve_sync_interval(sync_interval_seconds)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        stop = threading.Event()

        def loop() -> None:
            while True:
                try:
                    rt.sync()
                except SyncInProgress:
                    logger.info("Skipping scheduled sync; one is already running")
                except Exception:
                    logger.exception("Scheduled league sync failed")
                if stop.wait(interval):
                    break

        worker: threading.Thread | None = None
        if interval > 0:
            worker = threading.Thread(target=loop, name="fpl-radar-sync", daemon=True)
            worker.start()
        yield
        stop.set()

    app = FastAPI(title="FPL Radar", version="0.1.0", lifespan=lifespan)
    app.state.runtime = rt
    app.state.sync_interval_seconds = interval
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def load_entry_squad(entry_id: int, budget_remaining: float | None = None):
        try:
            return load_manager_squad(
                rt.fpl_client(),
                entry_id,
                budget_remaining=budget_remaining,
            )
        except FplApiError as exc:
            raise_fpl_http(exc, not_found_detail="Entry not found")

    def model_context():
        try:
            return rt.get_context()
        except FplApiError as exc:
            raise_fpl_http(exc)

    @app.get("/v1/status", response_model=StatusResponse)
    def status(
        x_sync_token: Annotated[str | None, Header()] = None,
    ) -> StatusResponse:
        ctx = model_context()
        identity = identity_coverage(
            ctx.bootstrap.get("elements") or [],
            (ctx.understat_league or {}).get("players") or [],
            ctx.player_match,
        )
        expected = os.environ.get(config.SYNC_TOKEN_ENV, "")
        cache_dir = ""
        if expected and sync_token_matches(x_sync_token, expected):
            cache_dir = str(config.CACHE_DIR)
        return StatusResponse(
            ready=True,
            current_event=current_event_id(ctx.bootstrap),
            features_ready=ctx.features is not None,
            placeholder_xp=ctx.features is None,
            last_sync_at=rt.last_sync_at,
            context_built_at=rt.context_built_at,
            context_age_seconds=rt.context_age_seconds(),
            context_stale=rt.context_stale(),
            syncing=rt.syncing(),
            xp_precomputed=len(ctx.xp_by_player),
            sync_interval_seconds=interval,
            identity=identity,
            cache_dir=cache_dir,
        )

    @app.post("/v1/sync", response_model=SyncResponse)
    def sync(
        x_sync_token: Annotated[str | None, Header()] = None,
    ) -> SyncResponse:
        expected = os.environ.get(config.SYNC_TOKEN_ENV, "")
        if not expected:
            raise HTTPException(status_code=503, detail="FPL_SYNC_TOKEN is not configured")
        if not sync_token_matches(x_sync_token, expected):
            raise HTTPException(status_code=401, detail="Invalid sync token")
        try:
            payload = rt.sync()
        except SyncInProgress as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except FplApiError as exc:
            raise_fpl_http(exc)
        return SyncResponse(
            fpl=payload["fpl"],
            understat=payload["understat"],
            identity=payload["identity"],
            last_sync_at=rt.last_sync_at,
        )

    @app.get("/v1/entries/{entry_id}")
    def entry(
        entry_id: int,
        bank: Annotated[float | None, Query(ge=0)] = None,
    ):
        return entry_summary(load_entry_squad(entry_id, budget_remaining=bank))

    @app.get("/v1/entries/{entry_id}/squad")
    def squad(
        entry_id: int,
        horizon: Annotated[int, Query(ge=1, le=15)] = config.DEFAULT_SQUAD_HORIZON,
        bank: Annotated[float | None, Query(ge=0)] = None,
    ):
        return squad_payload(
            load_entry_squad(entry_id, budget_remaining=bank),
            model_context(),
            horizon,
        )

    @app.get("/v1/entries/{entry_id}/recommendations")
    def recommendations(
        entry_id: int,
        horizon: Annotated[int, Query(ge=1, le=15)] = config.DEFAULT_SQUAD_HORIZON,
        limit: Annotated[int, Query(ge=1, le=50)] = config.DEFAULT_LIST_LIMIT,
        remove_player: Annotated[str | None, Query()] = None,
        bank: Annotated[float | None, Query(ge=0)] = None,
    ):
        loaded = load_entry_squad(entry_id, budget_remaining=bank)
        try:
            return recommendations_payload(
                loaded,
                model_context(),
                horizon=horizon,
                limit=limit,
                remove_player=remove_player,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/v1/entries/{entry_id}/plan")
    def plan(entry_id: int, body: PlanRequest):
        loaded = load_entry_squad(entry_id, budget_remaining=body.bank)
        try:
            rt.begin_plan()
        except PlanInProgress as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            return plan_payload(loaded, model_context(), body)
        except FplApiError as exc:
            raise_fpl_http(exc)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        finally:
            rt.end_plan()

    @app.get("/v1/xp")
    def xp(
        horizon: Annotated[int, Query(ge=1, le=15)] = config.DEFAULT_SQUAD_HORIZON,
        limit: Annotated[int, Query(ge=1, le=50)] = config.DEFAULT_LIST_LIMIT,
    ):
        return xp_listing(model_context(), horizon=horizon, limit=limit)

    @app.get("/v1/xgi")
    def xgi(
        limit: Annotated[int, Query(ge=1, le=50)] = config.DEFAULT_LIST_LIMIT,
        min_minutes: Annotated[float, Query(ge=0)] = 0.0,
    ):
        try:
            return xgi_listing(model_context(), limit=limit, min_minutes=min_minutes)
        except ValueError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "fpl_radar.api.app:app",
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "8000")),
    )


if __name__ == "__main__":
    main()
