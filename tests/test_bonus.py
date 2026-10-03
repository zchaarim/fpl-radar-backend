from __future__ import annotations

from tests.fixtures import bootstrap_sample
from tests.test_features import _us_league

from fpl_radar.features import (
    build_feature_set,
    expected_bonus_from_bps,
    heuristic_bonus_from_bps,
    shrink_bonus_e,
)
from fpl_radar.xp.model import ModelContext, expected_points


def test_higher_bps_maps_to_more_bonus() -> None:
    assert heuristic_bonus_from_bps(32) > heuristic_bonus_from_bps(18)
    curve = {k: heuristic_bonus_from_bps(float(k)) + 0.1 for k in range(12, 36)}
    assert expected_bonus_from_bps(28, curve) > expected_bonus_from_bps(18, curve)


def test_one_bonus_haul_is_shrunk() -> None:
    lucky = shrink_bonus_e(1, 3.0, 40.0, 18.0, {})
    regular = shrink_bonus_e(20, 1.2, 28.0, 18.0, {})
    assert lucky < 2.0
    assert regular > lucky * 0.4


def test_live_bonus_feeds_xp() -> None:
    boot = bootstrap_sample()
    for element in boot["elements"]:
        if element["id"] == 8:
            element["minutes"] = 900
            element["starts"] = 10
            element["bps"] = 280
            element["bonus"] = 12
        if int(element["element_type"]) == 3:
            element["minutes"] = max(element.get("minutes") or 0, 180)
            element["starts"] = max(element.get("starts") or 0, 2)
            element["bps"] = element.get("bps") or 36
    live = {
        8: [{"minutes": 90, "bps": 30, "bonus": 2, "defensive_contribution": 0}] * 10
    }
    features = build_feature_set(boot, _us_league(), live_matches=live)
    assert features.players[8].bonus_games == 10
    assert features.players[8].bonus_e > 0.5
    ctx = ModelContext(
        bootstrap=boot,
        fixtures=[{"event": 2, "team_h": 1, "team_a": 2}],
        features=features,
    )
    xp = expected_points(8, [2], ctx)
    assert xp.breakdown["events"]["2"]["bonus_xp"] > 0.4
