from __future__ import annotations

import json
from typing import Any

from fpl_radar.clients.fpl import FplClient
from tests.fixtures import bootstrap_sample


class FakeResponse:
    def __init__(self, payload: Any, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload) if not isinstance(payload, str) else payload
        self.ok = status_code < 400

    def json(self) -> Any:
        if isinstance(self._payload, str):
            return json.loads(self._payload)
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


class FakeSession:
    def __init__(self, routes: dict[str, Any]) -> None:
        self.routes = routes
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []

    def get(self, url: str, params=None, headers=None, timeout=None):
        self.calls.append(url)
        payload = self.routes.get(url)
        path = url
        if payload is None and "/api/" in url:
            path = url.split("/api/", 1)[1]
            if params and params.get("event") is not None:
                path = f"{path}?event={params['event']}"
            payload = self.routes.get(path)
        elif payload is None:
            path = url
            payload = self.routes.get(path)
        if payload is None:
            return FakeResponse({"error": path}, status_code=404)
        if isinstance(payload, FakeResponse):
            return payload
        return FakeResponse(payload)


def public_routes() -> dict[str, Any]:
    boot = bootstrap_sample()
    picks = {"picks": [{"element": i, "position": i} for i in range(1, 16)]}
    return {
        "bootstrap-static/": boot,
        "fixtures/": [{"id": 1, "event": 1}],
        "event-status/": {"status": []},
        "team/set-piece-notes/": {"teams": []},
        "entry/99/": {"id": 99, "name": "Test FC", "last_deadline_bank": 12},
        "entry/99/history/": {"current": [{"event": 1, "bank": 12}]},
        "entry/99/transfers/": [
            {
                "event": 1,
                "element_in": 12,
                "element_out": 11,
                "element_in_cost": 50,
                "element_out_cost": 55,
                "time": "2026-08-10T12:00:00Z",
            }
        ],
        "entry/99/event/1/picks/": picks,
        "entry/99/event/2/picks/": picks,
    }


def client_from_routes(routes: dict[str, Any], cache=None) -> FplClient:
    session = FakeSession(routes)
    return FplClient(cache=cache, session=session, base_url="https://fantasy.premierleague.com/api/")
