# Expected points

`fpl_radar.xp.expected_points` has two modes:

1. **Model path** when `ModelContext.features` is set: minutes, xG/xA, CS, GC, DefCon, bonus, saves, cards.
2. **Placeholder** if there are no features: FPL `ep_next`.

Blanks score 0; doubles sum both matches.

**Minutes and attack**

- Expected minutes from Understat `time/games` (else FPL minutes), scaled by availability.
- Raw xG/90 and xA/90 from Understat (unmatched: FPL `expected_goals` / `expected_assists`), then **shrunk toward last season’s xG/90** if that player has ≥180 EPL minutes last year, else the position mean (`k = 8`). See [shrinkage](shrinkage.md).
- Team attack/defence are venue-neutral multipliers, shrunk with `k = 8` toward **last season** (or 1.0 if promoted). Finishing (`GF/xG`) is a separate term with `k = 12`.
- Fixture multiplier = `att` × opposition `dfn` × **that club’s** home/away factor (starts at league HA / last-season split, then follows their own home and away games).
- `E[goals] = shrunk_xG90 × (mins/90) × multiplier` (same for assists).

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

**Saves (GK only)**

1 point per 3 saves (`⌊saves / 3⌋`). Outfield is 0.

Do **not** use `avg_saves / 3`: 2.0 saves/game is usually 0 points. Shrink mean saves toward the GK mean (`k = 6`), convert with Poisson to `E[⌊saves/3⌋]`, and blend with the observed mean save points (and thus how often they actually hit 3 / 6 / 9) from live GWs. Season totals only give the Poisson-from-mean path.

No fixture scaling yet — volume is the keeper’s own average.

Saves xP = `P(play 60+) × saves_e`.

**Cards**

No x-metric. Minutes-adjusted yellow/red rates from live appearances (else season totals), shrunk toward the **position** per-90 mean. Yellows use `k = 6` equivalent 90s; reds use `k = 18` because one sending-off is not a weekly event.

Blend that rate’s `P(card in 90')` with the observed share of appearances that actually had a card. Scale to expected minutes: `1 − (1 − p90)^(mins/90)`. Yellow (−1) dominates; red (−3) is a small extra.

Cards xP = `P(yellow) × −1 + P(red) × −3`.

## Scoring table

Values come from `game_settings` when present, else `fpl_radar.fpl_rules.SCORING_DEFAULTS`.

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

Scoring for the model path is now complete (penalties/own goals still omitted as rare).

## Accuracy gaps (not yet in the model)

Identity is no longer the main leak: club aliases + in-club name matching should cover every Understat player. Remaining xP bias is mostly statistical.

xG/xA/90 and team attack/defence now shrink ([shrinkage](shrinkage.md)). Still open:

- **Minutes** are `time/games` (or FPL minutes), not a playing-time model. `p_play_sixty` is a 30–70 linear heuristic. Doubles reuse the same minutes for both fixtures. News/`chance_of_playing` is only applied when FPL sets it.
- Fixture floor of 0.25 is arbitrary. CS/GC λ is independent Poisson; no scoreline correlation.
- **DefCon, bonus, saves, cards** are not opponent-adjusted. DefCon uses a Poisson per-game λ from a per-90 rate. Bonus is a player prior, not P(finish top 3 in *this* match’s BPS). Saves ignore opposition shot volume. Cards ignore referee/opponent.
- **Horizon** copies the same per-match xP across future GWs (no extra decay beyond the rate priors, no set-piece share, no penalty taker). Own goals / penalty save-miss omitted.
- **Transfers** rank 1-for-1 best-XI delta only: no hits, free transfers, captain 2×, or chip sequences.
