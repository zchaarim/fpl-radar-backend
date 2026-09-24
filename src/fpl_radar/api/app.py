from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import Annotated, AsyncIterator

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from fpl_radar import config
from fpl_radar.api.runtime import Runtime, SyncInProgress
from fpl_radar.api.schemas import StatusResponse, SyncResponse
from fpl_radar.api.serialize import current_event_id, entry_summary, squad_payload
from fpl_radar.clients.fpl import FplApiError
from fpl_radar.identity.match import identity_coverage
from fpl_radar.squad import load_manager_squad

logger = logging.getLogger(__name__)


def cors_origins() -> list[str]:
    raw = os.environ.get(config.CORS_ORIGINS_ENV, "")
    if raw.strip():
        return [part.strip() for part in raw.split(",") if part.strip()]
    return list(config.DEFAULT_CORS_ORIGINS)


def resolve_sync_interval(override: int | None) -> int:
    if override is not None:
        return max(0, int(override))
    raw = os.environ.get(config.SYNC_INTERVAL_ENV)
    if raw is None or not str(raw).strip():
        return config.DEFAULT_SYNC_INTERVAL_SECONDS
    return max(0, int(raw))


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
            while not stop.wait(interval):
                try:
                    rt.sync()
                except SyncInProgress:
                    logger.info("Skipping scheduled sync; one is already running")
                except Exception:
                    logger.exception("Scheduled league sync failed")

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

    @app.get("/v1/status", response_model=StatusResponse)
    def status() -> StatusResponse:
        ctx = rt.get_context()
        identity = identity_coverage(
            ctx.bootstrap.get("elements") or [],
            (ctx.understat_league or {}).get("players") or [],
            ctx.player_match,
        )
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
            cache_dir=str(config.CACHE_DIR),
        )

    @app.post("/v1/sync", response_model=SyncResponse)
    def sync(
        x_sync_token: Annotated[str | None, Header()] = None,
    ) -> SyncResponse:
        expected = os.environ.get(config.SYNC_TOKEN_ENV, "")
        if not expected:
            raise HTTPException(status_code=503, detail="FPL_SYNC_TOKEN is not configured")
        if x_sync_token != expected:
            raise HTTPException(status_code=401, detail="Invalid sync token")
        try:
            payload = rt.sync()
        except SyncInProgress as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return SyncResponse(
            fpl=payload["fpl"],
            understat=payload["understat"],
            identity=payload["identity"],
            last_sync_at=rt.last_sync_at,
        )

    @app.get("/v1/entries/{entry_id}")
    def entry(entry_id: int):
        try:
            squad = load_manager_squad(rt.fpl_client(), entry_id)
        except FplApiError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return entry_summary(squad)

    @app.get("/v1/entries/{entry_id}/squad")
    def squad(
        entry_id: int,
        horizon: Annotated[int, Query(ge=1, le=15)] = config.DEFAULT_SQUAD_HORIZON,
    ):
        try:
            loaded = load_manager_squad(rt.fpl_client(), entry_id)
        except FplApiError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return squad_payload(loaded, rt.get_context(), horizon)

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
