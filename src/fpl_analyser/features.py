from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

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
