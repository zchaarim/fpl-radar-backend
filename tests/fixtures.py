from __future__ import annotations

from typing import Any


def player(
    pid: int,
    name: str,
    team: int,
    element_type: int,
    now_cost: int,
    ep_next: str = "3.0",
    cost_change_start: int = 0,
) -> dict[str, Any]:
    return {
        "id": pid,
        "web_name": name,
        "first_name": name,
        "second_name": name,
        "team": team,
        "element_type": element_type,
        "now_cost": now_cost,
        "ep_next": ep_next,
        "cost_change_start": cost_change_start,
    }


def bootstrap_sample() -> dict[str, Any]:
    elements = []
    # 15-man legal squad: 2 GK, 5 DEF, 5 MID, 3 FWD across teams 1-5
    template = [
        (1, "GK1", 1, 1, 45),
        (2, "GK2", 2, 1, 40),
        (3, "DEF1", 1, 2, 50),
        (4, "DEF2", 2, 2, 45),
        (5, "DEF3", 3, 2, 45),
        (6, "DEF4", 4, 2, 40),
        (7, "DEF5", 5, 2, 40),
        (8, "MID1", 1, 3, 80),
        (9, "MID2", 2, 3, 70),
        (10, "MID3", 3, 3, 60),
        (11, "MID4", 4, 3, 55),
        (12, "MID5", 5, 3, 50),
        (13, "FWD1", 1, 4, 90),
        (14, "FWD2", 2, 4, 75),
        (15, "FWD3", 3, 4, 65),
        (16, "MID6", 3, 3, 85, "8.0"),
        (17, "DEF6", 1, 2, 55),
        (18, "CLUB4A", 4, 3, 50),
        (19, "CLUB4B", 4, 3, 50),
        (20, "CLUB4C", 4, 4, 50),
        (21, "GK3", 5, 1, 40),
        (22, "DEF7", 5, 2, 40),
        (23, "MID7", 5, 3, 50),
        (24, "FWD4", 5, 4, 55),
        (25, "FWD5", 1, 4, 60),
    ]
    for row in template:
        elements.append(player(*row))
    return {
        "events": [
            {"id": 1, "is_current": False, "is_next": False, "finished": True},
            {"id": 2, "is_current": True, "is_next": False, "finished": False},
        ],
        "teams": [
            {"id": 1, "name": "Arsenal", "short_name": "ARS"},
            {"id": 2, "name": "Chelsea", "short_name": "CHE"},
            {"id": 3, "name": "Liverpool", "short_name": "LIV"},
            {"id": 4, "name": "Manchester United", "short_name": "MUN"},
            {"id": 5, "name": "Fulham", "short_name": "FUL"},
        ],
        "elements": elements,
        "game_settings": {"transfers_sell_on_fee": 0.5},
    }
