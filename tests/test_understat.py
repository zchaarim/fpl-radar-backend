from __future__ import annotations

import pytest
import requests
from tests.conftest import FakeResponse, FakeSession

from fpl_radar.clients import understat as understat_mod
from fpl_radar.clients.understat import (
    UnderstatClient,
    decode_understat_embedded,
    extract_embedded_var,
)
from fpl_radar.ingest.store import JsonCache
from fpl_radar.ingest.sync import sync_understat


@pytest.fixture(autouse=True)
def _clear_understat_backoff() -> None:
    understat_mod._fetch_failed_until.clear()
    yield
    understat_mod._fetch_failed_until.clear()


def test_decode_hex_json() -> None:
    raw = r"\x7B\x22id\x22\x3A\x221\x22\x7D"
    assert decode_understat_embedded(raw) == {"id": "1"}


def test_extract_embedded_var() -> None:
    html = "<script>var playersData = JSON.parse('\\x5B\\x7B\\x22id\\x22\\x3A\\x229\\x22\\x7D\\x5D')</script>"
    assert extract_embedded_var(html, "playersData")[0]["id"] == "9"


def test_ajax_league_data() -> None:
    payload = {"teams": {"1": {"id": "1", "title": "Arsenal"}}, "players": [{"id": "9"}], "dates": []}
    session = FakeSession(
        {
            "https://understat.com/league/EPL/2026": FakeResponse("<html></html>"),
            "https://understat.com/getLeagueData/EPL/2026": payload,
        }
    )
    client = UnderstatClient(session=session, delay_seconds=0)
    data = client.get_league_data("EPL", 2026)
    assert data["players"][0]["id"] == "9"
    assert client.used_stale is False


def test_stale_cache_when_fetch_fails(tmp_path, monkeypatch) -> None:
    cache = JsonCache(tmp_path)
    cache.set(
        "understat_league_EPL_2026",
        {"teams": {}, "players": [{"id": "9"}], "dates": []},
    )
    monkeypatch.setattr("fpl_radar.ingest.store.time.time", lambda: 10**12)
    calls = {"n": 0}
    session = FakeSession({})

    def get(url, headers=None, timeout=None):
        calls["n"] += 1
        raise requests.ConnectionError("temporary failure in name resolution")

    session.get = get
    client = UnderstatClient(cache=cache, session=session, delay_seconds=0)
    data = client.get_league_data("EPL", 2026, ttl_seconds=1)
    again = client.get_league_data("EPL", 2026, ttl_seconds=1)
    assert data["players"][0]["id"] == "9"
    assert again["players"][0]["id"] == "9"
    assert calls["n"] == 1
    assert client.used_stale is True


def test_fetch_failure_without_cache_raises() -> None:
    session = FakeSession({})

    def get(url, headers=None, timeout=None):
        raise requests.ConnectionError("timed out")

    session.get = get
    client = UnderstatClient(session=session, delay_seconds=0)
    with pytest.raises(requests.ConnectionError):
        client.get_league_data("EPL", 2099)
    with pytest.raises(requests.ConnectionError):
        client.get_league_data("EPL", 2099)


def test_sync_understat_reports_stale_client() -> None:
    class Client:
        used_stale = True

        def get_league_data(self, league="EPL", season=2026, ttl_seconds=None):
            return {"teams": {"1": {}}, "players": [{}, {}], "dates": [1]}

    stats = sync_understat(client=Client())
    assert stats["stale"] is True
    assert stats["players"] == 2
