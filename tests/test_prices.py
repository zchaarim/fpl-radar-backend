from __future__ import annotations

from fpl_radar.fpl_rules import estimated_selling_price, start_price


def test_sell_price_rise_floored() -> None:
    # bought 10.0, now 10.7 → keep 0.3 → sell 10.3
    assert estimated_selling_price(100, 107, 0.5) == 103


def test_sell_price_small_rise_no_profit_share() -> None:
    assert estimated_selling_price(100, 101, 0.5) == 100


def test_sell_price_fall() -> None:
    assert estimated_selling_price(100, 95, 0.5) == 95


def test_start_price() -> None:
    assert start_price({"now_cost": 80, "cost_change_start": 5}) == 75
