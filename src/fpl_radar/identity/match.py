from __future__ import annotations

import html
import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from fpl_radar import config

# FPL short labels vs Understat titles (canonical form is the value).
TEAM_ALIASES: dict[str, str] = {
    "man city": "manchester city",
    "manchester city": "manchester city",
    "man utd": "manchester united",
    "manchester united": "manchester united",
    "spurs": "tottenham",
    "tottenham": "tottenham",
    "tottenham hotspur": "tottenham",
    "newcastle": "newcastle united",
    "newcastle united": "newcastle united",
    "nottm forest": "nottingham forest",
    "nottingham forest": "nottingham forest",
    "hull": "hull",
    "hull city": "hull",
    "ipswich": "ipswich",
    "ipswich town": "ipswich",
    "coventry": "coventry",
    "coventry city": "coventry",
    "brighton": "brighton",
    "brighton and hove albion": "brighton",
    "leeds": "leeds",
    "leeds united": "leeds",
    "wolves": "wolverhampton wanderers",
    "wolverhampton": "wolverhampton wanderers",
    "wolverhampton wanderers": "wolverhampton wanderers",
}

# Letters NFKD will not fold into ASCII (Ø stays Ø, then our alnum strip would drop it).
_TRANSLIT = str.maketrans(
    {
        "ø": "o",
        "Ø": "o",
        "đ": "d",
        "Đ": "d",
        "ð": "d",
        "Ð": "d",
        "ł": "l",
        "Ł": "l",
        "ß": "ss",
        "æ": "ae",
        "Æ": "ae",
        "œ": "oe",
        "Œ": "oe",
        "þ": "th",
        "Þ": "th",
    }
)

_FUZZY_RATIO = 0.86
_FUZZY_GAP = 0.05


def normalize_name(value: str) -> str:
    text = html.unescape(value or "")
    text = text.translate(_TRANSLIT)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("_", " ").replace("-", " ")
    text = re.sub(r"\b(fc|afc)\b", "", text)
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def canonical_team(value: str) -> str:
    key = normalize_name(value)
    return TEAM_ALIASES.get(key, key)


def name_tokens(value: str) -> tuple[str, ...]:
    return tuple(part for part in normalize_name(value).split() if part)


def load_overrides(path: Path | None = None) -> dict[str, Any]:
    mapping_path = path or config.MAPPINGS_PATH
    if not mapping_path.exists():
        return {"teams": {}, "players": {}}
    return json.loads(mapping_path.read_text(encoding="utf-8"))


def _understat_team_items(understat_teams: dict[str, Any] | list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """(canonical title, us_id, raw title)."""
    items: list[tuple[str, str, str]] = []
    if isinstance(understat_teams, dict):
        rows = understat_teams.values()
    else:
        rows = understat_teams
    for value in rows:
        if isinstance(value, dict):
            title = str(value.get("title") or value.get("team_title") or "")
            us_id = str(value.get("id") or title)
        else:
            title = str(value)
            us_id = str(value)
        items.append((canonical_team(title), us_id, title))
    return items


def match_teams(
    fpl_teams: list[dict[str, Any]],
    understat_teams: dict[str, Any] | list[dict[str, Any]],
    overrides: dict[str, Any] | None = None,
) -> dict[int, str]:
    """Map FPL team id -> Understat team id or title."""
    overrides = overrides or {}
    team_overrides = overrides.get("teams") or {}
    us_items = _understat_team_items(understat_teams)
    by_canonical = {canon: us_id for canon, us_id, _title in us_items}

    result: dict[int, str] = {}
    for team in fpl_teams:
        fpl_id = int(team["id"])
        if str(fpl_id) in team_overrides:
            result[fpl_id] = str(team_overrides[str(fpl_id)])
            continue
        for raw in (team.get("name") or "", team.get("short_name") or ""):
            key = canonical_team(raw)
            if key in by_canonical:
                result[fpl_id] = by_canonical[key]
                break
    return result


def _current_us_team(team_title: str) -> str:
    last = (team_title or "").split(",")[-1].strip()
    return canonical_team(last)


def _fpl_name_variants(player: dict[str, Any]) -> list[str]:
    first = player.get("first_name") or ""
    second = player.get("second_name") or ""
    web = player.get("web_name") or ""
    first_tokens = name_tokens(first)
    second_tokens = name_tokens(second)
    variants = [f"{first} {second}", web, second, first]
    if first_tokens and second_tokens:
        variants.append(f"{first_tokens[0]} {second_tokens[-1]}")
        variants.append(f"{first_tokens[0]} {second_tokens[0]}")
    variants.extend(tok for tok in second_tokens if len(tok) > 2)
    web_tokens = name_tokens(web)
    if web_tokens:
        last = web_tokens[-1]
        first_tok = web_tokens[0]
        if len(last) > 1:
            variants.append(last)
        elif len(first_tok) > 1:
            variants.append(first_tok)
    seen: set[str] = set()
    out: list[str] = []
    for raw in variants:
        key = normalize_name(raw)
        if key and key not in seen:
            seen.add(key)
            out.append(raw)
    return out


def _unique_by(records: list[dict[str, Any]], key_fn) -> dict[str, str | None]:
    buckets: dict[str, list[str]] = {}
    for row in records:
        key = key_fn(row)
        if not key:
            continue
        buckets.setdefault(key, []).append(str(row.get("id")))
    return {key: ids[0] if len(ids) == 1 else None for key, ids in buckets.items()}


def _pick_fuzzy(query: str, records: list[dict[str, Any]]) -> str | None:
    scored: list[tuple[float, str]] = []
    q = normalize_name(query)
    if not q:
        return None
    for row in records:
        name = normalize_name(row.get("player_name") or "")
        if not name:
            continue
        ratio = SequenceMatcher(None, q, name).ratio()
        scored.append((ratio, str(row.get("id"))))
    if not scored:
        return None
    scored.sort(reverse=True)
    best_ratio, best_id = scored[0]
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best_ratio >= _FUZZY_RATIO and best_ratio - second >= _FUZZY_GAP:
        return best_id
    return None


def _token_match(query: str, records: list[dict[str, Any]]) -> str | None:
    q_tokens = set(name_tokens(query))
    if not q_tokens:
        return None
    hits: list[str] = []
    for row in records:
        us_tokens = set(name_tokens(row.get("player_name") or ""))
        if not us_tokens:
            continue
        overlap = q_tokens & us_tokens
        if not overlap:
            continue
        if q_tokens == us_tokens or q_tokens <= us_tokens or us_tokens <= q_tokens:
            hits.append(str(row.get("id")))
    unique = list(dict.fromkeys(hits))
    if len(unique) == 1:
        return unique[0]
    return None


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

    by_team: dict[str, list[dict[str, Any]]] = {}
    us_by_name: dict[str, list[str]] = {}
    us_index: dict[tuple[str, str], str] = {}
    for player in understat_players:
        pid = str(player.get("id"))
        name = normalize_name(player.get("player_name") or "")
        team = _current_us_team(player.get("team_title") or "")
        us_index[(name, team)] = pid
        us_by_name.setdefault(name, []).append(pid)
        by_team.setdefault(team, []).append(player)

    def _nth_token(row: dict[str, Any], index: int) -> str:
        tokens = name_tokens(row.get("player_name") or "")
        if not tokens:
            return ""
        token = tokens[index]
        return token if len(token) > 1 else ""

    last_on_team = {
        team: _unique_by(rows, lambda row, idx=-1: _nth_token(row, idx)) for team, rows in by_team.items()
    }
    first_on_team = {
        team: _unique_by(rows, lambda row, idx=0: _nth_token(row, idx)) for team, rows in by_team.items()
    }

    result: dict[int, str] = {}
    used_us: set[str] = set()
    ordered = sorted(
        fpl_players,
        key=lambda row: -float(row.get("minutes") or 0),
    )
    for player in ordered:
        element_id = int(player["id"])
        if str(element_id) in player_overrides:
            result[element_id] = str(player_overrides[str(element_id)])
            continue
        team_id = int(player.get("team") or 0)
        team_key = canonical_team(team_names.get(team_id, ""))
        club_rows = [row for row in (by_team.get(team_key) or []) if str(row.get("id")) not in used_us]
        matched: str | None = None
        for candidate in _fpl_name_variants(player):
            key = normalize_name(candidate)
            if (key, team_key) in us_index and us_index[(key, team_key)] not in used_us:
                matched = us_index[(key, team_key)]
                break
            token_hit = _token_match(candidate, club_rows)
            if token_hit:
                matched = token_hit
                break
            tokens = name_tokens(candidate)
            if tokens:
                last = tokens[-1]
                first = tokens[0]
                if len(last) > 1:
                    last_id = last_on_team.get(team_key, {}).get(last)
                    if last_id and last_id not in used_us:
                        matched = last_id
                        break
                if len(first) > 1:
                    first_id = first_on_team.get(team_key, {}).get(first)
                    if first_id and first_id not in used_us:
                        matched = first_id
                        break
            fuzzy = _pick_fuzzy(candidate, [row for row in club_rows if str(row.get("id")) not in used_us])
            if fuzzy and fuzzy not in used_us:
                matched = fuzzy
                break
        if matched is None:
            full = normalize_name(f"{player.get('first_name') or ''} {player.get('second_name') or ''}")
            web = normalize_name(player.get("web_name") or "")
            matches = [pid for pid in (us_by_name.get(full) or us_by_name.get(web) or []) if pid not in used_us]
            if len(matches) == 1:
                matched = matches[0]
        if matched and matched not in used_us:
            result[element_id] = matched
            used_us.add(matched)
    _ = team_map
    return result


def identity_coverage(
    fpl_players: list[dict[str, Any]],
    understat_players: list[dict[str, Any]],
    player_map: dict[int, str],
) -> dict[str, int]:
    unmatched_fpl = [p for p in fpl_players if int(p["id"]) not in player_map]
    matched_us = set(player_map.values())
    unmatched_us = [p for p in understat_players if str(p.get("id")) not in matched_us]
    return {
        "fpl_players": len(fpl_players),
        "understat_players": len(understat_players),
        "matched": len(player_map),
        "unmatched_fpl": len(unmatched_fpl),
        "unmatched_fpl_with_minutes": sum(
            1 for p in unmatched_fpl if float(p.get("minutes") or 0) > 0
        ),
        "unmatched_understat": len(unmatched_us),
        "unmatched_understat_with_minutes": sum(
            1 for p in unmatched_us if float(p.get("time") or 0) > 0
        ),
    }
