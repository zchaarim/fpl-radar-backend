from __future__ import annotations

from typing import Any

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
