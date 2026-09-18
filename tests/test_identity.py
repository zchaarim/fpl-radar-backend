from __future__ import annotations

from fpl_radar.identity.match import match_players, match_teams, normalize_name


def test_normalize_name() -> None:
    assert normalize_name("Manchester_United") == "manchester united"
    assert normalize_name("Sánchez") == "sanchez"


def test_match_teams_and_overrides() -> None:
    fpl = [{"id": 1, "name": "Arsenal", "short_name": "ARS"}, {"id": 4, "name": "Manchester United"}]
    understat = {
        "88": {"id": "88", "title": "Arsenal"},
        "89": {"id": "89", "title": "Manchester United"},
    }
    mapped = match_teams(fpl, understat)
    assert mapped[1] == "88"
    assert mapped[4] == "89"
    overridden = match_teams(fpl, understat, {"teams": {"1": "custom"}})
    assert overridden[1] == "custom"


def test_match_players_by_name_and_club() -> None:
    fpl_teams = [{"id": 1, "name": "Arsenal"}]
    fpl_players = [
        {
            "id": 10,
            "first_name": "Bukayo",
            "second_name": "Saka",
            "web_name": "Saka",
            "team": 1,
        }
    ]
    us_players = [{"id": "55", "player_name": "Bukayo Saka", "team_title": "Arsenal"}]
    team_map = {1: "88"}
    assert match_players(fpl_players, us_players, team_map, fpl_teams)[10] == "55"
