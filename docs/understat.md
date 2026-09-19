# Understat ingest

Understat has no official API. The site CSV/JSON/XLSX export is the same dataset the tables use. After late 2025 the league page loads that data over AJAX instead of embedding `JSON.parse('\x7B...')` in HTML.

Client: `fpl_radar.clients.understat.UnderstatClient`. Scope: **EPL**. Current season is the sample; **previous season** (`UNDERSTAT_SEASON - 1`) is the shrink prior for returning players and clubs. Season path uses the **start year** (`2026` → 2026/27). Config: `UNDERSTAT_LEAGUE`, `UNDERSTAT_SEASON`.

Do not depend on `understatapi` / `py-understat`; they lag site changes.

## League pull (`get_league_data`)

1. `GET https://understat.com/league/EPL/2026` (session cookies).
2. `GET https://understat.com/getLeagueData/EPL/2026` with `User-Agent` and `X-Requested-With: XMLHttpRequest`.
3. JSON object with:
   - `teams` — `{id, title, history[]}` per club. Each history row is a match: `h_a`, `xG`, `xGA`, `scored`, `missed`, …
   - `players` — `id`, `player_name`, `team_title`, `time`, `games`, `xG`, `xA`, `yellow_cards`, `red_cards`, shots, …
   - `dates` — season fixtures with team-level `xG` and `goals`

That league dump is enough for player xGI/90, last-season card/90 priors, and team attack/defence (including home/away). `getTeamData` is not required for the current model.

`fpl-radar-backend sync` caches the current season (~6h) and last season (~7 days). `xgi` prints shrunk per-90 rates (`src` is `understat+prior` when last year was used). Unmatched names go in `data/mappings/overrides.json`.

If AJAX is not JSON, fall back to decoding embedded `teamsData` / `playersData` / `datesData` from the league HTML (`unicode_escape` then `json.loads`).

Polite delay between requests. Raw responses cache under `data/understat/` (gitignored) via `JsonCache`.

## Later (not required for phase 1 sync)

Same AJAX headers, typical paths used by community clients:

- Team: `getTeamData/{Team_Name}/{season}` (underscore names, e.g. `Manchester_United`)
- Player / match pages still used for shot maps and rosters

## Identity

`fpl_radar.identity.match` maps clubs via canonical aliases (Man Utd / Manchester United, Spurs / Tottenham, Nott'm Forest, Hull City / Hull, …) and players by normalized name **within that club**. Matching tries full name, web name, token subsets (`Alisson Becker` ↔ `Alisson`), unique last names on the club, then a conservative fuzzy ratio. HTML entities (`O&#039;Shea`) and letters that NFKD will not fold (`Ødegaard`) are handled in `normalize_name`. Dual `team_title` values use the last club. Manual fixes: `data/mappings/overrides.json`. Unmatched players use FPL `expected_goals` / `expected_assists` instead of Understat xGI — that fallback is **not** the same metric, so coverage on players with minutes should stay high.
