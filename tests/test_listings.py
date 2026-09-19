from __future__ import annotations

from collections import Counter

from fpl_radar.features import build_feature_set, rank_xgi_rates
from fpl_radar.fpl_rules import (
    ELEMENT_TYPE_DEF,
    ELEMENT_TYPE_FWD,
    ELEMENT_TYPE_GKP,
    ELEMENT_TYPE_MID,
    take_top_per_position,
)
from fpl_radar.xp.model import ModelContext, rank_horizon_xp
from tests.fixtures import bootstrap_sample
from tests.test_features import _us_league


def test_take_top_per_position_keeps_limit_each() -> None:
    rows = [
        (ELEMENT_TYPE_MID, 3),
        (ELEMENT_TYPE_GKP, 2),
        (ELEMENT_TYPE_MID, 1),
        (ELEMENT_TYPE_DEF, 4),
        (ELEMENT_TYPE_GKP, 0),
        (ELEMENT_TYPE_FWD, 5),
        (ELEMENT_TYPE_FWD, 1),
    ]
    out = take_top_per_position(rows, lambda row: row[0], 1)
    types = [row[0] for row in out]
    assert types == [ELEMENT_TYPE_GKP, ELEMENT_TYPE_DEF, ELEMENT_TYPE_MID, ELEMENT_TYPE_FWD]
    assert [row[1] for row in out] == [2, 4, 3, 5]


def test_rank_horizon_xp_limit_per_position() -> None:
    boot = bootstrap_sample()
    ctx = ModelContext(bootstrap=boot, features=build_feature_set(boot, _us_league()))
    rows = rank_horizon_xp(ctx, horizon=1, limit_per_position=1)
    counts = Counter(int(p.get("element_type") or 0) for p, _xp in rows)
    assert all(n <= 1 for n in counts.values())
    assert set(counts) == {ELEMENT_TYPE_GKP, ELEMENT_TYPE_DEF, ELEMENT_TYPE_MID, ELEMENT_TYPE_FWD}


def test_rank_xgi_rates_limit_per_position() -> None:
    boot = bootstrap_sample()
    features = build_feature_set(boot, _us_league())
    rows = rank_xgi_rates(boot, features, limit_per_position=1)
    counts = Counter(int(p.get("element_type") or 0) for p, _rates in rows)
    assert all(n <= 1 for n in counts.values())
    assert ELEMENT_TYPE_MID in counts
