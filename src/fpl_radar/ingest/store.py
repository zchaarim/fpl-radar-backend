from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


class JsonCache:
    """File-backed JSON cache with optional TTL."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _relative_name(self, key: str) -> str:
        safe = key.strip("/").replace("?", "_").replace("&", "_").replace("=", "-")
        safe = safe.replace(":", "_").replace(" ", "_")
        if not safe or "\x00" in safe:
            raise ValueError("invalid cache key")
        rel = f"{safe}.json"
        if any(part in {".", ".."} for part in Path(rel).parts):
            raise ValueError("invalid cache key")
        return rel

    def path_for(self, key: str) -> Path:
        return Path(self._resolved(key))

    def _resolved(self, key: str) -> str:
        # CodeQL py/path-injection: normpath + startswith on the same root used in join.
        root = os.path.realpath(self.root)
        fullpath = os.path.normpath(os.path.join(root, self._relative_name(key)))
        if not fullpath.startswith(root) or not (
            fullpath == root or fullpath.startswith(root + os.sep)
        ):
            raise ValueError("cache path escapes root")
        return fullpath

    def get(self, key: str, ttl_seconds: int | None = None) -> Any | None:
        root = os.path.realpath(self.root)
        fullpath = os.path.normpath(os.path.join(root, self._relative_name(key)))
        if not fullpath.startswith(root):
            raise ValueError("cache path escapes root")
        if not fullpath.startswith(root + os.sep):
            raise ValueError("cache path escapes root")
        if not os.path.exists(fullpath):
            return None
        with open(fullpath, encoding="utf-8") as handle:
            payload = json.load(handle)
        fetched_at = payload.get("fetched_at")
        if ttl_seconds is not None and ttl_seconds > 0 and fetched_at is not None:
            if time.time() - fetched_at > ttl_seconds:
                return None
        return payload.get("data")

    def set(self, key: str, data: Any) -> None:
        root = os.path.realpath(self.root)
        fullpath = os.path.normpath(os.path.join(root, self._relative_name(key)))
        if not fullpath.startswith(root):
            raise ValueError("cache path escapes root")
        if not fullpath.startswith(root + os.sep):
            raise ValueError("cache path escapes root")
        os.makedirs(os.path.dirname(fullpath), exist_ok=True)
        with open(fullpath, "w", encoding="utf-8") as handle:
            json.dump({"fetched_at": time.time(), "data": data}, handle, default=str)
