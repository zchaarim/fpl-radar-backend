from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class JsonCache:
    """File-backed JSON cache with optional TTL."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        safe = key.strip("/").replace("?", "_").replace("&", "_").replace("=", "-")
        safe = safe.replace(":", "_").replace(" ", "_")
        return self.root / f"{safe}.json"

    def get(self, key: str, ttl_seconds: int | None = None) -> Any | None:
        path = self.path_for(key)
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = payload.get("fetched_at")
        if ttl_seconds is not None and ttl_seconds > 0 and fetched_at is not None:
            if time.time() - fetched_at > ttl_seconds:
                return None
        return payload.get("data")

    def set(self, key: str, data: Any) -> None:
        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"fetched_at": time.time(), "data": data}, default=str),
            encoding="utf-8",
        )
