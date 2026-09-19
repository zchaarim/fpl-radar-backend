from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

from fpl_radar.fpl_rules import (
    BONUS_PRIOR_GAMES,
    DEFCON_PRIOR_GAMES,
    ELEMENT_TYPE_DEF,
    ELEMENT_TYPE_FWD,
    ELEMENT_TYPE_GKP,
    ELEMENT_TYPE_MID,
    FINISHING_PRIOR_GAMES,
    HOME_SPLIT_PRIOR_GAMES,
    MIN_BONUS_CURVE_BUCKETS,
    MIN_PRIOR_MINUTES,
    POSITION_XGI_PRIOR_90S,
    SAVES_PRIOR_GAMES,
    TEAM_STRENGTH_PRIOR_GAMES,
    XGI90_DEFAULT,
    XGI_PRIOR_90S,
    YELLOW90_DEFAULT,
    YELLOW_PRIOR_GAMES,
    RED90_DEFAULT,
    RED_PRIOR_GAMES,
    defcon_threshold,
    scoring_table,
)
from fpl_radar.identity.match import (
    canonical_team,
    load_overrides,
    map_understat_players,
    match_players,
    match_teams,
)


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
    venue_home: float = 1.0
    venue_away: float = 1.0


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
    xg90_raw: float = 0.0
    xa90_raw: float = 0.0
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
    league_ha_home: float = 1.0
    league_ha_away: float = 1.0
    unmatched_players: list[int] = field(default_factory=list)


def shrink_mean(observed: float, prior: float, n: float, k: float) -> float:
    """Posterior mean if the prior is worth ``k`` observations at ``prior``.

    Same conjugate update as a Normal mean with known variance, or a Gamma-Poisson
    rate with a prior equivalent sample size of ``k``. After ``n = k`` games the
    estimate is halfway between the sample and the prior.
    """
    n = max(float(n), 0.0)
    k = max(float(k), 0.0)
    if n + k <= 0:
        return prior
    return (n * observed + k * prior) / (n + k)


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


def _finishing_ratio(goals_pg: float, xg_pg: float) -> float:
    if xg_pg <= 0.05:
        return 1.0
    return goals_pg / xg_pg


def _collect_team_raw(understat_teams: dict[str, Any]) -> dict[str, dict[str, float]]:
    raw: dict[str, dict[str, float]] = {}
    for us_id, team in (understat_teams or {}).items():
        if not isinstance(team, dict):
            continue
        rows = _history_rows(team)
        if not rows:
            continue
        xg, xga, gf, ga, n = _split_pg(rows)
        hxg, hxga, _hgf, _hga, hn = _split_pg(rows, "h")
        axg, axga, _agf, _aga, an = _split_pg(rows, "a")
        raw[str(team.get("id") or us_id)] = {
            "title": team.get("title") or "",
            "n": float(n),
            "hn": float(hn),
            "an": float(an),
            "xg": xg,
            "xga": xga,
            "gf": gf,
            "ga": ga,
            "hxg": hxg,
            "hxga": hxga,
            "axg": axg,
            "axga": axga,
        }
    return raw


def season_team_priors(understat_teams: dict[str, Any] | None) -> dict[str, dict[str, float]]:
    """Last-season xG strengths keyed by canonical club name."""
    raw = _collect_team_raw(understat_teams or {})
    if not raw:
        return {}
    league_xg = max(sum(v["xg"] for v in raw.values()) / len(raw), 0.05)
    league_xga = max(sum(v["xga"] for v in raw.values()) / len(raw), 0.05)
    priors: dict[str, dict[str, float]] = {}
    for v in raw.values():
        xg = max(v["xg"], 0.05)
        priors[canonical_team(str(v["title"]))] = {
            "att": v["xg"] / league_xg,
            "dfn": v["xga"] / league_xga,
            "finish_att": _finishing_ratio(v["gf"], v["xg"]),
            "finish_def": _finishing_ratio(v["ga"], v["xga"]),
            "venue_home": v["hxg"] / xg if v["hn"] else 1.0,
            "venue_away": v["axg"] / xg if v["an"] else 1.0,
        }
    return priors


def team_strengths(understat_teams: dict[str, Any]) -> dict[str, TeamStrength]:
    table = build_team_strengths(understat_teams)
    return table[0]


def build_team_strengths(
    understat_teams: dict[str, Any],
    priors: dict[str, dict[str, float]] | None = None,
) -> tuple[dict[str, TeamStrength], float, float, float]:
    """Venue-neutral attack/defence plus per-club home/away residuals.

    Attack is xG vs league, times finishing (GF/xG). Shrink toward last season
    when we have it, else 1.0. Home/away starts at the league venue factor
    (or last season's split) and blends in this club's current split as n grows.
    """
    raw = _collect_team_raw(understat_teams)
    priors = priors or {}
    if not raw:
        return {}, 1.4, 1.0, 1.0

    avg_xg = sum(v["xg"] for v in raw.values()) / len(raw)
    avg_xga = sum(v["xga"] for v in raw.values()) / len(raw)
    home_rows = [v for v in raw.values() if v["hn"] > 0]
    away_rows = [v for v in raw.values() if v["an"] > 0]
    avg_home_xg = (
        sum(v["hxg"] for v in home_rows) / len(home_rows) if home_rows else avg_xg
    )
    avg_away_xg = (
        sum(v["axg"] for v in away_rows) / len(away_rows) if away_rows else avg_xg
    )
    avg_home_xga = (
        sum(v["hxga"] for v in home_rows) / len(home_rows) if home_rows else avg_xga
    )
    avg_away_xga = (
        sum(v["axga"] for v in away_rows) / len(away_rows) if away_rows else avg_xga
    )
    league_xg = max(avg_xg, 0.05)
    league_xga = max(avg_xga, 0.05)
    ha_home = max(avg_home_xg / league_xg, 0.5)
    ha_away = max(avg_away_xg / league_xg, 0.5)
    def_home_f = max(avg_home_xga / league_xga, 0.5)
    def_away_f = max(avg_away_xga / league_xga, 0.5)

    result: dict[str, TeamStrength] = {}
    for us_id, v in raw.items():
        n = v["n"]
        prior = priors.get(canonical_team(str(v["title"]))) or {}
        att_xg = shrink_mean(
            v["xg"] / league_xg,
            float(prior.get("att") or 1.0),
            n,
            TEAM_STRENGTH_PRIOR_GAMES,
        )
        dfn_xg = shrink_mean(
            v["xga"] / league_xga,
            float(prior.get("dfn") or 1.0),
            n,
            TEAM_STRENGTH_PRIOR_GAMES,
        )
        finish_att = shrink_mean(
            _finishing_ratio(v["gf"], v["xg"]),
            float(prior.get("finish_att") or 1.0),
            n,
            FINISHING_PRIOR_GAMES,
        )
        finish_def = shrink_mean(
            _finishing_ratio(v["ga"], v["xga"]),
            float(prior.get("finish_def") or 1.0),
            n,
            FINISHING_PRIOR_GAMES,
        )
        att = max(att_xg * finish_att, 0.25)
        dfn = max(dfn_xg * finish_def, 0.25)
        xg = max(v["xg"], 0.05)
        raw_home = v["hxg"] / xg if v["hn"] else float(prior.get("venue_home") or ha_home)
        raw_away = v["axg"] / xg if v["an"] else float(prior.get("venue_away") or ha_away)
        venue_home = shrink_mean(
            raw_home,
            float(prior.get("venue_home") or ha_home),
            v["hn"],
            HOME_SPLIT_PRIOR_GAMES,
        )
        venue_away = shrink_mean(
            raw_away,
            float(prior.get("venue_away") or ha_away),
            v["an"],
            HOME_SPLIT_PRIOR_GAMES,
        )
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
            att_home=att * venue_home,
            att_away=att * venue_away,
            def_home=dfn * def_home_f,
            def_away=dfn * def_away_f,
            venue_home=venue_home,
            venue_away=venue_away,
        )
    return result, league_xg, ha_home, ha_away


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
            xg90_raw=xg / per90,
            xa90_raw=xa / per90,
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
        xg90_raw=xg / per90,
        xa90_raw=xa / per90,
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


def position_xgi90(
    fpl_players: list[dict[str, Any]],
    rates_by_id: dict[int, PlayerRates],
    element_type: int,
) -> tuple[float, float]:
    default_xg, default_xa = XGI90_DEFAULT.get(element_type, (0.2, 0.15))
    weighted_xg = 0.0
    weighted_xa = 0.0
    n90_sum = 0.0
    for player in fpl_players:
        if int(player.get("element_type") or 0) != element_type:
            continue
        rates = rates_by_id.get(int(player["id"]))
        if rates is None or rates.minutes < 180:
            continue
        n90 = rates.minutes / 90.0
        raw_xg = rates.xg90_raw or rates.xg90
        raw_xa = rates.xa90_raw or rates.xa90
        weighted_xg += n90 * raw_xg
        weighted_xa += n90 * raw_xa
        n90_sum += n90
    xg90 = shrink_mean(weighted_xg / n90_sum if n90_sum else default_xg, default_xg, n90_sum, POSITION_XGI_PRIOR_90S)
    xa90 = shrink_mean(weighted_xa / n90_sum if n90_sum else default_xa, default_xa, n90_sum, POSITION_XGI_PRIOR_90S)
    return xg90, xa90


def attach_xgi_shrink(
    rates_by_id: dict[int, PlayerRates],
    fpl_players: list[dict[str, Any]],
    season_priors: dict[int, tuple[float, float]] | None = None,
) -> dict[int, PlayerRates]:
    pos = {
        etype: position_xgi90(fpl_players, rates_by_id, etype)
        for etype in (ELEMENT_TYPE_GKP, ELEMENT_TYPE_DEF, ELEMENT_TYPE_MID, ELEMENT_TYPE_FWD)
    }
    season_priors = season_priors or {}
    updated: dict[int, PlayerRates] = {}
    for player in fpl_players:
        eid = int(player["id"])
        rates = rates_by_id.get(eid) or fpl_player_rates(player)
        n90 = rates.minutes / 90.0 if rates.minutes > 0 else 0.0
        pxg, pxa = pos.get(int(player.get("element_type") or 0), XGI90_DEFAULT[ELEMENT_TYPE_MID])
        if eid in season_priors:
            pxg, pxa = season_priors[eid]
        raw_xg = rates.xg90_raw or rates.xg90
        raw_xa = rates.xa90_raw or rates.xa90
        used_prior = eid in season_priors
        if n90 <= 0:
            xg90, xa90 = 0.0, 0.0
        else:
            xg90 = shrink_mean(raw_xg, pxg, n90, XGI_PRIOR_90S)
            xa90 = shrink_mean(raw_xa, pxa, n90, XGI_PRIOR_90S)
        tag = "prior" if used_prior else "shrunk"
        source = rates.source.split("+")[0]
        source = f"{source}+{tag}"
        updated[eid] = replace(
            rates,
            xg90=xg90,
            xa90=xa90,
            xgi90=xg90 + xa90,
            xg90_raw=raw_xg,
            xa90_raw=raw_xa,
            source=source,
        )
    for eid, rates in rates_by_id.items():
        if eid not in updated:
            updated[eid] = rates
    return updated


def build_feature_set(
    bootstrap: dict[str, Any],
    understat_league: dict[str, Any] | None,
    live_defcon: dict[int, list[tuple[int, float]]] | None = None,
    live_matches: dict[int, list[dict[str, float]]] | None = None,
    understat_prior: dict[str, Any] | None = None,
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
    team_priors = season_team_priors((understat_prior or {}).get("teams") or {})
    strengths, league_xg, ha_home, ha_away = (
        build_team_strengths(us_teams, priors=team_priors) if us_teams else ({}, 1.4, 1.0, 1.0)
    )
    us_rates = player_understat_rates(us_players)
    prior_rates = player_understat_rates((understat_prior or {}).get("players") or [])
    prior_ids = map_understat_players(us_players, (understat_prior or {}).get("players") or [])

    teams: dict[int, TeamStrength] = {}
    for fpl_id, us_id in team_map.items():
        if us_id in strengths:
            teams[int(fpl_id)] = strengths[us_id]

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

    season_priors: dict[int, tuple[float, float]] = {}
    for eid, us_id in player_map.items():
        prev_id = prior_ids.get(str(us_id))
        prev = prior_rates.get(prev_id or "")
        if prev is None or prev.minutes < MIN_PRIOR_MINUTES:
            continue
        season_priors[int(eid)] = (prev.xg90_raw or prev.xg90, prev.xa90_raw or prev.xa90)
    players = attach_xgi_shrink(players, fpl_players, season_priors)

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
        league_ha_home=ha_home,
        league_ha_away=ha_away,
        unmatched_players=unmatched,
    )


def fixture_multiplier(
    features: FeatureSet,
    team_id: int,
    opponent_id: int,
    is_home: bool,
) -> float:
    """Venue-neutral attack × opposition defence × this club's shrunk home/away factor.

    The venue factor starts at the league (or last-season) split and moves toward
    this team's own home/away xG ratio as home/away matches accumulate.
    """
    team = features.teams.get(team_id)
    opp = features.teams.get(opponent_id)
    if not team or not opp:
        return 1.0
    venue = team.venue_home if is_home else team.venue_away
    return max(0.25, team.att * opp.dfn * venue)


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
    venue = opp.venue_away if is_home else opp.venue_home
    return max(0.05, league * opp.att * team.dfn * venue)


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
