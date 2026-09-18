from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

from fpl_analyser.fpl_rules import (
    BONUS_PRIOR_GAMES,
    DEFCON_PRIOR_GAMES,
    ELEMENT_TYPE_DEF,
    ELEMENT_TYPE_FWD,
    ELEMENT_TYPE_GKP,
    ELEMENT_TYPE_MID,
    MIN_BONUS_CURVE_BUCKETS,
    SAVES_PRIOR_GAMES,
    YELLOW90_DEFAULT,
    YELLOW_PRIOR_GAMES,
    RED90_DEFAULT,
    RED_PRIOR_GAMES,
    defcon_threshold,
    scoring_table,
)
from fpl_analyser.identity.match import load_overrides, match_players, match_teams


def _f(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _i(value: Any) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


@dataclass
class TeamStrength:
    us_id: str
    title: str
    matches: int
    xg_pg: float
    xga_pg: float
    gf_pg: float
    ga_pg: float
    att: float
    dfn: float  # defensive weakness; 1.0 = league average, higher = leakier
    att_home: float
    att_away: float
    def_home: float
    def_away: float


@dataclass
class PlayerRates:
    us_id: str | None
    minutes: float
    games: float
    xg: float
    xa: float
    xgi: float
    xg90: float
    xa90: float
    xgi90: float
    source: str
    defcon90: float = 0.0
    defcon_games: int = 0
    defcon_hits: int = 0
    defcon_p: float = 0.0
    defcon_source: str = "none"
    bps_avg: float = 0.0
    bonus_avg: float = 0.0
    bonus_e: float = 0.0
    bonus_games: int = 0
    bonus_source: str = "none"
    saves_avg: float = 0.0
    saves_e: float = 0.0
    saves_games: int = 0
    saves_hits: int = 0
    saves_source: str = "none"
    yellow90: float = 0.0
    red90: float = 0.0
    yellow_p: float = 0.0
    red_p: float = 0.0
    yellow_games: int = 0
    cards_source: str = "none"


@dataclass
class FeatureSet:
    teams: dict[int, TeamStrength] = field(default_factory=dict)
    players: dict[int, PlayerRates] = field(default_factory=dict)
    league_xg_pg: float = 1.4
    unmatched_players: list[int] = field(default_factory=list)


def _history_rows(team: dict[str, Any]) -> list[dict[str, Any]]:
    history = team.get("history") or []
    return [row for row in history if isinstance(row, dict)]


def _split_pg(rows: list[dict[str, Any]], ha: str | None = None) -> tuple[float, float, float, float, int]:
    selected = rows if ha is None else [r for r in rows if r.get("h_a") == ha]
    if not selected:
        return 0.0, 0.0, 0.0, 0.0, 0
    n = len(selected)
    xg = sum(_f(r.get("xG")) for r in selected) / n
    xga = sum(_f(r.get("xGA")) for r in selected) / n
    gf = sum(_f(r.get("scored")) for r in selected) / n
    ga = sum(_f(r.get("missed")) for r in selected) / n
    return xg, xga, gf, ga, n


def _blend(actual: float, expected: float, weight: float = 0.5) -> float:
    return weight * expected + (1.0 - weight) * actual


def team_strengths(understat_teams: dict[str, Any]) -> dict[str, TeamStrength]:
    raw: dict[str, dict[str, float]] = {}
    for us_id, team in (understat_teams or {}).items():
        if not isinstance(team, dict):
            continue
        rows = _history_rows(team)
        if not rows:
            continue
        xg, xga, gf, ga, n = _split_pg(rows)
        hxg, hxga, hgf, hga, hn = _split_pg(rows, "h")
        axg, axga, agf, aga, an = _split_pg(rows, "a")
        if hn == 0:
            hxg, hxga, hgf, hga = xg, xga, gf, ga
        if an == 0:
            axg, axga, agf, aga = xg, xga, gf, ga
        raw[str(team.get("id") or us_id)] = {
            "title": team.get("title") or "",
            "n": float(n),
            "xg": xg,
            "xga": xga,
            "gf": gf,
            "ga": ga,
            "hxg": hxg,
            "hxga": hxga,
            "hgf": hgf,
            "hga": hga,
            "axg": axg,
            "axga": axga,
            "agf": agf,
            "aga": aga,
        }
    if not raw:
        return {}
    avg_xg = sum(v["xg"] for v in raw.values()) / len(raw)
    avg_xga = sum(v["xga"] for v in raw.values()) / len(raw)
    avg_gf = sum(v["gf"] for v in raw.values()) / len(raw)
    avg_ga = sum(v["ga"] for v in raw.values()) / len(raw)
    avg_att = max(_blend(avg_gf, avg_xg), 0.05)
    avg_def = max(_blend(avg_ga, avg_xga), 0.05)

    result: dict[str, TeamStrength] = {}
    for us_id, v in raw.items():
        att = _blend(v["gf"], v["xg"]) / avg_att
        dfn = _blend(v["ga"], v["xga"]) / avg_def
        result[us_id] = TeamStrength(
            us_id=us_id,
            title=str(v["title"]),
            matches=int(v["n"]),
            xg_pg=v["xg"],
            xga_pg=v["xga"],
            gf_pg=v["gf"],
            ga_pg=v["ga"],
            att=att,
            dfn=dfn,
            att_home=_blend(v["hgf"], v["hxg"]) / avg_att,
            att_away=_blend(v["agf"], v["axg"]) / avg_att,
            def_home=_blend(v["hga"], v["hxga"]) / avg_def,
            def_away=_blend(v["aga"], v["axga"]) / avg_def,
        )
    return result


def player_understat_rates(understat_players: list[dict[str, Any]]) -> dict[str, PlayerRates]:
    result: dict[str, PlayerRates] = {}
    for player in understat_players or []:
        pid = str(player.get("id") or "")
        minutes = _f(player.get("time"))
        games = max(_f(player.get("games")), 1.0)
        xg = _f(player.get("xG"))
        xa = _f(player.get("xA"))
        per90 = minutes / 90.0 if minutes > 0 else games
        per90 = max(per90, 1e-6)
        result[pid] = PlayerRates(
            us_id=pid,
            minutes=minutes,
            games=games,
            xg=xg,
            xa=xa,
            xgi=xg + xa,
            xg90=xg / per90,
            xa90=xa / per90,
            xgi90=(xg + xa) / per90,
            source="understat",
        )
    return result


def fpl_player_rates(player: dict[str, Any]) -> PlayerRates:
    minutes = _f(player.get("minutes"))
    games = max(_f(player.get("starts") or player.get("appearances")), 1.0)
    xg = _f(player.get("expected_goals"))
    xa = _f(player.get("expected_assists"))
    per90 = minutes / 90.0 if minutes > 0 else games
    per90 = max(per90, 1e-6)
    return PlayerRates(
        us_id=None,
        minutes=minutes,
        games=games,
        xg=xg,
        xa=xa,
        xgi=xg + xa,
        xg90=xg / per90,
        xa90=xa / per90,
        xgi90=(xg + xa) / per90,
        source="fpl",
    )


def expected_minutes(player: dict[str, Any], rates: PlayerRates) -> float:
    chance = player.get("chance_of_playing_next_round")
    if chance is not None and _f(chance) == 0:
        return 0.0
    if rates.games > 0 and rates.minutes > 0:
        mins = min(90.0, rates.minutes / max(rates.games, 1.0))
    else:
        mins = 60.0 if _i(player.get("starts")) else 15.0
    if chance is not None:
        mins *= _f(chance) / 100.0
    status = (player.get("status") or "a").lower()
    if status in {"i", "s", "u", "n"}:
        mins = 0.0
    return max(0.0, min(90.0, mins))


def build_feature_set(
    bootstrap: dict[str, Any],
    understat_league: dict[str, Any] | None,
    live_defcon: dict[int, list[tuple[int, float]]] | None = None,
    live_matches: dict[int, list[dict[str, float]]] | None = None,
) -> FeatureSet:
    fpl_teams = bootstrap.get("teams") or []
    fpl_players = bootstrap.get("elements") or []
    overrides = load_overrides()
    us_teams = (understat_league or {}).get("teams") or {}
    us_players = (understat_league or {}).get("players") or []
    team_map = match_teams(fpl_teams, us_teams, overrides) if us_teams else {}
    player_map = (
        match_players(fpl_players, us_players, team_map, fpl_teams, overrides) if us_players else {}
    )
    strengths = team_strengths(us_teams) if us_teams else {}
    us_rates = player_understat_rates(us_players)

    teams: dict[int, TeamStrength] = {}
    for fpl_id, us_id in team_map.items():
        if us_id in strengths:
            teams[int(fpl_id)] = strengths[us_id]

    league_xg = (
        sum(t.xg_pg for t in teams.values()) / len(teams) if teams else 1.4
    )

    players: dict[int, PlayerRates] = {}
    unmatched: list[int] = []
    for player in fpl_players:
        eid = int(player["id"])
        us_id = player_map.get(eid)
        if us_id and us_id in us_rates:
            players[eid] = us_rates[us_id]
        else:
            players[eid] = fpl_player_rates(player)
            if us_players:
                unmatched.append(eid)

    if live_matches and not live_defcon:
        live_defcon = {
            pid: [(int(row["minutes"]), row.get("defensive_contribution") or 0.0) for row in rows]
            for pid, rows in live_matches.items()
        }
    players = attach_defcon(players, fpl_players, live_defcon)
    players = attach_bonus(players, fpl_players, live_matches)
    players = attach_saves(
        players,
        fpl_players,
        live_matches,
        scoring_table(bootstrap.get("game_settings")),
    )
    players = attach_cards(players, fpl_players, live_matches)
    return FeatureSet(
        teams=teams,
        players=players,
        league_xg_pg=league_xg,
        unmatched_players=unmatched,
    )


def fixture_multiplier(
    features: FeatureSet,
    team_id: int,
    opponent_id: int,
    is_home: bool,
) -> float:
    """Attack vs opposition defence, home/away split when Understat strengths exist."""
    team = features.teams.get(team_id)
    opp = features.teams.get(opponent_id)
    if not team or not opp:
        return 1.0
    att = team.att_home if is_home else team.att_away
    dfn = opp.def_away if is_home else opp.def_home
    return max(0.25, att * dfn)


def fixture_goals_against_lambda(
    features: FeatureSet,
    team_id: int,
    opponent_id: int,
    is_home: bool,
) -> float:
    """Expected goals conceded by team_id in this fixture (Poisson lambda)."""
    team = features.teams.get(team_id)
    opp = features.teams.get(opponent_id)
    league = max(features.league_xg_pg, 0.05)
    if not team or not opp:
        return league
    opp_att = opp.att_away if is_home else opp.att_home
    our_def = team.def_home if is_home else team.def_away
    return max(0.05, league * opp_att * our_def)


def poisson_pmf(k: int, lam: float) -> float:
    if k < 0:
        return 0.0
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-lam) * (lam**k) / math.factorial(k)


def poisson_clean_sheet(lam: float) -> float:
    return math.exp(-max(lam, 0.0))


def expected_goals_conceded_points(
    lam: float,
    per: int = 2,
    points_per: float = -1.0,
    k_max: int = 12,
) -> float:
    """E[floor(goals / per) * points_per] under Poisson(lam)."""
    total = 0.0
    for k in range(k_max + 1):
        total += (k // per) * poisson_pmf(k, lam)
    return total * points_per


def p_play_sixty(exp_mins: float) -> float:
    """FPL CS and GC both require 60+ minutes."""
    if exp_mins <= 0:
        return 0.0
    if exp_mins >= 70:
        return 1.0
    if exp_mins <= 30:
        return 0.0
    return (exp_mins - 30.0) / 40.0


def poisson_tail(threshold: int, lam: float) -> float:
    """P(X >= threshold) for X ~ Poisson(lam)."""
    if threshold <= 0:
        return 1.0
    return max(0.0, min(1.0, 1.0 - sum(poisson_pmf(k, lam) for k in range(threshold))))


def position_defcon90(players: list[dict[str, Any]], element_type: int) -> float:
    rates = []
    for player in players:
        if int(player.get("element_type") or 0) != element_type:
            continue
        if _f(player.get("minutes")) < 180:
            continue
        rate = _f(player.get("defensive_contribution_per_90"))
        if rate > 0:
            rates.append(rate)
    return sum(rates) / len(rates) if rates else 8.0


def live_defcon_record(appearances: list[tuple[int, float]], threshold: int) -> tuple[int, int, float]:
    """Eligible 60+ minute games, threshold hits, mean actions in those games."""
    eligible = [(m, a) for m, a in appearances if m >= 60]
    if not eligible:
        return 0, 0, 0.0
    hits = sum(1 for _m, actions in eligible if actions >= threshold)
    mean = sum(a for _m, a in eligible) / len(eligible)
    return len(eligible), hits, mean


def shrink_defcon_p(
    games: int,
    hits: int,
    own_lambda: float,
    pos_lambda: float,
    threshold: int,
    prior_games: int = DEFCON_PRIOR_GAMES,
) -> float:
    """Blend observed hit rate with Poisson(average), shrunk toward the position mean.

    Small samples cannot sit at 100% just because they cleared the threshold once.
    """
    n = max(games, 0)
    k = max(prior_games, 1)
    lam = (n * own_lambda + k * pos_lambda) / (n + k)
    from_mean = poisson_tail(threshold, lam)
    observed = hits / n if n > 0 else from_mean
    weight = n / (n + k)
    return max(0.0, min(1.0, weight * observed + (1.0 - weight) * from_mean))


def attach_defcon(
    rates_by_id: dict[int, PlayerRates],
    fpl_players: list[dict[str, Any]],
    live_defcon: dict[int, list[tuple[int, float]]] | None,
) -> dict[int, PlayerRates]:
    live_defcon = live_defcon or {}
    pos_lam = {
        etype: position_defcon90(fpl_players, etype)
        for etype in (ELEMENT_TYPE_DEF, ELEMENT_TYPE_MID, ELEMENT_TYPE_FWD)
    }
    updated: dict[int, PlayerRates] = {}
    for player in fpl_players:
        eid = int(player["id"])
        rates = rates_by_id.get(eid) or fpl_player_rates(player)
        threshold = defcon_threshold(int(player.get("element_type") or 0))
        if threshold is None:
            updated[eid] = replace(rates, defcon_p=0.0, defcon_source="gk")
            continue
        own90 = _f(player.get("defensive_contribution_per_90"))
        games, hits, mean_actions = live_defcon_record(live_defcon.get(eid, []), threshold)
        if own90 <= 0:
            own90 = mean_actions
        p_hit = shrink_defcon_p(
            games,
            hits,
            own90,
            pos_lam.get(int(player.get("element_type") or 0), 8.0),
            threshold,
        )
        source = "live+mean" if games else "mean"
        updated[eid] = replace(
            rates,
            defcon90=own90,
            defcon_games=games,
            defcon_hits=hits,
            defcon_p=p_hit,
            defcon_source=source,
        )
    for eid, rates in rates_by_id.items():
        if eid not in updated:
            updated[eid] = rates
    return updated


def heuristic_bonus_from_bps(bps: float) -> float:
    """Rough E[bonus] from typical match BPS ranks when no live curve exists."""
    if bps <= 0:
        return 0.0
    if bps < 12:
        return 0.02 * bps
    if bps < 22:
        return 0.24 + (bps - 12) * 0.04
    if bps < 30:
        return 0.64 + (bps - 22) * 0.12
    return min(2.4, 1.6 + (bps - 30) * 0.12)


def build_bonus_curve(live_matches: dict[int, list[dict[str, float]]] | None) -> dict[int, float]:
    buckets: dict[int, list[float]] = {}
    for rows in (live_matches or {}).values():
        for row in rows:
            if (row.get("minutes") or 0) < 45:
                continue
            key = int(round(row.get("bps") or 0))
            buckets.setdefault(key, []).append(row.get("bonus") or 0.0)
    return {bps: sum(vals) / len(vals) for bps, vals in buckets.items() if vals}


def expected_bonus_from_bps(bps: float, curve: dict[int, float]) -> float:
    prior = heuristic_bonus_from_bps(bps)
    if len(curve) < MIN_BONUS_CURVE_BUCKETS:
        return prior

    def lookup(key: int) -> float:
        if key in curve:
            return curve[key]
        nearest = min(curve, key=lambda item: abs(item - key))
        fallback = heuristic_bonus_from_bps(float(key))
        if abs(nearest - key) > 6:
            return fallback
        return curve[nearest]

    lo = int(math.floor(bps))
    hi = lo + 1
    frac = bps - lo
    return lookup(lo) * (1.0 - frac) + lookup(hi) * frac


def live_bonus_record(rows: list[dict[str, float]]) -> tuple[int, float, float]:
    eligible = [row for row in rows if (row.get("minutes") or 0) >= 45]
    if not eligible:
        return 0, 0.0, 0.0
    n = len(eligible)
    mean_bonus = sum(row.get("bonus") or 0.0 for row in eligible) / n
    mean_bps = sum(row.get("bps") or 0.0 for row in eligible) / n
    return n, mean_bonus, mean_bps


def position_bps_pg(players: list[dict[str, Any]], element_type: int) -> float:
    vals: list[float] = []
    for player in players:
        if int(player.get("element_type") or 0) != element_type:
            continue
        minutes = _f(player.get("minutes"))
        if minutes < 180:
            continue
        games = max(_f(player.get("starts")), minutes / 90.0)
        if games < 2:
            continue
        vals.append(_f(player.get("bps")) / games)
    return sum(vals) / len(vals) if vals else 18.0


def shrink_bonus_e(
    games: int,
    observed_bonus: float,
    own_bps: float,
    pos_bps: float,
    curve: dict[int, float],
    prior_games: int = BONUS_PRIOR_GAMES,
) -> float:
    n = max(games, 0)
    k = max(prior_games, 1)
    shrunk_bps = (n * own_bps + k * pos_bps) / (n + k)
    prior = expected_bonus_from_bps(shrunk_bps, curve)
    observed = observed_bonus if n > 0 else prior
    weight = n / (n + k)
    return max(0.0, min(3.0, weight * observed + (1.0 - weight) * prior))


def attach_bonus(
    rates_by_id: dict[int, PlayerRates],
    fpl_players: list[dict[str, Any]],
    live_matches: dict[int, list[dict[str, float]]] | None,
) -> dict[int, PlayerRates]:
    live_matches = live_matches or {}
    curve = build_bonus_curve(live_matches)
    pos_bps = {
        etype: position_bps_pg(fpl_players, etype)
        for etype in (ELEMENT_TYPE_GKP, ELEMENT_TYPE_DEF, ELEMENT_TYPE_MID, ELEMENT_TYPE_FWD)
    }
    updated: dict[int, PlayerRates] = {}
    for player in fpl_players:
        eid = int(player["id"])
        rates = rates_by_id.get(eid) or fpl_player_rates(player)
        etype = int(player.get("element_type") or 0)
        minutes = _f(player.get("minutes"))
        starts = max(_f(player.get("starts")), minutes / 90.0, 1.0)
        season_bps = _f(player.get("bps")) / starts
        season_bonus = _f(player.get("bonus")) / starts
        games, mean_bonus, mean_bps = live_bonus_record(live_matches.get(eid, []))
        own_bps = mean_bps if games else season_bps
        observed = mean_bonus if games else season_bonus
        n = games if games else (int(starts) if season_bonus or season_bps else 0)
        bonus_e = shrink_bonus_e(
            n,
            observed,
            own_bps,
            pos_bps.get(etype, 18.0),
            curve,
        )
        updated[eid] = replace(
            rates,
            bps_avg=own_bps,
            bonus_avg=observed,
            bonus_e=bonus_e,
            bonus_games=games,
            bonus_source="live+bps" if games else "season+bps",
        )
    for eid, rates in rates_by_id.items():
        if eid not in updated:
            updated[eid] = rates
    return updated


def expected_save_points(
    lam: float,
    per: int = 3,
    points_per: float = 1.0,
    k_max: int = 15,
) -> float:
    """E[floor(saves / per) * points] under Poisson(lam). 2.0 avg saves is not 0.67 pts."""
    total = 0.0
    for k in range(k_max + 1):
        total += (k // per) * poisson_pmf(k, lam)
    return total * points_per


def position_saves_pg(players: list[dict[str, Any]]) -> float:
    vals: list[float] = []
    for player in players:
        if int(player.get("element_type") or 0) != ELEMENT_TYPE_GKP:
            continue
        minutes = _f(player.get("minutes"))
        if minutes < 180:
            continue
        games = max(_f(player.get("starts")), minutes / 90.0)
        if games < 2:
            continue
        vals.append(_f(player.get("saves")) / games)
    return sum(vals) / len(vals) if vals else 3.0


def live_saves_record(
    rows: list[dict[str, float]],
    per: int = 3,
) -> tuple[int, float, float, int]:
    eligible = [row for row in rows if (row.get("minutes") or 0) >= 60]
    if not eligible:
        return 0, 0.0, 0.0, 0
    n = len(eligible)
    mean_saves = sum(row.get("saves") or 0.0 for row in eligible) / n
    mean_pts = sum(int((row.get("saves") or 0.0) // per) for row in eligible) / n
    hits = sum(1 for row in eligible if (row.get("saves") or 0.0) >= per)
    return n, mean_saves, mean_pts, hits


def shrink_saves_e(
    games: int,
    observed_pts: float,
    own_lam: float,
    pos_lam: float,
    per: int = 3,
    points_per: float = 1.0,
    prior_games: int = SAVES_PRIOR_GAMES,
) -> float:
    n = max(games, 0)
    k = max(prior_games, 1)
    lam = (n * own_lam + k * pos_lam) / (n + k)
    from_mean = expected_save_points(lam, per=per, points_per=points_per)
    observed = observed_pts if n > 0 else from_mean
    weight = n / (n + k)
    return max(0.0, weight * observed + (1.0 - weight) * from_mean)


def attach_saves(
    rates_by_id: dict[int, PlayerRates],
    fpl_players: list[dict[str, Any]],
    live_matches: dict[int, list[dict[str, float]]] | None,
    table: dict[str, int | float] | None = None,
) -> dict[int, PlayerRates]:
    live_matches = live_matches or {}
    table = table or scoring_table()
    per = int(table["save_per"])
    points_per = float(table["save_points"])
    pos_lam = position_saves_pg(fpl_players)
    updated: dict[int, PlayerRates] = {}
    for player in fpl_players:
        eid = int(player["id"])
        rates = rates_by_id.get(eid) or fpl_player_rates(player)
        if int(player.get("element_type") or 0) != ELEMENT_TYPE_GKP:
            updated[eid] = replace(rates, saves_e=0.0, saves_source="outfield")
            continue
        minutes = _f(player.get("minutes"))
        starts = max(_f(player.get("starts")), minutes / 90.0)
        season_avg = _f(player.get("saves")) / max(starts, 1.0) if starts else 0.0
        games, mean_saves, mean_pts, hits = live_saves_record(
            live_matches.get(eid, []),
            per=per,
        )
        own = mean_saves if games else season_avg
        observed = mean_pts if games else expected_save_points(own, per=per, points_per=points_per)
        n = games if games else (int(starts) if own else 0)
        saves_e = shrink_saves_e(
            n,
            observed,
            own,
            pos_lam,
            per=per,
            points_per=points_per,
        )
        updated[eid] = replace(
            rates,
            saves_avg=own,
            saves_e=saves_e,
            saves_games=games,
            saves_hits=hits,
            saves_source="live" if games else "season",
        )
    for eid, rates in rates_by_id.items():
        if eid not in updated:
            updated[eid] = rates
    return updated


def p_card_in_minutes(p90: float, minutes: float) -> float:
    """Scale a 90-minute card probability to expected minutes."""
    if minutes <= 0 or p90 <= 0:
        return 0.0
    share = minutes / 90.0
    return 1.0 - (1.0 - min(p90, 0.999)) ** share


def position_card90(
    players: list[dict[str, Any]],
    element_type: int,
    field: str,
    default: float,
) -> float:
    vals: list[float] = []
    for player in players:
        if int(player.get("element_type") or 0) != element_type:
            continue
        minutes = _f(player.get("minutes"))
        if minutes < 180:
            continue
        n90 = minutes / 90.0
        vals.append(_f(player.get(field)) / n90)
    return sum(vals) / len(vals) if vals else default


def live_card_record(rows: list[dict[str, float]], field: str) -> tuple[int, float, int, float]:
    """apps, equivalent 90s, games with a card, cards per 90."""
    eligible = [row for row in rows if (row.get("minutes") or 0) > 0]
    if not eligible:
        return 0, 0.0, 0, 0.0
    minutes = sum(row.get("minutes") or 0.0 for row in eligible)
    n90 = minutes / 90.0
    cards = sum(row.get(field) or 0.0 for row in eligible)
    hits = sum(1 for row in eligible if (row.get(field) or 0.0) > 0)
    own90 = cards / n90 if n90 > 0 else 0.0
    return len(eligible), n90, hits, own90


def shrink_card_p(
    n90: float,
    apps: int,
    hits: int,
    own90: float,
    pos90: float,
    prior_games: int,
) -> tuple[float, float]:
    n = max(n90, 0.0)
    k = float(max(prior_games, 1))
    lam = (n * own90 + k * pos90) / (n + k) if (n + k) else pos90
    from_mean = 1.0 - math.exp(-max(lam, 0.0))
    observed = hits / apps if apps > 0 else from_mean
    weight = n / (n + k) if (n + k) else 0.0
    p90 = max(0.0, min(0.95, weight * observed + (1.0 - weight) * from_mean))
    return lam, p90


def attach_cards(
    rates_by_id: dict[int, PlayerRates],
    fpl_players: list[dict[str, Any]],
    live_matches: dict[int, list[dict[str, float]]] | None,
) -> dict[int, PlayerRates]:
    live_matches = live_matches or {}
    pos_y = {
        etype: position_card90(fpl_players, etype, "yellow_cards", YELLOW90_DEFAULT[etype])
        for etype in (ELEMENT_TYPE_GKP, ELEMENT_TYPE_DEF, ELEMENT_TYPE_MID, ELEMENT_TYPE_FWD)
    }
    pos_r = {
        etype: position_card90(fpl_players, etype, "red_cards", RED90_DEFAULT[etype])
        for etype in (ELEMENT_TYPE_GKP, ELEMENT_TYPE_DEF, ELEMENT_TYPE_MID, ELEMENT_TYPE_FWD)
    }
    updated: dict[int, PlayerRates] = {}
    for player in fpl_players:
        eid = int(player["id"])
        rates = rates_by_id.get(eid) or fpl_player_rates(player)
        etype = int(player.get("element_type") or 0)
        minutes = _f(player.get("minutes"))
        n90_season = minutes / 90.0
        apps, n90_live, y_hits, y90_live = live_card_record(live_matches.get(eid, []), "yellow_cards")
        _a, _n, r_hits, r90_live = live_card_record(live_matches.get(eid, []), "red_cards")
        if n90_live > 0:
            n90, y90, r90, n_apps = n90_live, y90_live, r90_live, apps
            y_obs, r_obs = y_hits, r_hits
            source = "live"
        else:
            n90 = n90_season
            y90 = _f(player.get("yellow_cards")) / n90 if n90 else 0.0
            r90 = _f(player.get("red_cards")) / n90 if n90 else 0.0
            n_apps = int(round(n90)) if n90 else 0
            y_obs = _i(player.get("yellow_cards"))
            r_obs = _i(player.get("red_cards"))
            source = "season"
        y_lam, yellow_p = shrink_card_p(
            n90,
            n_apps,
            y_obs,
            y90,
            pos_y.get(etype, YELLOW90_DEFAULT.get(etype, 0.12)),
            YELLOW_PRIOR_GAMES,
        )
        r_lam, red_p = shrink_card_p(
            n90,
            n_apps,
            r_obs,
            r90,
            pos_r.get(etype, RED90_DEFAULT.get(etype, 0.02)),
            RED_PRIOR_GAMES,
        )
        updated[eid] = replace(
            rates,
            yellow90=y_lam,
            red90=r_lam,
            yellow_p=yellow_p,
            red_p=red_p,
            yellow_games=y_obs,
            cards_source=source,
        )
    for eid, rates in rates_by_id.items():
        if eid not in updated:
            updated[eid] = rates
    return updated
