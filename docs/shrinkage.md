# Shrinkage (empirical Bayes)

Small samples overfit. A striker with 0.8 xG in 90 minutes is not an 0.80 xG/90 player; a team that scored 8 in 4 games is not a 2.0× attack. FPL Radar **shrinks** noisy rates toward a prior. The same update is used for DefCon, bonus, saves, cards, xG/xA, and team attack/defence.

## The formula

```text
estimate = (n × observed + k × prior) / (n + k)
```

- `n` — how much data this player/team has (games, or 90-minute equivalents).
- `k` — how much the prior is worth, in the same units. After `n = k`, the estimate is halfway between sample and prior.
- `prior` — what we believe before this season’s sample. **Not** a blend of many past years. Order of preference:
  1. That player/club’s **previous EPL season** (Understat `season - 1`), if they have enough minutes / a full-ish campaign.
  2. Else the **current-season** position mean (players) or **1.0** = this season’s league average (teams).
  3. Role defaults only if even the position mean has no data.

Promoted clubs and new-to-EPL players have no EPL last season, so they keep (2). We do not scrape the Championship. `sync` pulls last season once; it is cached for a week because that file does not change.

This is the posterior mean of a Normal mean (known variance) and of a Gamma–Poisson rate when the prior is equivalent to `k` observations at `prior`. It is also James–Stein / empirical Bayes in one dimension. It is **not** an arbitrary 50/50 blend of two stats.

At ~10–15 games, team strengths are mostly data (`k = 8` → about 55–65% observed). At 4 games they are still ~⅓ data.

| Signal | `n` | `k` | Prior |
| --- | --- | --- | --- |
| xG/90, xA/90 | minutes / 90 | 8 | Last EPL season xG/90 if ≥180 minutes, else position mean |
| Team attack / defence | matches | 8 | Last EPL season xG vs league, else **1.0** |
| Finishing (GF/xG, GA/xGA) | matches | 12 | Last season GF/xG, else **1.0** |
| Home/away venue | home or away matches | 10 | Last season split, else league-wide HA |
| DefCon / bonus / saves / yellows | games or 90s | 6 | Position mean (this season; no last-year DefCon yet) |
| Reds | 90s | 18 | Position mean |

## “Regression to 1.0” (teams)

`att` and `dfn` are **multipliers vs the league**. 1.0 means average, 1.2 means 20% more xG (or xGA) than a typical side.

Old code used each club’s 4-game (and 2-game home/away) sample as if it were the true strength. A hot start became `att = 1.6` every week.

**Regression to 1.0** means: if we have no last-season EPL row, treat “league average” as the prior, then let matches pull away from it. If we *do* have last season, shrink toward **that club’s last-season multiplier** instead of 1.0 — City starts as a strong attack, a promoted side still starts at 1.0.

```text
att_xg = shrink(team_xG_per_game / league_xG, prior=1.0, n=matches, k=8)
```

After 4 games a 1.6 raw attack becomes about `1.2`. After 15 games it is about `1.47`. The ranking of teams is preserved; the **scale** of the gap is damped until the sample can support it.

## Why not 50/50 goals and xG?

Goals and xG are not two equal measurements of the same thing.

- **xG** estimates chance quality. It is a lower-variance predictor of *future* goals than past goals (this is the usual result in public soccer-analytics work: xG now beats GF now for the rest of the season, especially before ~10 games).
- **Goals** = xG + finishing luck + opponent GK + Poisson noise. Over four matches the extra term is mostly luck. True finishing skill exists but needs a lot of shots to see.

A 50/50 mix of GF and xG treats a 4-game goal binge as half of “quality”. That is too much weight on the noisier series.

The model instead:

1. **Quality** from xG vs league, shrunk to 1.0.
2. **Finishing** as `GF / xG`, shrunk to 1.0 with a *larger* `k` (12). At 4 games, a team that outscored xG 2:1 only keeps ~25% of that finishing spike.
3. `att = att_xg × finishing`.

Same story on defence with xGA and goals against. Over 10–15 games finishing is allowed to matter more, which is when over/under-performance is less likely to be noise.

## Home / away

Venue is a **multiplier on top of** venue-neutral `att` / `dfn` (so home advantage is not also baked into those).

1. **League-wide factor** — typical home xG / league xG vs typical away xG / league xG. This is the prior when a club has almost no home (or away) games yet, or no last season.
2. **Last season’s split** for that club, if they were in the EPL — a better prior than the league (some teams really are worse away).
3. **This season’s** home (or away) xG relative to that club’s overall xG, blended in as `n_home` / `n_away` grows (`k = 10`). After ~2 home games the estimate is still mostly the prior; after 10–15 it is mostly that club.

So every home fixture does **not** get the same bump forever. Early on, Arsenal home ≈ league HA (or last year’s Arsenal home). Later, their own home/away record is allowed to differ. The attacking team’s venue factor is applied once (their shot volume at this venue), not also as a defensive HA on the opponent — that was the double-count.

## Players (xG/90, xA/90)

Raw Understat (or FPL fallback) per-90 is shrunk toward the **position** mean. The position mean is a minutes-weighted average of players with ≥180 minutes, itself shrunk toward a weak role default so one Haaland does not become “the forward prior”.

Players with **0 minutes** stay at 0 — they are not given the position average as if they will start.

`xgi` prints both shrunk `xG90` and `rawGI` so you can see the pull.
