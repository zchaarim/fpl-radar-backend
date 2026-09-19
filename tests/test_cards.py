from __future__ import annotations

from fpl_radar.features import (
    build_feature_set,
    p_card_in_minutes,
    shrink_card_p,
)
from fpl_radar.fpl_rules import RED_PRIOR_GAMES, YELLOW_PRIOR_GAMES
from fpl_radar.xp.model import ModelContext, expected_points
from tests.fixtures import bootstrap_sample
from tests.test_features import _us_league


def test_one_yellow_is_not_every_week() -> None:
    _lam, p90 = shrink_card_p(1.0, 1, 1, 1.0, 0.14, YELLOW_PRIOR_GAMES)
    assert p90 < 0.45


def test_one_red_is_shrunk_harder() -> None:
    _y, yellow_p = shrink_card_p(2.0, 2, 2, 1.0, 0.14, YELLOW_PRIOR_GAMES)
    _r, red_p = shrink_card_p(2.0, 2, 1, 0.5, 0.02, RED_PRIOR_GAMES)
    assert red_p < yellow_p
    assert red_p < 0.2


def test_partial_minutes_scale_probability() -> None:
    assert p_card_in_minutes(0.2, 45) < p_card_in_minutes(0.2, 90)
    assert p_card_in_minutes(0.2, 0) == 0.0


def test_regular_yellows_feed_negative_xp() -> None:
    boot = bootstrap_sample()
    for element in boot["elements"]:
        if element["id"] == 8:
            element["minutes"] = 900
            element["starts"] = 10
            element["yellow_cards"] = 4
        if int(element["element_type"]) == 3:
            element["minutes"] = max(element.get("minutes") or 0, 180)
            element["yellow_cards"] = element.get("yellow_cards") or 1
    live = {
        8: [
            {
                "minutes": 90,
                "yellow_cards": 1 if i < 4 else 0,
                "red_cards": 0,
                "saves": 0,
                "bps": 15,
                "bonus": 0,
                "defensive_contribution": 0,
            }
            for i in range(10)
        ]
    }
    features = build_feature_set(boot, _us_league(), live_matches=live)
    assert 0.15 < features.players[8].yellow_p < 0.55
    assert features.players[8].red_p < 0.08
    ctx = ModelContext(
        bootstrap=boot,
        fixtures=[{"event": 2, "team_h": 1, "team_a": 2}],
        features=features,
    )
    xp = expected_points(8, [2], ctx)
    cards = xp.breakdown["events"]["2"]["cards_xp"]
    assert cards < 0
    assert cards > -0.7


def test_last_season_cards_set_role_prior() -> None:
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
                "xG": "1.0",
                "xA": "1.0",
                "yellow_cards": "12",
                "red_cards": "1",
            }
        ],
    }
    plain = build_feature_set(boot, _us_league())
    with_prior = build_feature_set(boot, _us_league(), understat_prior=prior)
    assert with_prior.players[8].yellow90 > plain.players[8].yellow90
    assert abs(with_prior.players[8].yellow90 - 0.4) < 0.05
