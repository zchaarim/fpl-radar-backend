from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from fpl_radar import config
from fpl_radar.clients.fpl import FplClient
from fpl_radar.identity.match import identity_coverage
from fpl_radar.ingest.sync import default_cache, load_model_context, sync_fpl, sync_understat
from fpl_radar.xp.model import ModelContext, precompute_player_xp


class SyncInProgress(RuntimeError):
    """A league sync is already running in this process."""


class PlanInProgress(RuntimeError):
    """A transfer plan solve is already running in this process."""


def _default_client() -> FplClient:
    return FplClient(cache=default_cache())


class Runtime:
    """Process-global model context. Rebuild after sync or CONTEXT_TTL, not per request."""

    def __init__(
        self,
        client_factory: Callable[[], FplClient] | None = None,
        context: ModelContext | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self._cv = threading.Condition(self._lock)
        self.client_factory = client_factory or _default_client
        self.context = context
        self.context_built_at: float | None = time.time() if context is not None else None
        self.last_sync_at: float | None = None
        self.last_sync: dict[str, Any] | None = None
        self._syncing = False
        self._loading = False
        self._planning = False
        if context is not None and not context.xp_by_player:
            precompute_player_xp(context)

    def fpl_client(self) -> FplClient:
        return self.client_factory()

    def syncing(self) -> bool:
        with self._lock:
            return self._syncing

    def context_age_seconds(self) -> float | None:
        if self.context_built_at is None:
            return None
        return max(0.0, time.time() - self.context_built_at)

    def context_stale(self) -> bool:
        age = self.context_age_seconds()
        if age is None:
            return True
        return age >= config.CONTEXT_TTL_SECONDS

    def _install(self, ctx: ModelContext) -> None:
        self.context = ctx
        self.context_built_at = time.time()

    def _build_context(self, client: FplClient | None = None) -> ModelContext:
        ctx = load_model_context(client or self.client_factory())
        precompute_player_xp(ctx)
        return ctx

    def get_context(self) -> ModelContext:
        with self._cv:
            while True:
                if self.context is not None and (
                    self._syncing or self._loading or not self.context_stale()
                ):
                    return self.context
                if self._loading or self._syncing:
                    self._cv.wait(timeout=120.0)
                    continue
                self._loading = True
                break
        try:
            ctx = self._build_context()
            with self._cv:
                self._install(ctx)
                self._cv.notify_all()
                return self.context  # type: ignore[return-value]
        except Exception:
            with self._cv:
                self._cv.notify_all()
            raise
        finally:
            with self._cv:
                self._loading = False
                self._cv.notify_all()

    def sync(self) -> dict[str, Any]:
        with self._cv:
            if self._syncing:
                raise SyncInProgress("Sync already in progress")
            self._syncing = True
            self._cv.notify_all()
        try:
            client = self.client_factory()
            fpl_stats = sync_fpl(client)
            us_stats = sync_understat()
            ctx = self._build_context(client)
            coverage = identity_coverage(
                ctx.bootstrap.get("elements") or [],
                (ctx.understat_league or {}).get("players") or [],
                ctx.player_match,
            )
            payload = {
                "fpl": fpl_stats,
                "understat": us_stats,
                "identity": coverage,
            }
            with self._cv:
                self._install(ctx)
                self.last_sync_at = time.time()
                self.last_sync = payload
                self._cv.notify_all()
            return payload
        finally:
            with self._cv:
                self._syncing = False
                self._cv.notify_all()

    def begin_plan(self) -> None:
        with self._lock:
            if self._planning:
                raise PlanInProgress("Plan already in progress")
            self._planning = True

    def end_plan(self) -> None:
        with self._lock:
            self._planning = False
