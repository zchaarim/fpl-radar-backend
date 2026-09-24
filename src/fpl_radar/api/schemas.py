from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from fpl_radar.models import PriceSource


class Money(BaseModel):
    tenths: int
    pounds: float


class IdentityCoverage(BaseModel):
    fpl_players: int = 0
    understat_players: int = 0
    matched: int = 0
    unmatched_fpl: int = 0
    unmatched_fpl_with_minutes: int = 0
    unmatched_understat: int = 0
    unmatched_understat_with_minutes: int = 0


class StatusResponse(BaseModel):
    ready: bool
    current_event: int | None = None
    features_ready: bool = False
    placeholder_xp: bool = True
    last_sync_at: float | None = None
    context_built_at: float | None = None
    context_age_seconds: float | None = None
    context_stale: bool = False
    syncing: bool = False
    xp_precomputed: int = 0
    sync_interval_seconds: int = 0
    identity: IdentityCoverage = Field(default_factory=IdentityCoverage)
    cache_dir: str = ""


class SyncResponse(BaseModel):
    fpl: dict[str, Any]
    understat: dict[str, Any]
    identity: IdentityCoverage
    last_sync_at: float | None = None


class EntrySummary(BaseModel):
    entry_id: int
    name: str | None = None
    current_event: int | None = None
    bank: Money
    bank_source: str
    free_transfers: int
    free_transfers_source: str
    authenticated: bool = False


class SquadPlayerRow(BaseModel):
    element_id: int
    web_name: str
    team_id: int
    team_short: str
    element_type: int
    now_cost: Money
    purchase_price: Money
    selling_price: Money
    price_source: PriceSource
    position: int | None = None
    horizon_xp: float
    xgi90: float | None = None
    flag: str = ""


class SquadResponse(EntrySummary):
    horizon: int
    event_ids: list[int]
    xp_source: str
    placeholder: bool
    players: list[SquadPlayerRow]


class ListingPlayer(BaseModel):
    element_id: int
    web_name: str
    team_id: int
    team_short: str
    element_type: int
    now_cost: Money
    flag: str = ""


class XpPlayerRow(ListingPlayer):
    horizon_xp: float
    per_event: dict[int, float] = Field(default_factory=dict)


class XpResponse(BaseModel):
    horizon: int
    event_ids: list[int]
    limit: int
    xp_source: str
    placeholder: bool
    players: list[XpPlayerRow]


class XgiPlayerRow(ListingPlayer):
    source: str
    minutes: float
    xg90: float
    xa90: float
    xgi90: float
    raw_xgi: float
    bps_avg: float
    bonus_e: float


class XgiResponse(BaseModel):
    limit: int
    min_minutes: float
    matched: int
    players_in_features: int
    players: list[XgiPlayerRow]


class RecommendationRow(BaseModel):
    element_out: int
    element_in: int
    out_name: str
    in_name: str
    element_type: int
    selling_price: Money
    now_cost_in: Money
    bank_after: Money
    price_source: PriceSource
    delta: float
    incoming_horizon_xp: float
    out_flag: str = ""
    in_flag: str = ""


class RecommendationsResponse(EntrySummary):
    horizon: int
    event_ids: list[int]
    limit: int
    remove_player_id: int | None = None
    remove_player_name: str | None = None
    xp_source: str
    placeholder: bool
    options: list[RecommendationRow]


class PlanRequest(BaseModel):
    horizon: int = Field(default=5, ge=1, le=15)
    transfers: int = Field(default=3, ge=0, le=15)
    chip: Literal["none", "wildcard", "freehit"] = "none"
    ft: int | None = Field(default=None, ge=0, le=5)
    remove_player: list[str] = Field(default_factory=list)


class PlanMoveRow(BaseModel):
    element_out: int
    element_in: int
    out_name: str
    in_name: str
    element_type: int
    cash_delta: Money
    out_flag: str = ""
    in_flag: str = ""


class PlanSquadPlayer(BaseModel):
    element_id: int
    web_name: str
    team_id: int
    team_short: str
    element_type: int
    role: Literal["XI", "bench"]
    now_cost: Money
    flag: str = ""


class PlanResponse(EntrySummary):
    chip: str | None = None
    horizon: int
    event_ids: list[int]
    n_transfers: int
    hits: int
    hit_cost: float
    current_xi: float
    planned_xi: float
    delta_xi: float
    delta_net: float
    bank_after: Money
    xp_source: str
    placeholder: bool
    moves: list[PlanMoveRow]
    squad: list[PlanSquadPlayer]
