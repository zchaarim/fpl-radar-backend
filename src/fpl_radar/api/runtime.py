from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from fpl_radar.clients.fpl import FplClient
from fpl_radar.identity.match import identity_coverage
from fpl_radar.ingest.sync import default_cache, load_model_context, sync_fpl, sync_understat
from fpl_radar.xp.model import ModelContext


def _default_client() -> FplClient:
    return FplClient(cache=default_cache())


class Runtime:
    """Process-global model context. Rebuild after sync; do not rebuild per request."""

    def __init__(
        self,
        client_factory: Callable[[], FplClient] | None = None,
        context: ModelContext | None = None,
    ) -> None:
        self._lock = threading.Lock()
        self.client_factory = client_factory or _default_client
        self.context = context
        self.last_sync_at: float | None = None
        self.last_sync: dict[str, Any] | None = None

    def fpl_client(self) -> FplClient:
        return self.client_factory()

    def get_context(self) -> ModelContext:
        with self._lock:
            if self.context is None:
                self.context = load_model_context(self.client_factory())
            return self.context

    def sync(self) -> dict[str, Any]:
        client = self.client_factory()
        fpl_stats = sync_fpl(client)
        us_stats = sync_understat()
        ctx = load_model_context(client)
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
        with self._lock:
            self.context = ctx
            self.last_sync_at = time.time()
            self.last_sync = payload
        return payload
