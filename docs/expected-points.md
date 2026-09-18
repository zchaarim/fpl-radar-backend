# Expected points

`fpl_analyser.xp.expected_points` has two modes:

1. **Model path** when `ModelContext.features` (or `understat_league`) is set: minutes, xG/xA, clean sheets, goals conceded.
2. **Placeholder** if there are no features: FPL `ep_next` (`placeholder=True`).

DefCon, bonus, saves, and cards are not in yet.

## Per fixture

Blanks score 0; doubles sum both matches.

**Minutes and attack**

- Expected minutes from Understat `time/games` (else FPL minutes), scaled by availability.
- xG/90 and xA/90 from Understat; unmatched players use FPL `expected_goals` / `expected_assists`.
- Attack multiplier = player-team attack × opposition defensive weakness (home/away). Strengths blend actual GF/GA and Understat xG/xGA vs league average.
- `E[goals] = xG90 × (mins/90) × multiplier` (same for assists).

**Clean sheets and goals conceded**

- Goals the player's team concedes ~ Poisson(`λ`), where `λ = league_xG/game × opponent_attack × team_defence_weakness` (home/away).
- `P(CS) = P(play 60+) × e^{-λ}`. FPL only awards CS (and GC) if the player reaches 60 minutes.
- CS points: 4 GK/DEF, 1 MID, 0 FWD.
- GK/DEF GC: `P(play 60+) × E[⌊goals/2⌋] × -1`.
- `P(play 60+)` ramps from 0 at 30 minutes to 1 at 70.

Inspect attacking rates with `fpl-analyser xgi`. Transfer recommend uses this full xP.

## Scoring table

Values come from `game_settings` when present, else `fpl_analyser.fpl_rules.SCORING_DEFAULTS`.

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

Next: DefCon, then saves and bonus.
