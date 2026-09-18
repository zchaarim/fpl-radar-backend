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
    "Mozilla/5.0 (compatible; fpl-analyser/0.1; +https://github.com/fpl_bot)"
)
SESSION_COOKIE_ENV = "FPL_SESSION_COOKIE"

BOOTSTRAP_TTL_SECONDS = 60 * 60
FIXTURES_TTL_SECONDS = 60 * 60
ELEMENT_SUMMARY_TTL_SECONDS = 6 * 60 * 60
ENTRY_TTL_SECONDS = 15 * 60
UNDERSTAT_TTL_SECONDS = 6 * 60 * 60
AUTH_TTL_SECONDS = 0  # never cache authenticated responses on disk
