from __future__ import annotations

from fpl_radar.features import (
    expected_goals_conceded_points,
    p_play_sixty,
    poisson_clean_sheet,
)
from fpl_radar.xp.model import ModelContext, expected_points
from tests.fixtures import bootstrap_sample
from tests.test_features import _us_league
from fpl_radar.features import build_feature_set


def test_poisson_cs_and_gc() -> None:
    assert abs(poisson_clean_sheet(0.0) - 1.0) < 1e-9
    assert poisson_clean_sheet(1.0) < poisson_clean_sheet(0.4)
    # E[floor(K/2)] for lambda=0 is 0
    assert expected_goals_conceded_points(0.0) == 0.0
    assert expected_goals_conceded_points(2.0) < expected_goals_conceded_points(0.5)


def test_p60_ramp() -> None:
    assert p_play_sixty(0) == 0
    assert p_play_sixty(90) == 1
    assert 0 < p_play_sixty(50) < 1


def test_defender_cs_better_than_leaky_away_gk() -> None:
    boot = bootstrap_sample()
    for element in boot["elements"]:
        if element["id"] in {1, 2, 3, 4}:
            element["minutes"] = 360
            element["starts"] = 4
    features = build_feature_set(boot, _us_league())
    ctx = ModelContext(
        bootstrap=boot,
        fixtures=[{"event": 2, "team_h": 1, "team_a": 2}],
        features=features,
    )
    arsenal_gk = expected_points(1, [2], ctx)
    chelsea_gk = expected_points(2, [2], ctx)
    assert arsenal_gk.breakdown["events"]["2"]["cs_xp"] > chelsea_gk.breakdown["events"]["2"]["cs_xp"]
    assert chelsea_gk.breakdown["events"]["2"]["gc_xp"] < arsenal_gk.breakdown["events"]["2"]["gc_xp"]


def test_mid_cs_is_one_not_four() -> None:
    boot = bootstrap_sample()
    for element in boot["elements"]:
        if element["id"] in {1, 8}:
            element["minutes"] = 360
            element["starts"] = 4
    features = build_feature_set(boot, _us_league())
    ctx = ModelContext(
        bootstrap=boot,
        fixtures=[{"event": 2, "team_h": 1, "team_a": 2}],
        features=features,
    )
    mid = expected_points(8, [2], ctx)
    gk = expected_points(1, [2], ctx)
    assert mid.breakdown["events"]["2"]["cs_xp"] < gk.breakdown["events"]["2"]["cs_xp"]
    assert mid.breakdown["events"]["2"]["gc_xp"] == 0.0
