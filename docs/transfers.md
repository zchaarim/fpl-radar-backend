# Transfer ranking

CLI: `fpl-analyser recommend --entry ID --horizon N [--bank 1.2] [--session-cookie ...] [--limit 20]`

Library: `fpl_analyser.transfers.rank_replacements`.

Free transfers are **not** modelled. The output is a ranked list of legal **1-for-1** replacements. The manager decides how many to make.

## Inputs

1. Rebuild the 15-man squad (`load_manager_squad`).
2. Buy price of targets: live `now_cost`.
3. Sell price of `out`: `my_team` when authenticated, else reconstructed (`price_source` on each option).
4. Bank: `--bank` override if set; else `my-team` bank if logged in; else last-deadline public bank.
5. Horizon `N`: next N gameweeks from bootstrap `events` (`is_current` / `is_next`).

## Legality

Same position; not already in the squad; at most 3 per club after the swap; `selling_price(out) + bank >= now_cost(in)`.

## Ranking

For current squad and each candidate squad, compute **best XI xP each GW** (1 GK, 3–5 DEF, 2–5 MID, 1–3 FWD; bench ignored until Bench Boost). xP is minutes + opponent-adjusted xG/xA + Poisson CS/GC + shrunk DefCon + shrunk bonus (BPS + observed bonus) + GK save points. Cards still to come.

- Primary: `delta = xP_horizon(new) - xP_horizon(current)`
- Secondary: incoming player’s horizon xP (captain flag)

Each option includes out/in names and ids, purchase/sell/now_cost, `price_source`, bank after, delta, incoming xP, per-GW delta series.

2-for-2, hits, chips, and multi-week sequences are out of scope for v1.
