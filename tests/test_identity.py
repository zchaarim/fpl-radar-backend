from __future__ import annotations

from fpl_radar.identity.match import (
    canonical_team,
    map_understat_players,
    match_players,
    match_teams,
    normalize_name,
)


def test_normalize_name() -> None:
    assert normalize_name("Manchester_United") == "manchester united"
    assert normalize_name("Sánchez") == "sanchez"
    assert normalize_name("Ødegaard") == "odegaard"
    assert normalize_name("O&#039;Shea") == "oshea"


def test_canonical_team_aliases() -> None:
    assert canonical_team("Man Utd") == canonical_team("Manchester United")
    assert canonical_team("Spurs") == canonical_team("Tottenham")
    assert canonical_team("Nott'm Forest") == canonical_team("Nottingham Forest")
    assert canonical_team("Man City") == canonical_team("Manchester City")
    assert canonical_team("Hull City") == canonical_team("Hull")
    assert canonical_team("Ipswich Town") == canonical_team("Ipswich")
    assert canonical_team("Coventry City") == canonical_team("Coventry")
    assert canonical_team("Newcastle") == canonical_team("Newcastle United")


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


def test_match_teams_fpl_short_labels() -> None:
    fpl = [
        {"id": 15, "name": "Man City", "short_name": "MCI"},
        {"id": 19, "name": "Spurs", "short_name": "TOT"},
    ]
    understat = {
        "88": {"id": "88", "title": "Manchester City"},
        "82": {"id": "82", "title": "Tottenham"},
    }
    mapped = match_teams(fpl, understat)
    assert mapped[15] == "88"
    assert mapped[19] == "82"


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


def test_match_players_official_vs_understat_names() -> None:
    fpl_teams = [{"id": 1, "name": "Arsenal"}, {"id": 14, "name": "Liverpool"}]
    fpl_players = [
        {
            "id": 1,
            "first_name": "David",
            "second_name": "Raya Martín",
            "web_name": "Raya",
            "team": 1,
        },
        {
            "id": 15,
            "first_name": "Martin",
            "second_name": "Ødegaard",
            "web_name": "Ødegaard",
            "team": 1,
        },
        {
            "id": 350,
            "first_name": "Alisson",
            "second_name": "Becker",
            "web_name": "A.Becker",
            "team": 14,
        },
    ]
    us_players = [
        {"id": "9676", "player_name": "David Raya", "team_title": "Arsenal"},
        {"id": "2517", "player_name": "Martin Odegaard", "team_title": "Arsenal"},
        {"id": "1257", "player_name": "Alisson", "team_title": "Liverpool"},
    ]
    mapped = match_players(fpl_players, us_players, {}, fpl_teams)
    assert mapped[1] == "9676"
    assert mapped[15] == "2517"
    assert mapped[350] == "1257"


def test_match_players_html_entity_and_alias_club() -> None:
    fpl_teams = [{"id": 12, "name": "Ipswich Town"}]
    fpl_players = [
        {
            "id": 304,
            "first_name": "Dara",
            "second_name": "O'Shea",
            "web_name": "O'Shea",
            "team": 12,
        }
    ]
    us_players = [{"id": "8756", "player_name": "Dara O&#039;Shea", "team_title": "Ipswich"}]
    assert match_players(fpl_players, us_players, {}, fpl_teams)[304] == "8756"


def test_match_iberian_double_surname_and_spelling() -> None:
    fpl_teams = [{"id": 8, "name": "Crystal Palace"}]
    fpl_players = [
        {
            "id": 211,
            "first_name": "Yéremy",
            "second_name": "Pino Santos",
            "web_name": "Yeremy",
            "team": 8,
        }
    ]
    us_players = [{"id": "9024", "player_name": "Yeremi Pino", "team_title": "Crystal Palace"}]
    assert match_players(fpl_players, us_players, {}, fpl_teams)[211] == "9024"


def test_map_understat_players_by_id_and_name() -> None:
    current = [
        {"id": "55", "player_name": "Bukayo Saka"},
        {"id": "99", "player_name": "New Signing"},
    ]
    previous = [
        {"id": "55", "player_name": "Bukayo Saka"},
        {"id": "12", "player_name": "New Signing"},
    ]
    mapped = map_understat_players(current, previous)
    assert mapped["55"] == "55"
    assert mapped["99"] == "12"

