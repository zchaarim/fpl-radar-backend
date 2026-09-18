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


def load_api_token(explicit: str | None = None) -> str | None:
    raw = (explicit or os.environ.get(config.API_TOKEN_ENV) or "").strip()
    if not raw:
        return None
    if raw.lower().startswith("bearer "):
        raw = raw[7:].strip()
    return raw or None


def cookie_header(raw: str) -> str:
    value = raw.strip()
    if value.lower().startswith("cookie:"):
        value = value.split(":", 1)[1].strip()
    return value


def cookie_looks_logged_in(raw: str) -> bool:
    lower = cookie_header(raw).lower()
    return "pl_profile=" in lower


def _entry_from_me(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    player = payload.get("player")
    if isinstance(player, dict):
        for key in ("entry", "default_entry", "entry_id"):
            if player.get(key) is not None:
                return int(player[key])
    for key in ("entry", "entry_id"):
        if payload.get(key) is not None:
            return int(payload[key])
    return None


def build_auth_client(
    api_token: str | None = None,
    session_cookie: str | None = None,
) -> FplAuthClient | None:
    """Prefer Bearer token. Ignore leftover guest cookies (no pl_profile)."""
    token = load_api_token(api_token)
    cookie = load_session_cookie(session_cookie)
    logged_in_cookie = cookie if cookie and cookie_looks_logged_in(cookie) else None
    if not token and not logged_in_cookie:
        return None
    return FplAuthClient(api_token=token, session_cookie=logged_in_cookie)


class FplAuthClient:
    """Authenticated FPL calls. Never writes responses to the public cache."""

    def __init__(
        self,
        api_token: str | None = None,
        session_cookie: str | None = None,
        session: requests.Session | None = None,
        base_url: str = config.FPL_BASE_URL,
        timeout: float = 30.0,
    ) -> None:
        if not api_token and not session_cookie:
            raise AuthError("Need FPL_API_TOKEN (Bearer) or a logged-in pl_profile cookie.")
        self.timeout = timeout
        self.base_url = base_url.rstrip("/") + "/"
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = config.DEFAULT_USER_AGENT
        self._cookie_raw = session_cookie or ""
        self._api_token = api_token
        if session_cookie:
            self.session.headers["Cookie"] = cookie_header(session_cookie)
        if api_token:
            self.session.headers["X-API-Authorization"] = f"Bearer {api_token}"

    def _get_json(self, path: str) -> Any:
        url = self.base_url + path.lstrip("/")
        response = self.session.get(url, timeout=self.timeout)
        if response.status_code in (401, 403):
            raise AuthError(
                f"FPL authentication failed for {path} ({response.status_code}). "
                "Copy x-api-authorization from a logged-in api/me/ request "
                "(FPL_API_TOKEN / --api-token). Tokens expire after a few hours."
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
        entry = _entry_from_me(payload)
        if entry is not None:
            return entry
        raise AuthError(
            "FPL /me/ did not include a manager id (player is usually null). "
            "Auth is the request header x-api-authorization: Bearer <jwt>, not the Cookie "
            "list (cf_clearance / pl_guest_id are guests). Copy that header from api/me/ "
            "in DevTools and set FPL_API_TOKEN."
        )

    def require_entry_match(self, entry_id: int) -> dict[str, Any]:
        me_payload = self.me()
        logged_in = self.authenticated_entry_id(me_payload)
        if logged_in != int(entry_id):
            raise AuthError(
                f"Session belongs to entry {logged_in}, not requested entry {entry_id}."
            )
        return me_payload
