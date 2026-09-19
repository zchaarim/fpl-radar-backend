# Shrinkage (empirical Bayes)

Small samples overfit. A striker with 0.8 xG in 90 minutes is not an 0.80 xG/90 player; a team that scored 8 in 4 games is not a 2.0× attack. FPL Radar **shrinks** noisy rates toward a prior. The same update is used for DefCon, bonus, saves, cards, xG/xA, and team attack/defence.

## The formula

```text
estimate = (n × observed + k × prior) / (n + k)
```

- `n` — how much data this player/team has (games, or 90-minute equivalents).
- `k` — how much the prior is worth, in the same units. After `n = k`, the estimate is halfway between sample and prior.
- `prior` — what we believe before this season’s sample. **Not** a blend of many past years. Order of preference:
  1. That player/club’s **previous EPL season** (Understat xGI and cards), if they have ≥180 minutes.
  2. Else the **current-season** position mean, which itself uses last season’s position rate as its prior. Hardcoded role rates only if last season had nobody with 180+ minutes.
  3. Teams: last-season strength, else **1.0** = this season’s league average.

Promoted clubs and new-to-EPL players have no EPL last season, so they keep (2). We do not scrape the Championship. `sync` pulls last season once; it is cached for a week because that file does not change.

This is the posterior mean of a Normal mean (known variance) and of a Gamma–Poisson rate when the prior is equivalent to `k` observations at `prior`. It is also James–Stein / empirical Bayes in one dimension. It is **not** an arbitrary 50/50 blend of two stats.

At ~10–15 games, team xG strengths are mostly this season (`k = 10` → 50/50 at 10 matches). At 4 games they are still ~30% data.

| Signal | `n` | `k` | Prior |
| --- | --- | --- | --- |
| xG/90, xA/90 | minutes / 90 | 8 | Last EPL season xG/90 if ≥180 minutes, else this-season position mean |
| Team attack / defence | matches | 10 | Last EPL season xG vs league, else **1.0** |
| Finishing (GF/xG, GA/xGA) | matches | 18 | Last season GF/xG, else **1.0** |
| Home/away venue | home or away matches | 10 | Last season split, else league-wide HA |
| Minutes when playing / P(60+|play) | appearances (mins > 0) | 4 | Playing-player position mean |
| P(play) | finished GWs | 4 | Same-cluster mean: regular / rotation / unused |
| DefCon / bonus / saves / yellows | games or 90s | 8 | Position mean (DefCon/bonus/saves have no last-year prior) |
| Reds | 90s | 30 | Position mean (last-season Understat reds/90) |

### Why these `k` values

`k` is how many observations the prior is worth. It is **not** a fitted FPL backtest; it follows how noisy each series is in public soccer analytics.

- **Minutes `k = 4`.** Playing time is a discrete role (nailed / rotation / out). Four GWs usually show it. `k = 6` was still dragging 4×90 keepers off a full game toward the cluster prior.
- **xG/xA `k = 8` 90s.** Shooting rates need ~10–15 90s without a player prior (the usual public result: xG/90 is far more stable than goals/90, but not after two matches). Last season is already the prior mean when they have 180+ EPL minutes, so `k = 8` treats that year as about a third of a season after role-change discount.
- **Position xGI hyperprior `k = 8`.** The position mean itself has a huge `n`, so this barely moves it. It only matters if the live sample is empty.
- **Team xG `k = 10`.** Club xG/game correlates strongly year to year (SPI / xG tables persist). Last season is ~38 matches; treating it as 10 equivalent games is the usual early-season discount. 50/50 at GW10, not GW8.
- **Finishing `k = 18`.** Conversion over/under xG is mostly luck until shot samples are huge. At 4 games a 2:1 GF/xG spike is `4/22 ≈ 18%` of the estimate (was ~25% at `k = 12`).
- **Home/away `k = 10`.** Only 19 home games a year; two home matches should not rewrite HA. Keep 10.
- **DefCon / bonus / saves / yellows `k = 8`.** High week-to-week variance, and DefCon has no last-season FPL history. One haul in one GW is `1/9` of the posterior, not `1/7`.
- **Reds `k = 30`.** League sending-off rates are ~0.01–0.03 per 90. One red in 90 minutes with `k = 18` still implied ~0.06 per 90. `k = 30` keeps a one-off as a small bump.

```text
att_xg = shrink(team_xG_per_game / league_xG, prior=last season or 1.0, n=matches, k=10)
```

## “Regression to 1.0” (teams)

`att` and `dfn` are **multipliers vs the league**. 1.0 means average, 1.2 means 20% more xG (or xGA) than a typical side.

Old code used each club’s 4-game (and 2-game home/away) sample as if it were the true strength. A hot start became `att = 1.6` every week.

**Regression to 1.0** means: if we have no last-season EPL row, treat “league average” as the prior, then let matches pull away from it. If we *do* have last season, shrink toward **that club’s last-season multiplier** instead of 1.0 — City starts as a strong attack, a promoted side still starts at 1.0.

```text
att_xg = shrink(team_xG_per_game / league_xG, prior=1.0, n=matches, k=10)
```

After 4 games a 1.6 raw attack is about `1.17`. After 15 games it is about `1.36`. The ranking of teams is preserved; the **scale** of the gap is damped until the sample can support it.

## Why not 50/50 goals and xG?

Goals and xG are not two equal measurements of the same thing.

- **xG** estimates chance quality. It is a lower-variance predictor of *future* goals than past goals (this is the usual result in public soccer-analytics work: xG now beats GF now for the rest of the season, especially before ~10 games).
- **Goals** = xG + finishing luck + opponent GK + Poisson noise. Over four matches the extra term is mostly luck. True finishing skill exists but needs a lot of shots to see.

A 50/50 mix of GF and xG treats a 4-game goal binge as half of “quality”. That is too much weight on the noisier series.

The model instead:

1. **Quality** from xG vs league, shrunk to 1.0.
2. **Finishing** as `GF / xG`, shrunk to 1.0 with a *larger* `k` (18). At 4 games, a team that outscored xG 2:1 only keeps ~18% of that finishing spike.
3. `att = att_xg × finishing`.

Same story on defence with xGA and goals against. Over 10–15 games finishing is allowed to matter more, which is when over/under-performance is less likely to be noise.

## Home / away

Venue is a **multiplier on top of** venue-neutral `att` / `dfn` (so home advantage is not also baked into those).

1. **League-wide factor** — typical home xG / league xG vs typical away xG / league xG. This is the prior when a club has almost no home (or away) games yet, or no last season.
2. **Last season’s split** for that club, if they were in the EPL — a better prior than the league (some teams really are worse away).
3. **This season’s** home (or away) xG relative to that club’s overall xG, blended in as `n_home` / `n_away` grows (`k = 10`). After ~2 home games the estimate is still mostly the prior; after 10–15 it is mostly that club.

So every home fixture does **not** get the same bump forever. Early on, Arsenal home ≈ league HA (or last year’s Arsenal home). Later, their own home/away record is allowed to differ. The attacking team’s venue factor is applied once (their shot volume at this venue), not also as a defensive HA on the opponent — that was the double-count.

## Players (xG/90, xA/90)

Raw Understat (or FPL fallback) per-90 is shrunk toward **that player’s last-season xG/90** when they have ≥180 EPL minutes, else the **position** mean. The position mean is a minutes-weighted average of players with ≥180 minutes this season, itself shrunk toward **last season’s minutes-weighted xG/xA/90 for that position** (same 180' cutoff). Invented role defaults are only used if last season has no sample.

Players with **0 minutes** stay at 0 — they are not given the position average as if they will start.

`xgi` prints both shrunk `xG90` and `rawGI` so you can see the pull.

## Minutes

Live GWs still **include 0-minute DNPs**, but they only affect **P(play)**. Minutes when selected and P(60+|play) are counted on appearances with minutes > 0, then:

```text
E[minutes] = P(play) × minutes|play
P(60+) = P(play) × P(60+|play)
```

A nailed keeper (4×90) shrinks toward other *playing* keepers (~88–90), not toward the squad of unused third-choice GKs. Unused players shrink P(play) toward other unused players. Rotation is its own cluster so neither group contaminates the other.

No start/sub classifier: we never assume a start is 90 minutes. A 45-minute every week is not half a clean sheet.

