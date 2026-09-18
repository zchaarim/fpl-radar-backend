from __future__ import annotations

from fpl_radar.features import shrink_defcon_p
from fpl_radar.fpl_rules import defcon_threshold
from fpl_radar.xp.model import ModelContext, expected_points
from tests.fixtures import bootstrap_sample
from fpl_radar.features import build_feature_set
from tests.test_features import _us_league


def test_thresholds() -> None:
    assert defcon_threshold(1) is None
    assert defcon_threshold(2) == 10
    assert defcon_threshold(3) == 12
    assert defcon_threshold(4) == 12


def test_one_lucky_game_is_shrunk() -> None:
    lucky = shrink_defcon_p(games=1, hits=1, own_lambda=14.0, pos_lambda=7.0, threshold=10)
    regular = shrink_defcon_p(games=20, hits=16, own_lambda=12.0, pos_lambda=7.0, threshold=10)
    assert lucky < 0.7
    assert regular > lucky
    assert regular > 0.6


def test_gk_gets_no_defcon_xp() -> None:
    boot = bootstrap_sample()
    for element in boot["elements"]:
        if element["id"] == 1:
            element["minutes"] = 360
            element["starts"] = 4
            element["defensive_contribution_per_90"] = 20
    features = build_feature_set(boot, _us_league())
    ctx = ModelContext(
        bootstrap=boot,
        fixtures=[{"event": 2, "team_h": 1, "team_a": 2}],
        features=features,
    )
    gk = expected_points(1, [2], ctx)
    assert gk.breakdown["events"]["2"]["defcon_xp"] == 0.0


def test_defender_defcon_from_live_hits() -> None:
    boot = bootstrap_sample()
    for element in boot["elements"]:
        if element["id"] == 3:
            element["minutes"] = 900
            element["starts"] = 10
            element["defensive_contribution_per_90"] = 11
        if int(element["element_type"]) == 2:
            element["minutes"] = max(element.get("minutes") or 0, 180)
            element["defensive_contribution_per_90"] = element.get("defensive_contribution_per_90") or 8
    live = {3: [(90, 12.0)] * 10}
    features = build_feature_set(boot, _us_league(), live_defcon=live)
    assert features.players[3].defcon_hits == 10
    assert features.players[3].defcon_p > 0.7
    ctx = ModelContext(
        bootstrap=boot,
        fixtures=[{"event": 2, "team_h": 1, "team_a": 2}],
        features=features,
    )
    xp = expected_points(3, [2], ctx)
    assert xp.breakdown["events"]["2"]["defcon_xp"] > 1.0
