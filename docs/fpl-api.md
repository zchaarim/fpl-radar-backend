# FPL public API

Unofficial JSON API used by the official site. Base URL:

`https://fantasy.premierleague.com/api/`

No API key. Most endpoints are unauthenticated. The official web app sets CORS that **blocks browser front-ends**; this backend is fine.

IDs:

- `element` — Premier League player
- `element_type` — position (1 GKP, 2 DEF, 3 MID, 4 FWD)
- `event` — gameweek
- `entry` — FPL manager / team
- `team` — Premier League club (1–20)

Prices are integers in tenths of a million (`105` = £10.5m). `now_cost` on `bootstrap-static` is the **current buy price**, updated when FPL runs overnight price changes.

Client: `fpl_analyser.clients.fpl.FplClient` (public). Auth: `fpl_analyser.clients.auth.FplAuthClient`. Do not send the session cookie on public fetches.

## Implemented

### `bootstrap-static/` — `FplClient.bootstrap_static`

Players (`elements`), clubs (`teams`), gameweeks (`events`), `element_types`, `game_settings`, chips, phases. Cache ~1 hour.

### `fixtures/` and `fixtures/?event={gw}` — `FplClient.fixtures`

Season or single-GW fixtures, FPL difficulty, finished-match stats.

### `element-summary/{element_id}/` — `FplClient.element_summary`

Remaining fixtures, this-season history, previous seasons. Fetch lazily; do not download every player on every `sync`.

### `event/{event_id}/live/` — `FplClient.event_live`

Per-player GW stats and points explainers (minutes, goals, DefCon, BPS, bonus, saves, xG fields when present). `FplClient.live_match_log` stacks finished GWs into per-player minutes / DefCon / BPS / bonus / saves rows for the xP model.

### `event-status/` — `FplClient.event_status`

Whether bonus and league processing have completed for the current GW.

### `entry/{entry_id}/` — `FplClient.entry`

Manager profile, `last_deadline_bank`, `last_deadline_value`, leagues.

### `entry/{entry_id}/history/` — `FplClient.entry_history`

Per-GW points, rank, bank, value; past seasons; chips played.

### `entry/{entry_id}/transfers/` — `FplClient.entry_transfers`

Season transfer list with `element_in_cost` / `element_out_cost`.

### `entry/{entry_id}/event/{event_id}/picks/` — `FplClient.entry_picks`

Published squad, captain, chips for that GW. Available after the deadline; before deadline use last finished GW + current-event transfers.

### `team/set-piece-notes/` — `FplClient.set_piece_notes`

Set-piece taker notes per club (pens / FK / corners) for later xG share.

### Authenticated (optional)

FPL login is PingOne OIDC. Private endpoints expect header `X-API-Authorization: Bearer <access_token>`, not `pl_profile` cookies. Copy `x-api-authorization` from a logged-in `api/me/` or `api/my-team/` request. Env `FPL_API_TOKEN` or CLI `--api-token`. Tokens expire in hours.

Guest Cookie values (`pl_guest_id`, Cloudflare, analytics) are ignored so they do not block the public squad path.

Legacy `pl_profile` cookies still work if present (`FPL_SESSION_COOKIE` / `--session-cookie`).

- `me/` — `FplAuthClient.me` — logged-in manager; `player.entry` must match the requested team id
- `my-team/{entry_id}/` — `FplAuthClient.my_team` — `purchase_price`, `selling_price`, live `transfers.bank`, chips

Mismatch between cookie entry and `--entry` is a hard error. Authenticated payloads are **not** written to `data/cache`.

`transfers-latest/` exists but is unused if `my-team` is available.

## Documented, not wrapped in v1

- `leagues-classic/{league_id}/standings/`
- `leagues-h2h-matches/league/{league_id}/`
- `dream-team/{event_id}/`
- `league/{league_id}/cup-status/`
- `stats/most-valuable-teams/` and similar stats pages
