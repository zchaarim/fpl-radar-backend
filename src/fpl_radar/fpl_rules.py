"""FPL constants used by the model.

Scoring, squad size, and DefCon thresholds are the published game rules (or
bootstrap `game_settings` when present). Everything else is a modelling choice:

- Shrinkage *k* values: equivalent sample sizes. See comments in this file and
  docs/shrinkage.md (why 4 vs 8 vs 18 vs 30).
- Minutes-when-playing / P(60+|play) / P(play) clusters: typical Premier League
  patterns (keepers finish games; unused squad GKs should not pull Raya to 70').
  Magnitudes are priors, overwritten by live GWs as *n* grows.
- xG/xA/90 and card/90 fallbacks: copies of 2025/26 Understat league rates
  (minutes-weighted, ≥180'). ``sync`` does not rewrite this file; live priors
  are computed from last season’s dump at feature-build time. These dicts are
  used only if that dump is missing.
"""

from __future__ import annotations

from typing import Any

# --- Official FPL rules (high confidence). Scoring falls back if bootstrap omits a key. ---
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

# Shrinkage k: equivalent sample size of the prior. After n = k, 50/50 sample vs prior.
# Chosen from how fast each signal stabilizes (not an FPL backtest). See docs/shrinkage.md.
DEFCON_PRIOR_GAMES = 8
BONUS_PRIOR_GAMES = 8
SAVES_PRIOR_GAMES = 8
YELLOW_PRIOR_GAMES = 8
RED_PRIOR_GAMES = 30
MIN_BONUS_CURVE_BUCKETS = 8
XGI_PRIOR_90S = 8
POSITION_XGI_PRIOR_90S = 8
TEAM_STRENGTH_PRIOR_GAMES = 10
FINISHING_PRIOR_GAMES = 18
HOME_SPLIT_PRIOR_GAMES = 10
MIN_PRIOR_MINUTES = 180
MINUTES_PRIOR_GAMES = 4
# P(play) = share of scheduled GWs with minutes > 0.
# unused:  p_played <= MINUTES_UNUSED_RATE  (true DNPs: 0 minutes every GW)
# rotation: MINUTES_UNUSED_RATE < p_played < MINUTES_REGULAR_RATE
# regular:  p_played >= MINUTES_REGULAR_RATE  (played in at least 60% of GWs)
# There is no MINUTES_ROTATION_RATE; rotation is the open band between the two.
MINUTES_UNUSED_RATE = 0.0
MINUTES_REGULAR_RATE = 0.6

# Minutes *when they play* (not squad averages including DNP). Keepers are almost never subbed.
# Weak hyperpriors when the live sample of playing players is empty.
# Confidence: directional (GK ~90, outfield lower); magnitudes are typical PL, not a paper.
MINUTES_WHEN_PLAYING = {
    ELEMENT_TYPE_GKP: 88.0,
    ELEMENT_TYPE_DEF: 82.0,
    ELEMENT_TYPE_MID: 75.0,
    ELEMENT_TYPE_FWD: 72.0,
}
P60_WHEN_PLAYING = {
    ELEMENT_TYPE_GKP: 0.95,
    ELEMENT_TYPE_DEF: 0.88,
    ELEMENT_TYPE_MID: 0.75,
    ELEMENT_TYPE_FWD: 0.72,
}
# Typical P(play) *inside* a cluster, used as the shrinkage prior.
# Not cutoffs — cutoffs are MINUTES_UNUSED_RATE / MINUTES_REGULAR_RATE above.
P_PLAYED_REGULAR = {
    ELEMENT_TYPE_GKP: 0.92,
    ELEMENT_TYPE_DEF: 0.88,
    ELEMENT_TYPE_MID: 0.82,
    ELEMENT_TYPE_FWD: 0.80,
}
P_PLAYED_ROTATION = {
    ELEMENT_TYPE_GKP: 0.40,
    ELEMENT_TYPE_DEF: 0.45,
    ELEMENT_TYPE_MID: 0.45,
    ELEMENT_TYPE_FWD: 0.45,
}
P_PLAYED_UNUSED = {
    ELEMENT_TYPE_GKP: 0.08,
    ELEMENT_TYPE_DEF: 0.12,
    ELEMENT_TYPE_MID: 0.12,
    ELEMENT_TYPE_FWD: 0.15,
}

# Last-resort if Understat last season is missing. Snapshot: EPL 2025/26,
# minutes-weighted among players with ≥180' (Understat position letter).
# Live path recomputes this from the prior dump using FPL element_type.
XGI90_DEFAULT = {
    ELEMENT_TYPE_GKP: (0.000, 0.004),
    ELEMENT_TYPE_DEF: (0.068, 0.071),
    ELEMENT_TYPE_MID: (0.118, 0.133),
    ELEMENT_TYPE_FWD: (0.349, 0.150),
}
YELLOW90_DEFAULT = {
    ELEMENT_TYPE_GKP: 0.070,
    ELEMENT_TYPE_DEF: 0.182,
    ELEMENT_TYPE_MID: 0.210,
    ELEMENT_TYPE_FWD: 0.143,
}
RED90_DEFAULT = {
    ELEMENT_TYPE_GKP: 0.001,
    ELEMENT_TYPE_DEF: 0.008,
    ELEMENT_TYPE_MID: 0.004,
    ELEMENT_TYPE_FWD: 0.003,
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
