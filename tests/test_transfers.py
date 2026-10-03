from __future__ import annotations

from tests.fixtures import bootstrap_sample

from fpl_radar.models import ManagerSquad, PriceSource, SquadPlayer
from fpl_radar.transfers.rank import is_valid_replacement, rank_replacements
from fpl_radar.xp.model import ModelContext, expected_points


def _squad() -> ManagerSquad:
    boot = bootstrap_sample()
    players = {int(p["id"]): p for p in boot["elements"]}
    squad_players = []
    for i in range(1, 16):
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
    return ManagerSquad(entry_id=99, bank=50, bank_source="test", players=squad_players)


def test_placeholder_xp() -> None:
    boot = bootstrap_sample()
    xp = expected_points(8, [2, 3], ModelContext(bootstrap=boot))
    assert xp.placeholder
    assert xp.horizon_sum == float(boot["elements"][7]["ep_next"]) * 2


def test_three_per_club_blocks() -> None:
    boot = bootstrap_sample()
    players = {int(p["id"]): p for p in boot["elements"]}
    squad = _squad()
    # team 4 already has DEF4 (6) and MID4 (11). Adding two more mids 18,19 would need
    # replacing someone not on team 4 while incoming is team 4 — already 2 on team 4.
    # Put three team-4 players in squad by swapping FWD3 (team 3) mentally:
    squad.players[-1].team_id = 4
    squad.players[-1].element_id = 20
    incoming = players[18]  # team 4 MID
    assert is_valid_replacement(squad, 10, incoming, players) is False


def test_rank_includes_affordable_same_position() -> None:
    boot = bootstrap_sample()
    squad = _squad()
    options = rank_replacements(squad, boot, horizon=1, limit=50)
    assert options
    assert options[0].delta >= options[-1].delta
    mids = [o for o in options if o.element_out == 10]
    assert any(o.element_in == 16 for o in mids)


def test_availability_flags_on_transfer_options() -> None:
    boot = bootstrap_sample()
    boot["elements"][15]["status"] = "d"
    boot["elements"][15]["chance_of_playing_next_round"] = 75
    boot["elements"][15]["news"] = "Knock"
    squad = _squad()
    options = rank_replacements(squad, boot, horizon=1, limit=50)
    flagged = [o for o in options if o.element_in == 16]
    assert flagged
    assert "flag yellow" in flagged[0].in_flag
    assert "75% next GW" in flagged[0].in_flag


def test_rank_remove_player_only_that_out() -> None:
    boot = bootstrap_sample()
    squad = _squad()
    options = rank_replacements(squad, boot, horizon=1, limit=50, remove_player_id=10)
    assert options
    assert all(o.element_out == 10 for o in options)


def test_rank_limit_is_per_position() -> None:
    boot = bootstrap_sample()
    squad = _squad()
    options = rank_replacements(squad, boot, horizon=1, limit=1)
    from collections import Counter

    counts = Counter(o.element_type for o in options)
    assert all(n <= 1 for n in counts.values())
    assert set(counts) <= {1, 2, 3, 4}
