from __future__ import annotations

import os
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("FPL_DATA_DIR", Path.cwd() / "data"))
CACHE_DIR = DATA_DIR / "cache"
UNDERSTAT_CACHE_DIR = DATA_DIR / "understat"
MAPPINGS_PATH = DATA_DIR / "mappings" / "overrides.json"

FPL_BASE_URL = "https://fantasy.premierleague.com/api/"
UNDERSTAT_BASE_URL = "https://understat.com/"
UNDERSTAT_LEAGUE = "EPL"
# Understat uses the season start year (2026 => 2026/27).
UNDERSTAT_SEASON = 2026

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (compatible; fpl-radar-backend/0.1; +https://github.com/zchaarim/fpl-radar-backend)"
)
SESSION_COOKIE_ENV = "FPL_SESSION_COOKIE"
API_TOKEN_ENV = "FPL_API_TOKEN"
SYNC_TOKEN_ENV = "FPL_SYNC_TOKEN"
CORS_ORIGINS_ENV = "FPL_CORS_ORIGINS"
DEFAULT_CORS_ORIGINS = (
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
)
DEFAULT_SQUAD_HORIZON = 5

BOOTSTRAP_TTL_SECONDS = 60 * 60
FIXTURES_TTL_SECONDS = 60 * 60
ELEMENT_SUMMARY_TTL_SECONDS = 6 * 60 * 60
ENTRY_TTL_SECONDS = 15 * 60
UNDERSTAT_TTL_SECONDS = 6 * 60 * 60
UNDERSTAT_PRIOR_TTL_SECONDS = 7 * 24 * 60 * 60  # previous season is frozen
AUTH_TTL_SECONDS = 0  # never cache authenticated responses on disk
