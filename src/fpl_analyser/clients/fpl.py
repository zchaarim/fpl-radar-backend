from __future__ import annotations

import logging
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from fpl_analyser import config
from fpl_analyser.ingest.store import JsonCache

logger = logging.getLogger(__name__)


class FplApiError(RuntimeError):
    pass


class FplClient:
    """Public Fantasy Premier League API client with optional file cache."""

    def __init__(
        self,
        cache: JsonCache | None = None,
        session: requests.Session | None = None,
        base_url: str = config.FPL_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.cache = cache
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", config.DEFAULT_USER_AGENT)
        if session is None:
            retry = Retry(total=3, backoff_factor=0.3, status_forcelist=(429, 500, 502, 503, 504))
            self.session.mount("https://", HTTPAdapter(max_retries=retry))
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    def _get_json(self, path: str, ttl: int | None, params: dict[str, Any] | None = None) -> Any:
        key = path if not params else f"{path}?{sorted(params.items())}"
        if self.cache and ttl:
            cached = self.cache.get(key, ttl_seconds=ttl)
            if cached is not None:
                return cached
        url = self.base_url + path.lstrip("/")
        response = self.session.get(url, params=params, timeout=self.timeout)
        if response.status_code >= 400:
            raise FplApiError(f"GET {url} failed: {response.status_code} {response.text[:200]}")
        data = response.json()
        if self.cache and ttl:
            self.cache.set(key, data)
        return data

    def bootstrap_static(self) -> dict[str, Any]:
        return self._get_json("bootstrap-static/", config.BOOTSTRAP_TTL_SECONDS)

    def fixtures(self, event: int | None = None) -> list[dict[str, Any]]:
        params = {"event": event} if event is not None else None
        return self._get_json("fixtures/", config.FIXTURES_TTL_SECONDS, params=params)

    def element_summary(self, element_id: int) -> dict[str, Any]:
        return self._get_json(
            f"element-summary/{element_id}/",
            config.ELEMENT_SUMMARY_TTL_SECONDS,
        )

    def event_live(self, event_id: int) -> dict[str, Any]:
        return self._get_json(f"event/{event_id}/live/", config.FIXTURES_TTL_SECONDS)

    def event_status(self) -> dict[str, Any]:
        return self._get_json("event-status/", config.FIXTURES_TTL_SECONDS)

    def entry(self, entry_id: int) -> dict[str, Any]:
        return self._get_json(f"entry/{entry_id}/", config.ENTRY_TTL_SECONDS)

    def entry_history(self, entry_id: int) -> dict[str, Any]:
        return self._get_json(f"entry/{entry_id}/history/", config.ENTRY_TTL_SECONDS)

    def entry_transfers(self, entry_id: int) -> list[dict[str, Any]]:
        return self._get_json(f"entry/{entry_id}/transfers/", config.ENTRY_TTL_SECONDS)

    def entry_picks(self, entry_id: int, event_id: int) -> dict[str, Any]:
        return self._get_json(
            f"entry/{entry_id}/event/{event_id}/picks/",
            config.ENTRY_TTL_SECONDS,
        )

    def set_piece_notes(self) -> dict[str, Any]:
        return self._get_json("team/set-piece-notes/", config.BOOTSTRAP_TTL_SECONDS)

    def players_by_id(self, bootstrap: dict[str, Any] | None = None) -> dict[int, dict[str, Any]]:
        data = bootstrap or self.bootstrap_static()
        return {int(p["id"]): p for p in data.get("elements", [])}

    def teams_by_id(self, bootstrap: dict[str, Any] | None = None) -> dict[int, dict[str, Any]]:
        data = bootstrap or self.bootstrap_static()
        return {int(t["id"]): t for t in data.get("teams", [])}

    def finished_event_ids(self, bootstrap: dict[str, Any] | None = None) -> list[int]:
        data = bootstrap or self.bootstrap_static()
        return [int(event["id"]) for event in data.get("events") or [] if event.get("finished")]

    def live_match_log(
        self,
        bootstrap: dict[str, Any] | None = None,
    ) -> dict[int, list[dict[str, float]]]:
        """Per player per finished GW: minutes, defcon, bps, bonus, saves, cards."""
        data = bootstrap or self.bootstrap_static()
        by_player: dict[int, list[dict[str, float]]] = {}
        for event_id in self.finished_event_ids(data):
            live = self.event_live(event_id)
            for element in live.get("elements") or []:
                stats = element.get("stats") or {}
                minutes = float(stats.get("minutes") or 0)
                if minutes <= 0:
                    continue
                pid = int(element["id"])
                by_player.setdefault(pid, []).append(
                    {
                        "minutes": minutes,
                        "defensive_contribution": float(stats.get("defensive_contribution") or 0),
                        "bps": float(stats.get("bps") or 0),
                        "bonus": float(stats.get("bonus") or 0),
                        "saves": float(stats.get("saves") or 0),
                        "yellow_cards": float(stats.get("yellow_cards") or 0),
                        "red_cards": float(stats.get("red_cards") or 0),
                    }
                )
        return by_player

    def live_defcon_log(
        self,
        bootstrap: dict[str, Any] | None = None,
    ) -> dict[int, list[tuple[int, float]]]:
        log = self.live_match_log(bootstrap)
        return {
            pid: [(int(row["minutes"]), row["defensive_contribution"]) for row in rows]
            for pid, rows in log.items()
        }
