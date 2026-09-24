# FPL Radar backend

Ranking And Differential Analysis of Replacements. This repo is **`fpl-radar-backend`**: the Python service behind FPL Radar. Today that is a CLI. The same library (`fpl_radar`) will later expose an HTTP API for a separate front-end site — keep ingest, xP, squad, and transfer ranking free of CLI-only assumptions.

Python backend for Fantasy Premier League: ingest public FPL + Understat xGI, reconstruct a manager’s squad, and rank 1-for-1 transfers. xP uses minutes, opponent-adjusted xG/xA, Poisson CS/GC, shrunk DefCon, bonus, GK saves, and yellow/red rates.

## Setup

Python 3.11+

```text
python -m pip install -e ".[dev]"
python -m fpl_radar sync
```

## Commands

```text
python -m fpl_radar sync
python -m fpl_radar xgi --limit 10 --min-minutes 200
python -m fpl_radar xp --horizon 6 --limit 10
python -m fpl_radar squad --entry 123456 --horizon 6
python -m fpl_radar recommend --entry 123456 --horizon 6 --limit 10 --remove-player Haaland
python -m fpl_radar plan --entry 123456 --horizon 6 --transfers 3 --remove-player Haaland --remove-player Salah
python -m fpl_radar plan --entry 123456 --chip wildcard --horizon 6
$env:FPL_SYNC_TOKEN = "dev"
python -m fpl_radar.api
```

With the API process running: Swagger http://127.0.0.1:8000/docs , ReDoc http://127.0.0.1:8000/redoc , spec http://127.0.0.1:8000/openapi.json . How to run, click through, and pytest: [docs/api.md](docs/api.md).

The install also provides the `fpl-radar-backend` console script.

Optional exact sale prices (your team only). FPL no longer authenticates `/me/` with cookies. In DevTools, open the **same** `api/me/` request, then **Request headers** → `x-api-authorization`. Copy the JWT (with or without the `Bearer ` prefix):

```powershell
Remove-Item Env:FPL_SESSION_COOKIE -ErrorAction SilentlyContinue
$env:FPL_API_TOKEN = "eyJ..."
python -m fpl_radar squad --entry 123456
```

Or `--api-token eyJ...`. Tokens expire after a few hours. Guest cookies (`pl_guest_id`, `cf_clearance`) are ignored. Cache directory defaults to `./data` (override with `FPL_DATA_DIR`).

## Front-end later

A website will call this backend over HTTP (`docs/api.md`). Do not put ranking logic in argparse or FastAPI handlers. The CLI and API should stay thin wrappers around `load_manager_squad`, `expected_points`, `rank_horizon_xp`, `rank_replacements`, and `make_plan`. `squad` prints each owned player’s horizon xP and xGI/90. `--limit` is **per position** (GKP, DEF, MID, FWD). `plan` returns one hit-aware transfer set or a wildcard/free-hit 15. Auth is still optional and never cached. The front-end will live in a different repo.

## Docs

- [HTTP API](docs/api.md)
- [FPL API catalog](docs/fpl-api.md)
- [Understat scraper](docs/understat.md)
- [Expected points model](docs/expected-points.md)
- [Shrinkage / empirical Bayes](docs/shrinkage.md)
- [Transfer ranking](docs/transfers.md)

Name collisions between FPL and Understat go in [data/mappings/overrides.json](data/mappings/overrides.json).
