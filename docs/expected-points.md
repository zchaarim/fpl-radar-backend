# Expected points

`fpl_analyser.xp.expected_points` has two modes:

1. **Model path** when `ModelContext.features` is set: minutes, xG/xA, CS, GC, DefCon, bonus.
2. **Placeholder** if there are no features: FPL `ep_next`.

Blanks score 0; doubles sum both matches.

**Minutes and attack**

- Expected minutes from Understat `time/games` (else FPL minutes), scaled by availability.
- xG/90 and xA/90 from Understat; unmatched players use FPL `expected_goals` / `expected_assists`.
- Attack multiplier = player-team attack × opposition defensive weakness (home/away).
- `E[goals] = xG90 × (mins/90) × multiplier` (same for assists).

**Clean sheets and goals conceded**

- Conceded goals ~ Poisson(`λ`) with `λ = league_xG/game × opponent_attack × team_defence_weakness`.
- CS/GC require 60+ minutes. CS: 4 GK/DEF, 1 MID, 0 FWD. GC: GK/DEF `-⌊goals/2⌋`.

**DefCon**

Outfield only. DEF need 10 CBIT; MID/FWD need 12 CBIRT; 2 points, once per match.

`P(hit)` is **not** raw hit rate. It shrinks:

1. Own mean actions/90 (and live-game mean) toward the **position** mean (`k = 6` games).
2. Convert that shrunk mean to `P(actions ≥ threshold)` with Poisson — 9/10 is not 2 points.
3. Blend that with the **observed** 60+ minute hit frequency, again with `k = 6`.

So 1/1 hits does not become 2.0 xP; 16/20 with a high average stays high. GWs come from `event/{gw}/live/` (finished weeks only). If live stats are missing, Poisson-from-mean vs the position prior is used.

DefCon xP = `P(play 60+) × P(hit) × 2`.

**Bonus**

Match bonus (0–3) from BPS rank. Two signals, both shrunk with `k = 6`:

1. **BPS level** — mean BPS per 45+ minute appearance (live `event/{gw}/live/` when present, else season `bps / starts`). Shrink toward the **position** mean, then map BPS → `E[bonus]` with the empirical live curve once there are enough BPS buckets; otherwise a rank heuristic.
2. **Observed bonus** — mean bonus points per those appearances (live, else season `bonus / starts`).

`bonus_e` blends those. A single 3-bonus GW does not become 3.0 xP. High average BPS with few actual bonus hauls still scores some expected bonus.

Bonus xP = `P(play 60+) × bonus_e`.

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

Next: saves and cards.
