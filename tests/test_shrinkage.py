from tests.fixtures import bootstrap_sample

from fpl_radar.features import attach_minutes, fpl_player_rates
from fpl_radar.fpl_rules import ShrinkageConfig, shrinkage_from_overrides


def test_variant_slug() -> None:
    assert ShrinkageConfig().variant_slug() == "default"
    cfg = shrinkage_from_overrides(minutes_k=2, xgi_k=16)
    assert cfg.variant_slug() == "minutes-k-2_xgi-k-16"


def test_minutes_k_moves_expected_minutes() -> None:
    boot = bootstrap_sample()
    rates = {8: fpl_player_rates(boot["elements"][7])}
    live = {8: [{"minutes": 45}] * 4}
    sticky = attach_minutes(
        rates, boot["elements"], live, finished_gws=4, shrinkage=ShrinkageConfig(minutes_k=80)
    )
    loose = attach_minutes(
        rates, boot["elements"], live, finished_gws=4, shrinkage=ShrinkageConfig(minutes_k=1)
    )
    assert sticky[8].exp_mins != loose[8].exp_mins
