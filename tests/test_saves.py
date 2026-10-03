from __future__ import annotations

from tests.fixtures import bootstrap_sample
from tests.test_features import _us_league

from fpl_radar.features import build_feature_set, expected_save_points, shrink_saves_e
from fpl_radar.xp.model import ModelContext, expected_points


def test_mean_saves_are_not_divided_by_three() -> None:
    naive = 2.0 / 3.0
    poisson = expected_save_points(2.0, per=3)
    assert poisson < naive
    assert poisson > 0.2
    assert expected_save_points(4.0, per=3) > expected_save_points(2.0, per=3)


def test_one_six_save_game_is_shrunk() -> None:
    lucky = shrink_saves_e(1, 2.0, 6.0, 3.0)
    regular = shrink_saves_e(20, 1.1, 4.2, 3.0)
    assert lucky < 1.3
    assert regular > lucky


def test_outfield_gets_no_save_xp() -> None:
    boot = bootstrap_sample()
    features = build_feature_set(boot, _us_league())
    ctx = ModelContext(
        bootstrap=boot,
        fixtures=[{"event": 2, "team_h": 1, "team_a": 2}],
        features=features,
    )
    mid = expected_points(8, [2], ctx)
    assert mid.breakdown["events"]["2"]["saves_xp"] == 0.0
    assert features.players[8].saves_source == "outfield"


def test_keeper_live_saves_feed_xp() -> None:
    boot = bootstrap_sample()
    for element in boot["elements"]:
        if element["id"] == 1:
            element["minutes"] = 900
            element["starts"] = 10
            element["saves"] = 40
        if int(element["element_type"]) == 1:
            element["minutes"] = max(element.get("minutes") or 0, 180)
            element["starts"] = max(element.get("starts") or 0, 2)
            element["saves"] = element.get("saves") or 6
    live = {
        1: [{"minutes": 90, "saves": 4, "bps": 20, "bonus": 0, "defensive_contribution": 0}] * 10
    }
    features = build_feature_set(boot, _us_league(), live_matches=live)
    assert features.players[1].saves_games == 10
    assert features.players[1].saves_hits == 10
    assert features.players[1].saves_e > 0.6
    ctx = ModelContext(
        bootstrap=boot,
        fixtures=[{"event": 2, "team_h": 1, "team_a": 2}],
        features=features,
    )
    xp = expected_points(1, [2], ctx)
    assert xp.breakdown["events"]["2"]["saves_xp"] > 0.5
