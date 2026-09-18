from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any

from fpl_analyser import config


def normalize_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("_", " ").replace("-", " ")
    text = re.sub(r"\b(fc|afc)\b", "", text)
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def load_overrides(path: Path | None = None) -> dict[str, Any]:
    mapping_path = path or config.MAPPINGS_PATH
    if not mapping_path.exists():
        return {"teams": {}, "players": {}}
    return json.loads(mapping_path.read_text(encoding="utf-8"))


def match_teams(
    fpl_teams: list[dict[str, Any]],
    understat_teams: dict[str, Any] | list[dict[str, Any]],
    overrides: dict[str, Any] | None = None,
) -> dict[int, str]:
    """Map FPL team id -> Understat team id or title."""
    overrides = overrides or {}
    team_overrides = overrides.get("teams") or {}
    us_items: list[tuple[str, str]] = []
    if isinstance(understat_teams, dict):
        for key, value in understat_teams.items():
            title = value.get("title") if isinstance(value, dict) else str(value)
            us_id = str(value.get("id", key)) if isinstance(value, dict) else str(key)
            us_items.append((normalize_name(title), us_id))
    else:
        for value in understat_teams:
            title = value.get("title") or value.get("team_title") or ""
            us_items.append((normalize_name(title), str(value.get("id") or title)))

    by_name = {name: us_id for name, us_id in us_items}
    result: dict[int, str] = {}
    for team in fpl_teams:
        fpl_id = int(team["id"])
        name = team.get("name") or ""
        if str(fpl_id) in team_overrides:
            result[fpl_id] = str(team_overrides[str(fpl_id)])
            continue
        key = normalize_name(name)
        if key in by_name:
            result[fpl_id] = by_name[key]
            continue
        short = normalize_name(team.get("short_name") or "")
        if short in by_name:
            result[fpl_id] = by_name[short]
    return result


def match_players(
    fpl_players: list[dict[str, Any]],
    understat_players: list[dict[str, Any]],
    team_map: dict[int, str],
    fpl_teams: list[dict[str, Any]],
    overrides: dict[str, Any] | None = None,
) -> dict[int, str]:
    """Map FPL element id -> Understat player id."""
    overrides = overrides or {}
    player_overrides = overrides.get("players") or {}
    team_names = {int(t["id"]): t.get("name") or "" for t in fpl_teams}

    us_index: dict[tuple[str, str], str] = {}
    us_by_name: dict[str, list[str]] = {}
    for player in understat_players:
        pid = str(player.get("id"))
        name = normalize_name(player.get("player_name") or "")
        team = normalize_name((player.get("team_title") or "").split(",")[-1])
        us_index[(name, team)] = pid
        us_by_name.setdefault(name, []).append(pid)

    result: dict[int, str] = {}
    for player in fpl_players:
        element_id = int(player["id"])
        if str(element_id) in player_overrides:
            result[element_id] = str(player_overrides[str(element_id)])
            continue
        full = normalize_name(
            f"{player.get('first_name') or ''} {player.get('second_name') or ''}"
        )
        web = normalize_name(player.get("web_name") or "")
        team_id = int(player.get("team") or 0)
        team_name = normalize_name(team_names.get(team_id, ""))
        for candidate in (full, web):
            if (candidate, team_name) in us_index:
                result[element_id] = us_index[(candidate, team_name)]
                break
        else:
            matches = us_by_name.get(full) or us_by_name.get(web) or []
            if len(matches) == 1:
                result[element_id] = matches[0]
    return result
