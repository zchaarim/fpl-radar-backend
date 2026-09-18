from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fpl_analyser.features import (
    FeatureSet,
    build_feature_set,
    expected_goals_conceded_points,
    expected_minutes,
    fixture_goals_against_lambda,
    fixture_multiplier,
    p_play_sixty,
    poisson_clean_sheet,
)
from fpl_analyser.fpl_rules import (
    ELEMENT_TYPE_DEF,
    ELEMENT_TYPE_FWD,
    ELEMENT_TYPE_GKP,
    ELEMENT_TYPE_MID,
    scoring_table,
)
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

CS_KEYS = {
    ELEMENT_TYPE_GKP: "clean_sheet_gk",
    ELEMENT_TYPE_DEF: "clean_sheet_def",
    ELEMENT_TYPE_MID: "clean_sheet_mid",
    ELEMENT_TYPE_FWD: "clean_sheet_fwd",
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
    cs_pts = float(table[CS_KEYS.get(element_type, "clean_sheet_fwd")])
    gc_per = int(table["goals_conceded_per"])
    gc_pts = float(table["goals_conceded_points"])
    defcon_pts = float(table["defcon_points"])
    share_mins = exp_mins / 90.0
    p60 = p_play_sixty(exp_mins)
    gets_gc = element_type in {ELEMENT_TYPE_GKP, ELEMENT_TYPE_DEF}
    defcon_p = rates.defcon_p if element_type != ELEMENT_TYPE_GKP else 0.0

    per_event: dict[int, float] = {}
    event_break: dict[str, Any] = {}
    for event_id in event_ids:
        fixtures = player_fixtures(team_id, int(event_id), context.fixtures)
        gw_pts = 0.0
        gw_xg = 0.0
        gw_xa = 0.0
        gw_cs = 0.0
        gw_gc = 0.0
        gw_dc = 0.0
        gw_bonus = 0.0
        gw_lambda = 0.0
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
            lam_ga = fixture_goals_against_lambda(features, team_id, opp_id, is_home)
            p_cs = p60 * poisson_clean_sheet(lam_ga)
            cs_xp = p_cs * cs_pts
            gc_xp = p60 * expected_goals_conceded_points(lam_ga, per=gc_per, points_per=gc_pts) if gets_gc else 0.0
            dc_xp = p60 * defcon_p * defcon_pts
            bonus_xp = p60 * rates.bonus_e
            gw_xg += xg
            gw_xa += xa
            gw_cs += cs_xp
            gw_gc += gc_xp
            gw_dc += dc_xp
            gw_bonus += bonus_xp
            gw_lambda += lam_ga
            gw_pts += _minutes_points(exp_mins, table)
            gw_pts += xg * goal_pts
            gw_pts += xa * assist_pts
            gw_pts += cs_xp
            gw_pts += gc_xp
            gw_pts += dc_xp
            gw_pts += bonus_xp
        per_event[int(event_id)] = gw_pts
        event_break[str(event_id)] = {
            "minutes": exp_mins,
            "p60": round(p60, 4),
            "xg": round(gw_xg, 4),
            "xa": round(gw_xa, 4),
            "xgi": round(gw_xg + gw_xa, 4),
            "lambda_ga": round(gw_lambda, 4),
            "cs_xp": round(gw_cs, 4),
            "gc_xp": round(gw_gc, 4),
            "defcon_xp": round(gw_dc, 4),
            "defcon_p": round(defcon_p, 4),
            "bonus_xp": round(gw_bonus, 4),
            "fixtures": len(fixtures),
        }

    return PlayerXp(
        player_id=int(player_id),
        event_ids=[int(eid) for eid in event_ids],
        per_event=per_event,
        horizon_sum=sum(per_event.values()),
        breakdown={
            "source": "xgi_minutes_cs_gc_defcon_bonus",
            "rate_source": rates.source,
            "xg90": rates.xg90,
            "xa90": rates.xa90,
            "xgi90": rates.xgi90,
            "defcon_p": rates.defcon_p,
            "defcon_games": rates.defcon_games,
            "defcon_hits": rates.defcon_hits,
            "bps_avg": rates.bps_avg,
            "bonus_avg": rates.bonus_avg,
            "bonus_e": rates.bonus_e,
            "events": event_break,
        },
        placeholder=False,
    )
