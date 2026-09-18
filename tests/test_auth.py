from __future__ import annotations

from fpl_analyser.clients.auth import AuthError, FplAuthClient, cookie_header
from tests.conftest import FakeResponse, FakeSession


def test_cookie_header_strips_prefix() -> None:
    assert cookie_header("Cookie: pl_profile=abc") == "pl_profile=abc"


def test_me_and_my_team() -> None:
    session = FakeSession(
        {
            "me/": {"player": {"entry": 99}},
            "my-team/99/": {
                "picks": [{"element": 1, "purchase_price": 45, "selling_price": 46}],
                "transfers": {"bank": 15},
            },
        }
    )
    auth = FplAuthClient("pl_profile=abc", session=session, base_url="https://fantasy.premierleague.com/api/")
    auth.require_entry_match(99)
    team = auth.my_team(99)
    assert team["transfers"]["bank"] == 15


def test_entry_mismatch() -> None:
    session = FakeSession({"me/": {"player": {"entry": 1}}})
    auth = FplAuthClient("pl_profile=abc", session=session, base_url="https://fantasy.premierleague.com/api/")
    try:
        auth.require_entry_match(99)
    except AuthError as exc:
        assert "1" in str(exc)
        return
    raise AssertionError("expected AuthError")


def test_auth_http_401() -> None:
    session = FakeSession({"me/": FakeResponse({}, status_code=401)})
    auth = FplAuthClient("bad", session=session, base_url="https://fantasy.premierleague.com/api/")
    try:
        auth.me()
    except AuthError:
        return
    raise AssertionError("expected AuthError")
