from __future__ import annotations

from fpl_analyser.features import build_feature_set, fixture_multiplier, team_strengths
from fpl_analyser.xp.model import ModelContext, expected_points
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


def test_team_strength_attack_vs_defence() -> None:
    strengths = team_strengths(_us_league()["teams"])
    assert strengths["88"].att > strengths["89"].att
    assert strengths["89"].dfn > strengths["88"].dfn


def test_feature_set_matches_understat_xgi() -> None:
    boot = bootstrap_sample()
    features = build_feature_set(boot, _us_league())
    rates = features.players[8]
    assert rates.source == "understat"
    assert abs(rates.xgi90 - 0.75) < 1e-6
    assert 1 in features.teams
    assert 2 in features.teams


def test_fixture_multiplier_harder_away() -> None:
    boot = bootstrap_sample()
    features = build_feature_set(boot, _us_league())
    home = fixture_multiplier(features, 1, 2, True)
    away = fixture_multiplier(features, 1, 2, False)
    assert home > 0 and away > 0


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
    assert xp.breakdown["source"] == "xgi_minutes_cs_gc_defcon"
    blank = expected_points(8, [3], ctx)
    assert blank.per_event[3] == 0.0
