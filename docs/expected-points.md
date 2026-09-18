# Expected points

Phase 1 implements `fpl_analyser.xp.expected_points(player_id, event_ids, context) -> PlayerXp` as a **placeholder**: it repeats FPL `elements[].ep_next` across the horizon and sets `placeholder=True`. Replace the body of `xp/model.py` without changing callers.

## Scoring routes

Use `bootstrap-static` `game_settings` when present, else `fpl_analyser.fpl_rules.SCORING_DEFAULTS`.

| Event | Points (typical) |
| --- | --- |
| 1–59 minutes | 1 |
| 60+ minutes | 2 |
| Goal (GK / DEF / MID / FWD) | 10 / 6 / 5 / 4 |
| Assist | 3 |
| Clean sheet (GK, DEF / MID / FWD) | 4 / 1 / 0 |
| Every 2 goals conceded (GK, DEF) | -1 |
| Every 3 saves (GK) | 1 |
| Penalty save / miss | 5 / -2 |
| Yellow / red | -1 / -3 |
| Own goal | -2 |
| Bonus (BPS rank 1–3 in the match) | 1–3 |
| Defensive contribution (DEF: 10 CBIT; MID/FWD: 12 CBIRT) | 2, capped per match |

DefCon (from 2025/26) is independent of clean sheets. 2026/27 BPS weights for CBI/saves changed; bonus probability should follow current BPS, not last season’s.

## Intended model (not implemented yet)

For each player and fixture in the horizon:

`xP = E[minutes points] + Σ P(event) × points(event)`

- **Team strength:** blend actual GF/GA and Understat xG/xGA, split home/away, opponent-adjust (attack vs opposition defence).
- **Player rates:** FPL per-90 (goals, assists, xG, xA, DefCon, saves, BPS/bonus) × expected minutes.
- **Independence:** treat scoring events as independent given minutes and team totals unless a later module models covariance (e.g. goals vs CS).
- **Counts:** Poisson (or similar) for team goals → CS and player goals/assists; threshold model for DefCon; saves from opponent shot/xG volume.

`PlayerXp` already has `per_event`, `horizon_sum`, and a `breakdown` dict keyed by scoring event for that swap-in.

`ModelContext` carries bootstrap, optional Understat league dump, and FPL↔Understat id maps.
