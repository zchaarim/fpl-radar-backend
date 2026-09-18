from __future__ import annotations

from pathlib import Path

from fpl_analyser import config
from fpl_analyser.clients.fpl import FplClient
from fpl_analyser.clients.understat import UnderstatClient
from fpl_analyser.ingest.store import JsonCache


def default_cache() -> JsonCache:
    return JsonCache(config.CACHE_DIR)


def sync_fpl(client: FplClient | None = None) -> dict:
    client = client or FplClient(cache=default_cache())
    bootstrap = client.bootstrap_static()
    fixtures = client.fixtures()
    status = client.event_status()
    notes = client.set_piece_notes()
    return {
        "players": len(bootstrap.get("elements") or []),
        "teams": len(bootstrap.get("teams") or []),
        "fixtures": len(fixtures),
        "event_status": status,
        "set_piece_teams": len((notes.get("teams") if isinstance(notes, dict) else None) or notes or []),
    }


def sync_understat(
    client: UnderstatClient | None = None,
    league: str = config.UNDERSTAT_LEAGUE,
    season: int = config.UNDERSTAT_SEASON,
) -> dict:
    cache = JsonCache(Path(config.UNDERSTAT_CACHE_DIR))
    client = client or UnderstatClient(cache=cache)
    data = client.get_league_data(league=league, season=season)
    teams = data.get("teams") or {}
    players = data.get("players") or []
    dates = data.get("dates") or []
    return {
        "teams": len(teams) if not isinstance(teams, list) else len(teams),
        "players": len(players),
        "dates": len(dates),
    }
