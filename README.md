# FPL analyser

Python backend for Fantasy Premier League transfer analysis: ingest public FPL + Understat data, reconstruct a manager’s squad, and rank 1-for-1 transfers. Expected-points math is stubbed in this phase (`ep_next` as a labelled placeholder).

## Setup

Python 3.11+

```text
python -m pip install -e ".[dev]"
```

## Commands

```text
fpl-analyser sync
fpl-analyser squad --entry 123456
fpl-analyser squad --entry 123456 --bank 1.2
fpl-analyser recommend --entry 123456 --horizon 6 --limit 20
```

Optional exact sale prices (your team only). FPL no longer authenticates `/me/` with cookies. In DevTools, open the **same** `api/me/` request, then **Request headers** → `x-api-authorization`. Copy the JWT (with or without the `Bearer ` prefix):

```powershell
Remove-Item Env:FPL_SESSION_COOKIE -ErrorAction SilentlyContinue
$env:FPL_API_TOKEN = "eyJ..."
python -m fpl_analyser.cli squad --entry 123456
```

Or `--api-token eyJ...`. Tokens expire after a few hours. Guest cookies (`pl_guest_id`, `cf_clearance`) are ignored. Cache directory defaults to `./data` (override with `FPL_DATA_DIR`).

## Docs

- [FPL API catalog](docs/fpl-api.md)
- [Understat scraper](docs/understat.md)
- [Expected points model](docs/expected-points.md)
- [Transfer ranking](docs/transfers.md)

Name collisions between FPL and Understat go in [data/mappings/overrides.json](data/mappings/overrides.json).
