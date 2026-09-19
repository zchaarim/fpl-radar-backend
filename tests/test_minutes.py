from __future__ import annotations

from fpl_radar.features import (
    attach_minutes,
    availability_note,
    build_feature_set,
    fpl_player_rates,
    minutes_points,
    project_minutes,
)
from fpl_radar.fpl_rules import scoring_table
from tests.fixtures import bootstrap_sample
from tests.test_features import _us_league


def test_minutes_points_threshold_not_ramp() -> None:
    table = scoring_table()
    assert minutes_points(1.0, 0.0, table) == 1.0
    assert minutes_points(1.0, 1.0, table) == 2.0
    assert abs(minutes_points(0.5, 0.25, table) - 0.75) < 1e-9


def test_always_45_is_not_a_clean_sheet_profile() -> None:
    boot = bootstrap_sample()
    rates = {8: fpl_player_rates(boot["elements"][7])}
    live = {
        8: [{"minutes": 45}] * 4,
    }
    out = attach_minutes(rates, boot["elements"], live, finished_gws=4)
    mid = out[8]
    assert mid.exp_mins < 55
    assert mid.p60 < mid.p_played
    assert mid.p60 < 0.4
    proj = project_minutes(boot["elements"][7], mid)
    assert proj[1] < 0.4


def test_rotation_zeros_lower_expected_minutes() -> None:
    boot = bootstrap_sample()
    rates = {8: fpl_player_rates(boot["elements"][7])}
    nailed = attach_minutes(rates, boot["elements"], {8: [{"minutes": 90}] * 4}, 4)
    rotated = attach_minutes(
        rates,
        boot["elements"],
        {8: [{"minutes": 90}, {"minutes": 0}, {"minutes": 90}, {"minutes": 0}]},
        4,
    )
    assert rotated[8].exp_mins < nailed[8].exp_mins
    assert rotated[8].p60 < nailed[8].p60
    assert rotated[8].p_played < nailed[8].p_played


def test_nailed_gk_not_pulled_by_unused_keepers() -> None:
    boot = bootstrap_sample()
    rates = {
        1: fpl_player_rates(boot["elements"][0]),
        2: fpl_player_rates(boot["elements"][1]),
    }
    live = {
        1: [{"minutes": 90}] * 4,
        2: [{"minutes": 0}] * 4,
    }
    out = attach_minutes(rates, boot["elements"], live, finished_gws=4)
    assert out[1].mins_when_played > 85
    assert out[1].exp_mins > 75
    assert out[1].p_played > 0.8
    assert out[2].exp_mins < 20
    assert out[2].p_played < 0.25


def test_injured_does_not_zero_horizon_minutes() -> None:
    boot = bootstrap_sample()
    features = build_feature_set(boot, _us_league())
    player_row = dict(boot["elements"][7])
    player_row["status"] = "i"
    player_row["chance_of_playing_next_round"] = 0
    exp, p60, played = project_minutes(player_row, features.players[8])
    assert exp > 0 or features.players[8].minutes_source == "none"
    note = availability_note(player_row)
    assert "flag red" in note
    assert "0% next GW" in note
