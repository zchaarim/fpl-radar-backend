from __future__ import annotations

from collections import Counter

import pytest

from fpl_radar.fpl_rules import (
    ELEMENT_TYPE_DEF,
    ELEMENT_TYPE_FWD,
    ELEMENT_TYPE_GKP,
    ELEMENT_TYPE_MID,
    MAX_PLAYERS_PER_CLUB,
    SQUAD_SHAPE,
    transfer_hit_cost,
)
from fpl_radar.models import ManagerSquad, PriceSource, SquadPlayer
from fpl_radar.transfers.plan import make_plan, plan_chip, plan_transfers
from fpl_radar.transfers.rank import rank_replacements
from tests.fixtures import bootstrap_sample


def _squad(bank: int = 50) -> ManagerSquad:
    """2-5-5-3 with at most 3 per club (the 1–15 template is over the club cap)."""
    boot = bootstrap_sample()
    players = {int(p["id"]): p for p in boot["elements"]}
    ids = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 15, 20, 24]
    squad_players = []
    for i in ids:
        meta = players[i]
        squad_players.append(
            SquadPlayer(
                element_id=i,
                web_name=meta["web_name"],
                team_id=meta["team"],
                element_type=meta["element_type"],
                now_cost=meta["now_cost"],
                purchase_price=meta["now_cost"],
                selling_price=meta["now_cost"],
                price_source=PriceSource.ESTIMATED,
            )
        )
    return ManagerSquad(
        entry_id=99,
        bank=bank,
        bank_source="test",
        players=squad_players,
        free_transfers=1,
        free_transfers_source="test",
    )


def test_hit_cost_two_transfers_one_ft() -> None:
    hits, cost = transfer_hit_cost(2, 1, 4)
    assert hits == 1
    assert cost == 4.0
    assert transfer_hit_cost(1, 1, 4) == (0, 0.0)
    assert transfer_hit_cost(0, 2, 4) == (0, 0.0)


def test_plan_at_most_k_with_hit_on_second_move() -> None:
    boot = bootstrap_sample()
    squad = _squad()
    plan = plan_transfers(squad, boot, horizon=1, max_transfers=2, free_transfers=1)
    assert plan.n_transfers <= 2
    assert plan.hits == max(0, plan.n_transfers - 1)
    assert plan.hit_cost == plan.hits * 4
    assert plan.delta_net == pytest.approx(plan.delta_xi - plan.hit_cost)
    assert len(plan.squad_ids) == 15


def test_plan_k1_matches_best_one_for_one() -> None:
    boot = bootstrap_sample()
    squad = _squad()
    options = rank_replacements(squad, boot, horizon=1, limit=50)
    best = max(options, key=lambda option: option.delta)
    plan = plan_transfers(squad, boot, horizon=1, max_transfers=1, free_transfers=1)
    assert plan.n_transfers == 1
    assert plan.delta_xi == pytest.approx(best.delta)
    assert plan.moves[0].element_in == best.element_in
    assert plan.moves[0].element_out == best.element_out


def test_chip_respects_shape_club_and_budget() -> None:
    boot = bootstrap_sample()
    squad = _squad()
    budget = squad.bank + sum(p.selling_price for p in squad.players)
    plan = plan_chip(squad, boot, chip="wildcard", horizon=1)
    assert plan.chip == "wildcard"
    assert plan.hits == 0
    assert plan.n_transfers >= 0
    players = {int(p["id"]): p for p in boot["elements"]}
    types = Counter(int(players[pid]["element_type"]) for pid in plan.squad_ids)
    assert types == SQUAD_SHAPE
    clubs = Counter(int(players[pid]["team"]) for pid in plan.squad_ids)
    assert all(n <= MAX_PLAYERS_PER_CLUB for n in clubs.values())
    spend = sum(int(players[pid]["now_cost"]) for pid in plan.squad_ids)
    assert spend <= budget
    assert set(types) == {ELEMENT_TYPE_GKP, ELEMENT_TYPE_DEF, ELEMENT_TYPE_MID, ELEMENT_TYPE_FWD}


def test_chip_infeasible_budget_raises() -> None:
    boot = bootstrap_sample()
    squad = _squad(bank=0)
    for player in squad.players:
        player.selling_price = 1
    with pytest.raises(RuntimeError, match="infeasible"):
        plan_chip(squad, boot, chip="freehit")


def test_make_plan_freehit_uses_one_gw() -> None:
    boot = bootstrap_sample()
    squad = _squad()
    plan = make_plan(squad, boot, horizon=6, chip="freehit")
    assert plan.chip == "freehit"
    assert list(plan.per_event_delta) == [2]


def test_plan_removes_all_requested_players() -> None:
    boot = bootstrap_sample()
    squad = _squad()
    plan = plan_transfers(
        squad,
        boot,
        horizon=1,
        max_transfers=3,
        free_transfers=1,
        remove_player_ids=[12, 15],
    )
    assert 12 not in plan.squad_ids
    assert 15 not in plan.squad_ids
    assert {12, 15} <= {move.element_out for move in plan.moves}


def test_plan_remove_more_than_k_raises() -> None:
    boot = bootstrap_sample()
    squad = _squad()
    with pytest.raises(ValueError, match="at least 2"):
        plan_transfers(squad, boot, horizon=1, max_transfers=1, remove_player_ids=[12, 15])
