from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PriceSource(str, Enum):
    MY_TEAM = "my_team"
    ESTIMATED = "estimated"
    FALLBACK_NOW_COST = "fallback_now_cost"


class SquadPlayer(BaseModel):
    element_id: int
    web_name: str
    team_id: int
    element_type: int
    now_cost: int
    purchase_price: int
    selling_price: int
    price_source: PriceSource
    position: int | None = None
    is_captain: bool = False
    is_vice_captain: bool = False
    multiplier: int = 1


class ManagerSquad(BaseModel):
    entry_id: int
    name: str | None = None
    current_event: int | None = None
    bank: int
    bank_source: str
    players: list[SquadPlayer]
    authenticated: bool = False
    free_transfers: int = 1
    free_transfers_source: str = "default"


class PlayerXp(BaseModel):
    player_id: int
    event_ids: list[int]
    per_event: dict[int, float]
    horizon_sum: float
    breakdown: dict[str, Any] = Field(default_factory=dict)
    placeholder: bool = True


class TransferOption(BaseModel):
    element_out: int
    element_in: int
    out_name: str
    in_name: str
    selling_price: int
    purchase_price_out: int
    now_cost_in: int
    bank_after: int
    price_source: PriceSource
    delta: float
    incoming_horizon_xp: float
    element_type: int = 0
    per_event_delta: dict[int, float] = Field(default_factory=dict)
    out_flag: str = ""
    in_flag: str = ""
    placeholder: bool = True


class PlanMove(BaseModel):
    element_out: int
    element_in: int
    out_name: str
    in_name: str
    selling_price: int
    now_cost_in: int
    cash_delta: int
    element_type: int = 0
    out_flag: str = ""
    in_flag: str = ""


class TransferPlan(BaseModel):
    chip: str | None = None
    n_transfers: int = 0
    free_transfers: int = 1
    hits: int = 0
    hit_cost: float = 0.0
    delta_xi: float = 0.0
    delta_net: float = 0.0
    current_xi: float = 0.0
    planned_xi: float = 0.0
    bank_after: int = 0
    squad_ids: list[int] = Field(default_factory=list)
    starter_ids: list[int] = Field(default_factory=list)
    moves: list[PlanMove] = Field(default_factory=list)
    per_event_delta: dict[int, float] = Field(default_factory=dict)
    placeholder: bool = True
