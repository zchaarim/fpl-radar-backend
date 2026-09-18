from __future__ import annotations

from fpl_analyser.clients.understat import UnderstatClient, decode_understat_embedded, extract_embedded_var
from tests.conftest import FakeResponse, FakeSession


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
