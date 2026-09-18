from __future__ import annotations

import os
from typing import Any

import requests

from fpl_analyser import config


class AuthError(RuntimeError):
    pass


def load_session_cookie(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit.strip()
    env = os.environ.get(config.SESSION_COOKIE_ENV)
    if env:
        return env.strip()
    return None


def cookie_header(raw: str) -> str:
    value = raw.strip()
    if value.lower().startswith("cookie:"):
        value = value.split(":", 1)[1].strip()
    return value


class FplAuthClient:
    """Authenticated FPL calls. Never writes responses to the public cache."""

    def __init__(
        self,
        session_cookie: str,
        session: requests.Session | None = None,
        base_url: str = config.FPL_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        self.timeout = timeout
        self.base_url = base_url.rstrip("/") + "/"
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = config.DEFAULT_USER_AGENT
        self.session.headers["Cookie"] = cookie_header(session_cookie)

    def _get_json(self, path: str) -> Any:
        url = self.base_url + path.lstrip("/")
        response = self.session.get(url, timeout=self.timeout)
        if response.status_code in (401, 403):
            raise AuthError(
                f"FPL authentication failed for {path} ({response.status_code}). "
                "Check FPL_SESSION_COOKIE / --session-cookie."
            )
        if response.status_code >= 400:
            raise AuthError(f"GET {url} failed: {response.status_code} {response.text[:200]}")
        return response.json()

    def me(self) -> dict[str, Any]:
        return self._get_json("me/")

    def my_team(self, entry_id: int) -> dict[str, Any]:
        return self._get_json(f"my-team/{entry_id}/")

    def authenticated_entry_id(self, me_payload: dict[str, Any] | None = None) -> int:
        payload = me_payload if me_payload is not None else self.me()
        player = payload.get("player") if isinstance(payload, dict) else None
        if isinstance(player, dict) and player.get("entry") is not None:
            return int(player["entry"])
        if isinstance(payload, dict) and payload.get("entry") is not None:
            return int(payload["entry"])
        raise AuthError("Could not read manager entry id from /me/ response.")

    def require_entry_match(self, entry_id: int) -> dict[str, Any]:
        me_payload = self.me()
        logged_in = self.authenticated_entry_id(me_payload)
        if logged_in != int(entry_id):
            raise AuthError(
                f"Session belongs to entry {logged_in}, not requested entry {entry_id}."
            )
        return me_payload
