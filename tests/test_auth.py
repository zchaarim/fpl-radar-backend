from __future__ import annotations

from tests.conftest import FakeResponse, FakeSession

from fpl_radar.clients.auth import (
    AuthError,
    FplAuthClient,
    build_auth_client,
    cookie_header,
    load_api_token,
)


def test_cookie_header_strips_prefix() -> None:
    assert cookie_header("Cookie: pl_profile=abc") == "pl_profile=abc"


def test_load_api_token_strips_bearer() -> None:
    assert load_api_token("Bearer abc.def") == "abc.def"


def test_guest_cookie_does_not_build_client() -> None:
    assert build_auth_client(session_cookie="pl_guest_id=abc; cf_clearance=xyz") is None


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
    auth = FplAuthClient(
        api_token="abc.def",
        session=session,
        base_url="https://fantasy.premierleague.com/api/",
    )
    auth.require_entry_match(99)
    team = auth.my_team(99)
    assert team["transfers"]["bank"] == 15
    assert session.headers.get("X-API-Authorization") == "Bearer abc.def"


def test_entry_mismatch() -> None:
    session = FakeSession({"me/": {"player": {"entry": 1}}})
    auth = FplAuthClient(
        api_token="tok",
        session=session,
        base_url="https://fantasy.premierleague.com/api/",
    )
    try:
        auth.require_entry_match(99)
    except AuthError as exc:
        assert "1" in str(exc)
        return
    raise AssertionError("expected AuthError")


def test_guest_me_payload() -> None:
    session = FakeSession({"me/": {"player": None}})
    auth = FplAuthClient(
        api_token="tok",
        session=session,
        base_url="https://fantasy.premierleague.com/api/",
    )
    try:
        auth.require_entry_match(99)
    except AuthError as exc:
        assert "x-api-authorization" in str(exc)
        return
    raise AssertionError("expected AuthError")


def test_auth_http_401() -> None:
    session = FakeSession({"me/": FakeResponse({}, status_code=401)})
    auth = FplAuthClient(
        api_token="bad",
        session=session,
        base_url="https://fantasy.premierleague.com/api/",
    )
    try:
        auth.me()
    except AuthError:
        return
    raise AssertionError("expected AuthError")
