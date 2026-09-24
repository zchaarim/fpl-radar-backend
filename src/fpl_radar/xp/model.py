from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from fpl_radar import config
from fpl_radar.features import (
    FeatureSet,
    build_feature_set,
    expected_goals_conceded_points,
    fixture_goals_against_lambda,
    fixture_multiplier,
    minutes_points,
    p_card_in_minutes,
    poisson_clean_sheet,
    project_minutes,
)
from fpl_radar.fpl_rules import (
    ELEMENT_TYPE_DEF,
    ELEMENT_TYPE_FWD,
    ELEMENT_TYPE_GKP,
    ELEMENT_TYPE_MID,
    scoring_table,
    take_top_per_position,
)
from fpl_radar.models import PlayerXp


@dataclass
class ModelContext:
    bootstrap: dict[str, Any]
    fixtures: list[dict[str, Any]] = field(default_factory=list)
    understat_league: dict[str, Any] | None = None
    understat_prior: dict[str, Any] | None = None
    player_match: dict[int, str] = field(default_factory=dict)
    team_match: dict[int, str] = field(default_factory=dict)
    features: FeatureSet | None = None
    xp_by_player: dict[int, dict[int, float]] = field(default_factory=dict)
    xp_event_ids: list[int] = field(default_factory=list)


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


def expected_points(player_id: int, event_ids: list[int], context: ModelContext) -> PlayerXp:
    players = {int(p["id"]): p for p in context.bootstrap.get("elements") or []}
    player = players.get(int(player_id)) or {}
    features = context.features
    if features is None and context.understat_league is not None:
        features = build_feature_set(
            context.bootstrap,
            context.understat_league,
            understat_prior=context.understat_prior,
        )

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
        from fpl_radar.features import fpl_player_rates

        rates = fpl_player_rates(player)
    exp_mins, p60, p_played = project_minutes(player, rates)
    element_type = int(player.get("element_type") or 0)
    team_id = int(player.get("team") or 0)
    goal_pts = float(table[GOAL_KEYS.get(element_type, "goal_mid")])
    assist_pts = float(table["assist"])
    cs_pts = float(table[CS_KEYS.get(element_type, "clean_sheet_fwd")])
    gc_per = int(table["goals_conceded_per"])
    gc_pts = float(table["goals_conceded_points"])
    defcon_pts = float(table["defcon_points"])
    share_mins = exp_mins / 90.0
    gets_gc = element_type in {ELEMENT_TYPE_GKP, ELEMENT_TYPE_DEF}
    is_gk = element_type == ELEMENT_TYPE_GKP
    defcon_p = rates.defcon_p if not is_gk else 0.0
    saves_e = rates.saves_e if is_gk else 0.0
    yellow_pts = float(table["yellow_card"])
    red_pts = float(table["red_card"])

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
        gw_saves = 0.0
        gw_cards = 0.0
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
            save_xp = p60 * saves_e if is_gk else 0.0
            p_y = p_card_in_minutes(rates.yellow_p, exp_mins)
            p_r = p_card_in_minutes(rates.red_p, exp_mins)
            card_xp = p_y * yellow_pts + p_r * red_pts
            gw_xg += xg
            gw_xa += xa
            gw_cs += cs_xp
            gw_gc += gc_xp
            gw_dc += dc_xp
            gw_bonus += bonus_xp
            gw_saves += save_xp
            gw_cards += card_xp
            gw_lambda += lam_ga
            gw_pts += minutes_points(p_played, p60, table)
            gw_pts += xg * goal_pts
            gw_pts += xa * assist_pts
            gw_pts += cs_xp
            gw_pts += gc_xp
            gw_pts += dc_xp
            gw_pts += bonus_xp
            gw_pts += save_xp
            gw_pts += card_xp
        per_event[int(event_id)] = gw_pts
        event_break[str(event_id)] = {
            "minutes": exp_mins,
            "p60": round(p60, 4),
            "p_played": round(p_played, 4),
            "xg": round(gw_xg, 4),
            "xa": round(gw_xa, 4),
            "xgi": round(gw_xg + gw_xa, 4),
            "lambda_ga": round(gw_lambda, 4),
            "cs_xp": round(gw_cs, 4),
            "gc_xp": round(gw_gc, 4),
            "defcon_xp": round(gw_dc, 4),
            "defcon_p": round(defcon_p, 4),
            "bonus_xp": round(gw_bonus, 4),
            "saves_xp": round(gw_saves, 4),
            "cards_xp": round(gw_cards, 4),
            "yellow_p": round(p_card_in_minutes(rates.yellow_p, exp_mins), 4),
            "red_p": round(p_card_in_minutes(rates.red_p, exp_mins), 4),
            "fixtures": len(fixtures),
        }

    return PlayerXp(
        player_id=int(player_id),
        event_ids=[int(eid) for eid in event_ids],
        per_event=per_event,
        horizon_sum=sum(per_event.values()),
        breakdown={
            "source": "xgi_minutes_cs_gc_defcon_bonus_saves_cards",
            "rate_source": rates.source,
            "xg90": rates.xg90,
            "xa90": rates.xa90,
            "xgi90": rates.xgi90,
            "xg90_raw": rates.xg90_raw,
            "xa90_raw": rates.xa90_raw,
            "defcon_p": rates.defcon_p,
            "defcon_games": rates.defcon_games,
            "defcon_hits": rates.defcon_hits,
            "bps_avg": rates.bps_avg,
            "bonus_avg": rates.bonus_avg,
            "bonus_e": rates.bonus_e,
            "saves_avg": rates.saves_avg,
            "saves_e": rates.saves_e,
            "yellow_p": rates.yellow_p,
            "red_p": rates.red_p,
            "events": event_break,
        },
        placeholder=False,
    )


def horizon_event_ids(bootstrap: dict[str, Any], horizon: int) -> list[int]:
    events = bootstrap.get("events") or []
    current = next((e for e in events if e.get("is_next") or e.get("is_current")), None)
    start = int(current["id"]) if current else 1
    if current and current.get("is_current") and current.get("finished"):
        start = int(current["id"]) + 1
    elif current and current.get("is_current") and not current.get("finished"):
        start = int(current["id"])
    ids = [int(e["id"]) for e in events if int(e["id"]) >= start]
    return ids[:horizon]


def precompute_player_xp(
    context: ModelContext,
    horizon: int | None = None,
) -> ModelContext:
    """Fill ``xp_by_player`` for the next ``horizon`` GWs (all roster players)."""
    width = config.XP_PRECOMPUTE_HORIZON if horizon is None else max(int(horizon), 0)
    event_ids = horizon_event_ids(context.bootstrap, width)
    by_player: dict[int, dict[int, float]] = {}
    for player in context.bootstrap.get("elements") or []:
        pid = int(player["id"])
        xp = expected_points(pid, event_ids, context)
        by_player[pid] = {int(eid): float(pts) for eid, pts in xp.per_event.items()}
    context.xp_by_player = by_player
    context.xp_event_ids = list(event_ids)
    return context


def player_xp(player_id: int, event_ids: list[int], context: ModelContext) -> PlayerXp:
    """Use the precomputed matrix when every requested GW is present."""
    wanted = [int(eid) for eid in event_ids]
    cached = context.xp_by_player.get(int(player_id))
    if cached is not None and all(eid in cached for eid in wanted):
        per_event = {eid: float(cached[eid]) for eid in wanted}
        return PlayerXp(
            player_id=int(player_id),
            event_ids=wanted,
            per_event=per_event,
            horizon_sum=sum(per_event.values()),
            breakdown={"source": "precomputed"},
            placeholder=context.features is None,
        )
    return expected_points(player_id, event_ids, context)


def rank_horizon_xp(
    context: ModelContext,
    horizon: int = 1,
    limit_per_position: int | None = None,
) -> list[tuple[dict[str, Any], PlayerXp]]:
    """Players sorted by horizon xP, ``limit_per_position`` kept for each role."""
    bootstrap = context.bootstrap
    event_ids = horizon_event_ids(bootstrap, horizon)
    rows: list[tuple[dict[str, Any], PlayerXp]] = []
    for player in bootstrap.get("elements") or []:
        xp = player_xp(int(player["id"]), event_ids, context)
        rows.append((player, xp))
    rows.sort(key=lambda row: row[1].horizon_sum, reverse=True)
    return take_top_per_position(
        rows,
        lambda row: int(row[0].get("element_type") or 0),
        limit_per_position,
    )
