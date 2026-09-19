from __future__ import annotations

from fpl_radar.features import (
    build_feature_set,
    build_team_strengths,
    fixture_multiplier,
    season_team_priors,
    shrink_mean,
    team_strengths,
)
from fpl_radar.xp.model import ModelContext, expected_points
from tests.fixtures import bootstrap_sample


def _us_league() -> dict:
    history_a = [
        {"h_a": "h", "xG": 2.0, "xGA": 0.8, "scored": 2, "missed": 1},
        {"h_a": "a", "xG": 1.6, "xGA": 1.0, "scored": 1, "missed": 1},
    ]
    history_b = [
        {"h_a": "h", "xG": 1.0, "xGA": 1.8, "scored": 1, "missed": 2},
        {"h_a": "a", "xG": 0.8, "xGA": 2.0, "scored": 0, "missed": 2},
    ]
    return {
        "teams": {
            "88": {"id": "88", "title": "Arsenal", "history": history_a},
            "89": {"id": "89", "title": "Chelsea", "history": history_b},
        },
        "players": [
            {
                "id": "55",
                "player_name": "MID1 MID1",
                "team_title": "Arsenal",
                "games": "4",
                "time": "360",
                "xG": "2.0",
                "xA": "1.0",
            }
        ],
        "dates": [],
    }


def test_shrink_mean_is_empirical_bayes() -> None:
    assert shrink_mean(2.0, 1.0, 0, 8) == 1.0
    half = shrink_mean(2.0, 1.0, 8, 8)
    assert abs(half - 1.5) < 1e-9
    later = shrink_mean(2.0, 1.0, 24, 8)
    assert later > half


def test_team_strength_attack_vs_defence() -> None:
    strengths = team_strengths(_us_league()["teams"])
    assert strengths["88"].att > strengths["89"].att
    assert strengths["89"].dfn > strengths["88"].dfn
    # 2 matches, k=8 → still close to 1.0, not the raw ~1.6 / 0.6 split.
    assert strengths["88"].att < 1.35
    assert strengths["89"].att > 0.65


def test_feature_set_matches_understat_xgi() -> None:
    boot = bootstrap_sample()
    features = build_feature_set(boot, _us_league())
    rates = features.players[8]
    assert "understat" in rates.source
    assert abs(rates.xg90_raw - 0.5) < 1e-6
    assert abs(rates.xa90_raw - 0.25) < 1e-6
    assert rates.xgi90 < rates.xg90_raw + rates.xa90_raw
    assert rates.xgi90 > 0.3
    assert 1 in features.teams
    assert 2 in features.teams


def test_fixture_multiplier_harder_away() -> None:
    boot = bootstrap_sample()
    features = build_feature_set(boot, _us_league())
    home = fixture_multiplier(features, 1, 2, True)
    away = fixture_multiplier(features, 1, 2, False)
    assert home > away
    assert features.league_ha_home > features.league_ha_away


def test_xgi_xp_uses_fixture_and_not_placeholder() -> None:
    boot = bootstrap_sample()
    features = build_feature_set(boot, _us_league())
    ctx = ModelContext(
        bootstrap=boot,
        fixtures=[{"event": 2, "team_h": 1, "team_a": 2}],
        understat_league=_us_league(),
        features=features,
    )
    xp = expected_points(8, [2], ctx)
    assert not xp.placeholder
    assert xp.horizon_sum > 0
    assert xp.breakdown["source"] == "xgi_minutes_cs_gc_defcon_bonus_saves_cards"
    blank = expected_points(8, [3], ctx)
    assert blank.per_event[3] == 0.0


def test_home_venue_starts_near_league() -> None:
    strengths = team_strengths(_us_league()["teams"])
    _, _, ha_home, ha_away = build_team_strengths(_us_league()["teams"])
    assert abs(strengths["88"].venue_home - ha_home) < 0.12
    assert abs(strengths["88"].venue_away - ha_away) < 0.12
    assert strengths["88"].venue_home > strengths["88"].venue_away


def test_last_season_team_prior_pulls_attack() -> None:
    current = _us_league()["teams"]
    prior_teams = {
        "88": {
            "id": "88",
            "title": "Arsenal",
            "history": [{"h_a": "h", "xG": 2.5, "xGA": 0.5, "scored": 2, "missed": 0}] * 12,
        },
        "89": {
            "id": "89",
            "title": "Chelsea",
            "history": [{"h_a": "a", "xG": 0.6, "xGA": 2.0, "scored": 0, "missed": 2}] * 12,
        },
    }
    base = team_strengths(current)
    with_prior, *_ = build_team_strengths(current, priors=season_team_priors(prior_teams))
    assert with_prior["88"].att > base["88"].att
    assert with_prior["89"].att < base["89"].att


def test_last_season_player_prior_pulls_xgi() -> None:
    boot = bootstrap_sample()
    prior = {
        "teams": _us_league()["teams"],
        "players": [
            {
                "id": "55",
                "player_name": "MID1 MID1",
                "team_title": "Arsenal",
                "games": "30",
                "time": "2700",
                "xG": "24.0",
                "xA": "9.0",
            }
        ],
    }
    plain = build_feature_set(boot, _us_league())
    with_prior = build_feature_set(boot, _us_league(), understat_prior=prior)
    assert with_prior.players[8].xg90 > plain.players[8].xg90
    assert "prior" in with_prior.players[8].source


def test_last_season_position_xgi_is_role_hyperprior() -> None:
    boot = bootstrap_sample()
    prior = {
        "teams": _us_league()["teams"],
        "players": [
            {
                "id": "77",
                "player_name": "MID2 MID2",
                "team_title": "Chelsea",
                "games": "30",
                "time": "2700",
                "xG": "24.0",
                "xA": "9.0",
            }
        ],
    }
    plain = build_feature_set(boot, _us_league())
    with_role = build_feature_set(boot, _us_league(), understat_prior=prior)
    assert with_role.players[8].xg90 > plain.players[8].xg90
    assert "prior" not in with_role.players[8].source
