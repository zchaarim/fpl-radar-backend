from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fpl_analyser.features import (
    FeatureSet,
    build_feature_set,
    expected_minutes,
    fixture_multiplier,
)
from fpl_analyser.fpl_rules import ELEMENT_TYPE_DEF, ELEMENT_TYPE_FWD, ELEMENT_TYPE_GKP, ELEMENT_TYPE_MID, scoring_table
from fpl_analyser.models import PlayerXp


@dataclass
class ModelContext:
    bootstrap: dict[str, Any]
    fixtures: list[dict[str, Any]] = field(default_factory=list)
    understat_league: dict[str, Any] | None = None
    player_match: dict[int, str] = field(default_factory=dict)
    team_match: dict[int, str] = field(default_factory=dict)
    features: FeatureSet | None = None


GOAL_KEYS = {
    ELEMENT_TYPE_GKP: "goal_gk",
    ELEMENT_TYPE_DEF: "goal_def",
    ELEMENT_TYPE_MID: "goal_mid",
    ELEMENT_TYPE_FWD: "goal_fwd",
}


def player_fixtures(
    team_id: int,
    event_id: int,
    fixtures: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    out = []
    for fixture in fixtures:
        if fixture.get("event") != event_id:
            continue
        if int(fixture.get("team_h") or 0) == team_id or int(fixture.get("team_a") or 0) == team_id:
            out.append(fixture)
    return out


def _minutes_points(exp_mins: float, table: dict[str, int | float]) -> float:
    if exp_mins <= 0:
        return 0.0
    if exp_mins >= 60:
        return float(table["minutes_60_plus"])
    p60 = exp_mins / 60.0
    return float(table["minutes_0_59"]) * (1.0 - p60) + float(table["minutes_60_plus"]) * p60


def expected_points(player_id: int, event_ids: list[int], context: ModelContext) -> PlayerXp:
    players = {int(p["id"]): p for p in context.bootstrap.get("elements") or []}
    player = players.get(int(player_id)) or {}
    features = context.features
    if features is None and context.understat_league is not None:
        features = build_feature_set(context.bootstrap, context.understat_league)

    if features is None:
        try:
            ep_next = float(player.get("ep_next") or 0.0)
        except (TypeError, ValueError):
            ep_next = 0.0
        per_event = {int(eid): ep_next for eid in event_ids}
        return PlayerXp(
            player_id=int(player_id),
            event_ids=[int(eid) for eid in event_ids],
            per_event=per_event,
            horizon_sum=sum(per_event.values()),
            breakdown={"source": "fpl_ep_next_placeholder", "ep_next": ep_next},
            placeholder=True,
        )

    table = scoring_table(context.bootstrap.get("game_settings"))
    rates = features.players.get(int(player_id))
    if rates is None:
        from fpl_analyser.features import fpl_player_rates

        rates = fpl_player_rates(player)
    exp_mins = expected_minutes(player, rates)
    element_type = int(player.get("element_type") or 0)
    team_id = int(player.get("team") or 0)
    goal_pts = float(table[GOAL_KEYS.get(element_type, "goal_mid")])
    assist_pts = float(table["assist"])
    share_mins = exp_mins / 90.0

    per_event: dict[int, float] = {}
    event_break: dict[str, Any] = {}
    for event_id in event_ids:
        fixtures = player_fixtures(team_id, int(event_id), context.fixtures)
        gw_pts = 0.0
        gw_xg = 0.0
        gw_xa = 0.0
        if not fixtures:
            per_event[int(event_id)] = 0.0
            event_break[str(event_id)] = {"blank": True}
            continue
        for fixture in fixtures:
            is_home = int(fixture.get("team_h") or 0) == team_id
            opp_id = int(fixture.get("team_a") if is_home else fixture.get("team_h") or 0)
            mult = fixture_multiplier(features, team_id, opp_id, is_home)
            xg = rates.xg90 * share_mins * mult
            xa = rates.xa90 * share_mins * mult
            gw_xg += xg
            gw_xa += xa
            gw_pts += _minutes_points(exp_mins, table)
            gw_pts += xg * goal_pts
            gw_pts += xa * assist_pts
        per_event[int(event_id)] = gw_pts
        event_break[str(event_id)] = {
            "minutes": exp_mins,
            "xg": round(gw_xg, 4),
            "xa": round(gw_xa, 4),
            "xgi": round(gw_xg + gw_xa, 4),
            "fixtures": len(fixtures),
        }

    return PlayerXp(
        player_id=int(player_id),
        event_ids=[int(eid) for eid in event_ids],
        per_event=per_event,
        horizon_sum=sum(per_event.values()),
        breakdown={
            "source": "xgi_minutes_goals_assists",
            "rate_source": rates.source,
            "xg90": rates.xg90,
            "xa90": rates.xa90,
            "xgi90": rates.xgi90,
            "events": event_break,
        },
        placeholder=False,
    )
