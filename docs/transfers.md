# Transfer ranking

CLI:

```text
fpl-radar-backend recommend --entry ID --horizon N [--limit 10] [--remove-player NAME]
fpl-radar-backend plan --entry ID --horizon N --transfers 3 [--remove-player NAME ...]
fpl-radar-backend plan --entry ID --horizon N --chip wildcard
fpl-radar-backend plan --entry ID --chip freehit
```

`--limit` on **recommend** is per position: 10 GKP 1-for-1s, 10 DEF, etc.

**recommend** is a browse list of legal 1-for-1s. **plan** returns one squad: at most K transfers (hits included) or a wildcard/free-hit 15.

Library: `rank_replacements`, `make_plan` / `plan_transfers` / `plan_chip`. Player tables: `rank_horizon_xp`, `rank_xgi_rates`.

## Inputs

1. Rebuild the 15-man squad (`load_manager_squad`).
2. Buy price of targets: live `now_cost`.
3. Sell price of `out`: `my_team` when authenticated, else reconstructed (`price_source` on each option).
4. Bank: `--bank` override if set; else `my-team` bank if logged in; else last-deadline public bank.
5. Horizon `N`: next N gameweeks from bootstrap `events` (`is_current` / `is_next`). Free hit forces N = 1.
6. Free transfers: `my-team.transfers.limit − made` when authenticated; else **1**; `--ft` overrides.

## recommend (1-for-1)

Same position; not already in the squad; at most 3 per club after the swap; `selling_price(out) + bank >= now_cost(in)`.

For current squad and each candidate squad, compute **best XI xP each GW** (1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD; bench ignored until Bench Boost).

- Primary: `delta = xP_horizon(new) - xP_horizon(current)`
- Secondary: incoming player’s horizon xP

Hits are **not** subtracted here — the list is for browsing.

`--remove-player` (id or `web_name`, once) keeps only 1-for-1s that transfer that squad player out.

## plan (at most K, or a chip)

CP-SAT (OR-Tools) on a pruned pool (current 15 + top xP / value / cheap players per position).

Objective is the same best-XI horizon sum. Transfer mode:

```text
delta_xi  = xi_horizon(new) - xi_horizon(current)
hits      = max(0, n_transfers - free_transfers)
delta_net = delta_xi - 4 * hits
```

`n_transfers ≤ K` (default 3). Fewer moves win if hits eat the gain. An 8 xP XI gain that needs one hit is **+4** net. Budget is net cash: `bank + sells ≥ buys`. Moves are printed cash-positive first so the sequence never goes negative. Squad shape stays 2-5-5-3 (same-position swaps). Repeat `--remove-player` to force those squad players out; K must be at least that many.

Wildcard / free hit: rebuild any legal 2-5-5-3 15 from `bank + sum(selling prices)`, max 3 per club, no hits. Free hit uses a 1 GW horizon.

Captain 2×, Bench Boost, and multi-week transfer *sequences* are still out of scope.
