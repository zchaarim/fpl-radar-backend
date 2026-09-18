from __future__ import annotations

from pathlib import Path

from fpl_radar import config
from fpl_radar.clients.fpl import FplClient
from fpl_radar.clients.understat import UnderstatClient
from fpl_radar.features import build_feature_set
from fpl_radar.identity.match import identity_coverage, load_overrides, match_players, match_teams
from fpl_radar.ingest.store import JsonCache
from fpl_radar.xp.model import ModelContext


def default_cache() -> JsonCache:
    return JsonCache(config.CACHE_DIR)


def understat_cache() -> JsonCache:
    return JsonCache(Path(config.UNDERSTAT_CACHE_DIR))


def sync_fpl(client: FplClient | None = None) -> dict:
    client = client or FplClient(cache=default_cache())
    bootstrap = client.bootstrap_static()
    fixtures = client.fixtures()
    status = client.event_status()
    notes = client.set_piece_notes()
    live_gws = client.finished_event_ids(bootstrap)
    for event_id in live_gws:
        client.event_live(event_id)
    return {
        "players": len(bootstrap.get("elements") or []),
        "teams": len(bootstrap.get("teams") or []),
        "fixtures": len(fixtures),
        "event_status": status,
        "live_gameweeks": len(live_gws),
        "set_piece_teams": len((notes.get("teams") if isinstance(notes, dict) else None) or notes or []),
    }


def sync_understat(
    client: UnderstatClient | None = None,
    league: str = config.UNDERSTAT_LEAGUE,
    season: int = config.UNDERSTAT_SEASON,
) -> dict:
    client = client or UnderstatClient(cache=understat_cache())
    data = client.get_league_data(league=league, season=season)
    teams = data.get("teams") or {}
    players = data.get("players") or []
    dates = data.get("dates") or []
    return {
        "teams": len(teams) if not isinstance(teams, list) else len(teams),
        "players": len(players),
        "dates": len(dates),
    }


def load_understat_league(
    client: UnderstatClient | None = None,
    league: str = config.UNDERSTAT_LEAGUE,
    season: int = config.UNDERSTAT_SEASON,
) -> dict:
    client = client or UnderstatClient(cache=understat_cache())
    return client.get_league_data(league=league, season=season)


def load_model_context(fpl_client: FplClient | None = None) -> ModelContext:
    client = fpl_client or FplClient(cache=default_cache())
    bootstrap = client.bootstrap_static()
    fixtures = client.fixtures()
    understat = load_understat_league()
    overrides = load_overrides()
    team_match = match_teams(bootstrap.get("teams") or [], understat.get("teams") or {}, overrides)
    player_match = match_players(
        bootstrap.get("elements") or [],
        understat.get("players") or [],
        team_match,
        bootstrap.get("teams") or [],
        overrides,
    )
    live = client.live_match_log(bootstrap)
    features = build_feature_set(bootstrap, understat, live_matches=live)
    return ModelContext(
        bootstrap=bootstrap,
        fixtures=fixtures,
        understat_league=understat,
        player_match=player_match,
        team_match=team_match,
        features=features,
    )
