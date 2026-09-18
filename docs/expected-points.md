# Expected points

`fpl_analyser.xp.expected_points` now has two modes:

1. **xGI path** when `ModelContext.features` (or `understat_league`) is set: appearance minutes + expected goals/assists. Clean sheets, DefCon, bonus, cards, saves are **not** in yet.
2. **Placeholder** if there are no features: FPL `ep_next` repeated across the horizon (`placeholder=True`).

## Attacking model (current)

For each FPL fixture in the horizon (blanks = 0, doubles sum both):

- Expected minutes from Understat `time/games` (else FPL minutes), scaled by `chance_of_playing_next_round` / injury status.
- Player xG/90 and xA/90 from Understat (`xG`, `xA`, `time`). Unmatched players fall back to FPL `expected_goals` / `expected_assists`.
- Fixture multiplier = player-team attack × opposition defensive weakness, home/away split. Attack and defence blend **actual GF/GA** and **Understat xG/xGA** vs league average.
- `E[goals] = xG90 × (mins/90) × multiplier` (same for assists).
- Points: minutes 1/2 + E[goals] × position goal points + E[assists] × 3.

xGI = xG + xA. Inspect rates with `fpl-analyser xgi`.

## Scoring routes (full list; only minutes/goals/assists used so far)

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

Next: Poisson CS/GC from the same team xG lambdas, then DefCon, saves, bonus.
