from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from fpl_radar import config
from fpl_radar.ingest.store import JsonCache

logger = logging.getLogger(__name__)

# One outage should not repeat full connect timeouts for every caller in this process.
_FETCH_COOLDOWN_SECONDS = 15 * 60
_fetch_failed_until: dict[str, tuple[float, BaseException]] = {}


class UnderstatError(RuntimeError):
    pass


def decode_understat_embedded(raw: str) -> Any:
    decoded = raw.encode("utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
    return json.loads(decoded)


def extract_embedded_var(html: str, var_name: str) -> Any:
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script"):
        text = script.string or ""
        if var_name not in text:
            continue
        match = re.search(rf"{re.escape(var_name)}\s*=\s*JSON\.parse\('(.+?)'\)", text, re.S)
        if match:
            return decode_understat_embedded(match.group(1))
        if "('" in text and "')" in text:
            start = text.index("('") + 2
            end = text.index("')", start)
            return decode_understat_embedded(text[start:end])
    raise UnderstatError(f"{var_name} not found in Understat HTML")


class UnderstatClient:
    def __init__(
        self,
        cache: JsonCache | None = None,
        session: requests.Session | None = None,
        timeout: float = 30.0,
        delay_seconds: float = 0.5,
    ) -> None:
        self.cache = cache
        self.timeout = timeout
        self.delay_seconds = delay_seconds
        self.used_stale = False
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", config.DEFAULT_USER_AGENT)
        if session is None:
            retry = Retry(
                total=2,
                connect=2,
                read=2,
                backoff_factor=0.5,
                status_forcelist=(429, 500, 502, 503, 504),
                allowed_methods=frozenset({"GET", "HEAD"}),
            )
            self.session.mount("https://", HTTPAdapter(max_retries=retry))

    def _request_timeout(self) -> tuple[float, float]:
        total = float(self.timeout)
        return (min(10.0, total), total)

    def _sleep(self) -> None:
        if self.delay_seconds:
            time.sleep(self.delay_seconds)

    def _stale_or_raise(self, key: str, exc: BaseException) -> dict[str, Any]:
        stale = self.cache.get(key, ttl_seconds=None) if self.cache else None
        if stale is None:
            raise exc
        self.used_stale = True
        logger.warning("Understat fetch failed for %s (%s); using stale cache", key, exc)
        return stale

    def _download_league(self, league: str, season: int) -> dict[str, Any]:
        league_url = f"{config.UNDERSTAT_BASE_URL}league/{league}/{season}"
        timeout = self._request_timeout()
        warmup = self.session.get(league_url, timeout=timeout)
        warmup.raise_for_status()
        self._sleep()

        ajax_url = f"{config.UNDERSTAT_BASE_URL}getLeagueData/{league}/{season}"
        headers = {"X-Requested-With": "XMLHttpRequest", "Referer": league_url}
        response = self.session.get(ajax_url, headers=headers, timeout=timeout)
        data: dict[str, Any] | None = None
        if response.ok:
            try:
                parsed = response.json()
                if isinstance(parsed, dict) and (
                    "teams" in parsed or "players" in parsed or "dates" in parsed
                ):
                    data = parsed
            except ValueError:
                logger.info("Understat AJAX was not JSON; falling back to HTML embed")

        if data is None:
            data = {
                "teams": extract_embedded_var(warmup.text, "teamsData"),
                "players": extract_embedded_var(warmup.text, "playersData"),
                "dates": extract_embedded_var(warmup.text, "datesData"),
            }
        return data

    def get_league_data(
        self,
        league: str = config.UNDERSTAT_LEAGUE,
        season: int = config.UNDERSTAT_SEASON,
        ttl_seconds: int | None = None,
    ) -> dict[str, Any]:
        key = f"understat_league_{league}_{season}"
        ttl = config.UNDERSTAT_TTL_SECONDS if ttl_seconds is None else ttl_seconds
        if self.cache:
            cached = self.cache.get(key, ttl_seconds=ttl)
            if cached is not None:
                return cached

        blocked = _fetch_failed_until.get(key)
        if blocked is not None and time.monotonic() < blocked[0]:
            return self._stale_or_raise(key, blocked[1])

        try:
            data = self._download_league(league, season)
        except requests.RequestException as exc:
            _fetch_failed_until[key] = (time.monotonic() + _FETCH_COOLDOWN_SECONDS, exc)
            return self._stale_or_raise(key, exc)

        _fetch_failed_until.pop(key, None)
        if self.cache:
            self.cache.set(key, data)
        return data
