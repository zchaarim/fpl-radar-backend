from __future__ import annotations

from typing import Any

# Fallback FPL scoring when bootstrap game_settings omit a value.
# DefCon and 2025/26+ extras are not always in game_settings.
SCORING_DEFAULTS: dict[str, int | float] = {
    "minutes_0_59": 1,
    "minutes_60_plus": 2,
    "goal_gk": 10,
    "goal_def": 6,
    "goal_mid": 5,
    "goal_fwd": 4,
    "assist": 3,
    "clean_sheet_gk": 4,
    "clean_sheet_def": 4,
    "clean_sheet_mid": 1,
    "clean_sheet_fwd": 0,
    "goals_conceded_per": 2,
    "goals_conceded_points": -1,
    "save_per": 3,
    "save_points": 1,
    "penalty_save": 5,
    "penalty_miss": -2,
    "yellow_card": -1,
    "red_card": -3,
    "own_goal": -2,
    "bonus_max": 3,
    "defcon_def_threshold": 10,
    "defcon_mid_fwd_threshold": 12,
    "defcon_points": 2,
}

ELEMENT_TYPE_GKP = 1
ELEMENT_TYPE_DEF = 2
ELEMENT_TYPE_MID = 3
ELEMENT_TYPE_FWD = 4

MAX_PLAYERS_PER_CLUB = 3
SQUAD_SIZE = 15
STARTING_XI = 11
DEFCON_PRIOR_GAMES = 6
BONUS_PRIOR_GAMES = 6
SAVES_PRIOR_GAMES = 6
YELLOW_PRIOR_GAMES = 6
RED_PRIOR_GAMES = 18
MIN_BONUS_CURVE_BUCKETS = 8
# Empirical-Bayes prior strength (equivalent sample size). After n = k, posterior is 50/50.
XGI_PRIOR_90S = 8
POSITION_XGI_PRIOR_90S = 8
TEAM_STRENGTH_PRIOR_GAMES = 8
FINISHING_PRIOR_GAMES = 12
HOME_SPLIT_PRIOR_GAMES = 10
MIN_PRIOR_MINUTES = 180
XGI90_DEFAULT = {
    ELEMENT_TYPE_GKP: (0.01, 0.005),
    ELEMENT_TYPE_DEF: (0.07, 0.06),
    ELEMENT_TYPE_MID: (0.22, 0.18),
    ELEMENT_TYPE_FWD: (0.38, 0.18),
}
YELLOW90_DEFAULT = {
    ELEMENT_TYPE_GKP: 0.04,
    ELEMENT_TYPE_DEF: 0.18,
    ELEMENT_TYPE_MID: 0.14,
    ELEMENT_TYPE_FWD: 0.10,
}
RED90_DEFAULT = {
    ELEMENT_TYPE_GKP: 0.008,
    ELEMENT_TYPE_DEF: 0.025,
    ELEMENT_TYPE_MID: 0.020,
    ELEMENT_TYPE_FWD: 0.018,
}


def defcon_threshold(element_type: int) -> int | None:
    if element_type == ELEMENT_TYPE_DEF:
        return int(SCORING_DEFAULTS["defcon_def_threshold"])
    if element_type in {ELEMENT_TYPE_MID, ELEMENT_TYPE_FWD}:
        return int(SCORING_DEFAULTS["defcon_mid_fwd_threshold"])
    return None


def sell_on_fee(game_settings: dict[str, Any] | None) -> float:
    if not game_settings:
        return 0.5
    fee = game_settings.get("transfers_sell_on_fee")
    if fee is None:
        return 0.5
    return float(fee)


def estimated_selling_price(
    purchase_price: int,
    now_cost: int,
    fee: float = 0.5,
) -> int:
    """FPL sell price in tenths of a million.

    Profit is shared at ``fee`` (usually 0.5) rounded down to the nearest 0.1m.
    Price falls are applied in full.
    """
    profit = now_cost - purchase_price
    if profit <= 0:
        return now_cost
    return purchase_price + int(profit * fee)


def start_price(player: dict[str, Any]) -> int:
    return int(player["now_cost"]) - int(player.get("cost_change_start") or 0)


def scoring_table(game_settings: dict[str, Any] | None = None) -> dict[str, int | float]:
    table = dict(SCORING_DEFAULTS)
    if not game_settings:
        return table
    mapping = {
        "scoring_goal_gk": "goal_gk",
        "scoring_goal_def": "goal_def",
        "scoring_goal_mid": "goal_mid",
        "scoring_goal_fwd": "goal_fwd",
        "scoring_assist": "assist",
    }
    for src, dest in mapping.items():
        if src in game_settings and game_settings[src] is not None:
            table[dest] = game_settings[src]
    return table
