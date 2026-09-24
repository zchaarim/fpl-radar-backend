# HTTP API

First-party JSON API for the FPL Radar site. Ranking still lives in `fpl_radar` (`load_manager_squad`, `expected_points`, `make_plan`, …). Handlers only serialize.

Money is FPL tenths of a million plus display pounds: `{"tenths": 12, "pounds": 1.2}`.

Default squad horizon is **5** GWs (`?horizon=`).

## Run

Leave this process running; `/docs` is served by it, not a static file.

```powershell
cd C:\Users\Carme\Documents\GitHub\fpl-radar-backend
$env:FPL_SYNC_TOKEN = "dev"
python -m pip install -e ".[dev]"
python -m fpl_radar.api
```

You should see `Uvicorn running on http://0.0.0.0:8000`. Then open http://127.0.0.1:8000/docs in the browser. `python -m fpl_radar` is still the CLI and will not start the server.

Equivalent: `python -m uvicorn fpl_radar.api.app:app --port 8000`

CORS origins: `FPL_CORS_ORIGINS` (comma-separated). Default is localhost:3000 and :5173.

## Endpoints

| Method | Path | Auth |
|---|---|---|
| GET | `/v1/status` | none |
| POST | `/v1/sync` | header `X-Sync-Token` = `FPL_SYNC_TOKEN` |
| GET | `/v1/entries/{entry_id}` | none (public reconstruction) |
| GET | `/v1/entries/{entry_id}/squad?horizon=5` | none |

v1 squad is public picks only (estimated sale prices, default FTs). A later in-memory FPL session (option 3) can enrich “mine” without caching JWTs on disk.

`POST /v1/sync` refreshes FPL + Understat and **rebuilds the process-global `ModelContext`**. Set `FPL_SYNC_TOKEN` on Fly. One or two always-on processes; share `FPL_DATA_DIR` (or later Redis) so both see the same JSON cache.

## Later: `plan`

Do not run CP-SAT on a page-load GET. After listings + recommend:

1. **Reuse xP from the warm context.** Today `plan` scores the pool by calling `expected_points` per player. At context refresh, fill a player×GW matrix once; the solver only adds integers.
2. **Keep the 5s cap**, maybe shrink `PLAN_POOL_PER_POSITION` for the API default.
3. **`POST /v1/entries/{id}/plans`** that either waits (timeout ~8s, one worker) or returns **202** + `job_id` with `GET /v1/jobs/{id}` if we see overlapping wildcard solves.

Fly.io: web process + optional worker, not scale-to-zero, so OR-Tools and `ModelContext` stay warm.
