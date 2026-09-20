# Expected points

`fpl_radar.xp.expected_points` has two modes:

1. **Model path** when `ModelContext.features` is set: minutes, xG/xA, CS, GC, DefCon, bonus, saves, cards.
2. **Placeholder** if there are no features: FPL `ep_next`.

Blanks score 0; doubles sum both matches.

**Minutes and attack**

- Minutes come from live GW appearances, **including 0-minute blanks**. We do not treat a start as 90 minutes and we do not classify start vs sub (45' is 45' either way).
- Split **whether they play** from **how long they play when they do**:
  - **Minutes|play** and **P(60+|play)** are averaged only over appearances with minutes > 0 (so unused keepers do not pull a nailed GK toward 70'). They shrink toward other players in the same **duration role**: starter (mean minutes when playing ≥ 60') vs cameo. The cluster prior is worth `k = 4` **players**, not hundreds of pooled appearances.
  - **P(play)** shrinks toward other players in the same cluster: regular (≥60% of GWs), rotation, or unused.
  - **E[minutes] = P(play) × minutes|play**; **P(60+) = P(play) × P(60+|play)**.
- Both pieces shrink with `k = 4`. Injury/doubt is **not** baked into horizon minutes (`chance_of_playing_next_round` would zero every GW). Recommendations show FPL yellow/red flags instead. A player who always plays 45 has ~45 E[minutes] and low P(60+), so they do **not** get CS points.
- Raw xG/90 and xA/90 from Understat (unmatched: FPL `expected_goals` / `expected_assists`), then **shrunk toward last season’s xG/90** if that player has ≥180 EPL minutes last year, else the position mean (`k = 8`). The position hyperprior is last season’s minutes-weighted xGI/90 by FPL position. See [shrinkage](shrinkage.md).
- Team attack/defence are venue-neutral multipliers, shrunk with `k = 10` toward **last season** (or 1.0 if promoted). Finishing (`GF/xG`) is a separate term with `k = 18`.
- Fixture multiplier for **player** xG/xA = opposition `dfn` × **that club’s** home/away factor. Own-team `att` is not applied again (player xG/90 already includes it). CS/GC still use full team λ = `league × opp.att × team.dfn × venue`.
- `E[goals] = shrunk_xG90 × (mins/90) × multiplier` (same for assists).

**Clean sheets and goals conceded**

- Conceded goals ~ Poisson(`λ`) with `λ = league_xG/game × opponent_attack × team_defence_weakness`.
- CS/GC require 60+ minutes. CS: 4 GK/DEF, 1 MID, 0 FWD. GC: GK/DEF `-⌊goals/2⌋`.

**DefCon**

Outfield only. DEF need 10 CBIT; MID/FWD need 12 CBIRT; 2 points, once per match.

`P(hit)` is **not** raw hit rate. It shrinks:

1. Own mean actions/90 (and live-game mean) toward the **position** mean (`k = 8` games).
2. Convert that shrunk mean to `P(actions ≥ threshold)` with Poisson — 9/10 is not 2 points.
3. Blend that with the **observed** 60+ minute hit frequency, again with `k = 8`.

So 1/1 hits does not become 2.0 xP; 16/20 with a high average stays high. GWs come from `event/{gw}/live/` (finished weeks only). If live stats are missing, Poisson-from-mean vs the position prior is used.

DefCon xP = `P(play 60+) × P(hit) × 2`.

**Bonus**

Match bonus (0–3) from BPS rank. Two signals, both shrunk with `k = 8`:

1. **BPS level** — mean BPS per 45+ minute appearance (live `event/{gw}/live/` when present, else season `bps / starts`). Shrink toward the **position** mean, then map BPS → `E[bonus]` with the empirical live curve once there are enough BPS buckets; otherwise a rank heuristic.
2. **Observed bonus** — mean bonus points per those appearances (live, else season `bonus / starts`).

`bonus_e` blends those. A single 3-bonus GW does not become 3.0 xP. High average BPS with few actual bonus hauls still scores some expected bonus.

Bonus xP = `P(play 60+) × bonus_e`.

**Saves (GK only)**

1 point per 3 saves (`⌊saves / 3⌋`). Outfield is 0.

Do **not** use `avg_saves / 3`: 2.0 saves/game is usually 0 points. Shrink mean saves toward the GK mean (`k = 8`), convert with Poisson to `E[⌊saves/3⌋]`, and blend with the observed mean save points (and thus how often they actually hit 3 / 6 / 9) from live GWs. Season totals only give the Poisson-from-mean path.

No fixture scaling yet — volume is the keeper’s own average.

Saves xP = `P(play 60+) × saves_e`.

**Cards**

No x-metric. Minutes-adjusted yellow/red rates from live appearances (else season totals), shrunk toward the **position** per-90 mean. That position mean uses last season’s Understat yellows/reds among players with ≥180 minutes (same dump as xGI). Yellows use `k = 8` equivalent 90s; reds use `k = 30` because one sending-off is not a weekly event.

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

xG/xA/90, team strengths, and minutes now shrink ([shrinkage](shrinkage.md)). Still open:

- Fixture floor of 0.25 is arbitrary. CS/GC λ is independent Poisson; no scoreline correlation. Doubles still apply the same minutes model to each fixture.
- **DefCon, bonus, saves, cards** are not opponent-adjusted.
- **Set pieces / penalties** are not modelled. The public `set-piece-notes` payload is an empty placeholder; the website notes are messy (multiple names, only when first-choice is off).
- Own goals / penalty save-miss omitted. Horizon copies the same form minutes to every GW; yellow/red flags are listed on recommend instead of zeroing xP.
- **Transfers:** `recommend` is 1-for-1 browse (no hit cost). `plan` subtracts 4 xP per transfer beyond remaining FTs, or rebuilds a 15 for wildcard/free hit. Captain 2× is still omitted.
