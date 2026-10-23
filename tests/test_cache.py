from __future__ import annotations

from pathlib import Path

import pytest

from fpl_radar.ingest.store import JsonCache


def test_json_cache_roundtrip(tmp_path: Path) -> None:
    cache = JsonCache(tmp_path)
    cache.set("bootstrap-static/", {"ok": True})
    assert cache.get("bootstrap-static/", ttl_seconds=60) == {"ok": True}


def test_json_cache_ttl_expiry(tmp_path: Path, monkeypatch) -> None:
    cache = JsonCache(tmp_path)
    cache.set("x", 1)
    monkeypatch.setattr("fpl_radar.ingest.store.time.time", lambda: 10**12)
    assert cache.get("x", ttl_seconds=1) is None


def test_json_cache_nested_entry_key_stays_under_root(tmp_path: Path) -> None:
    cache = JsonCache(tmp_path)
    cache.set("entry/99/event/2/picks/", {"picks": []})
    assert cache.get("entry/99/event/2/picks/") == {"picks": []}
    stored = cache.path_for("entry/99/event/2/picks/")
    assert stored.resolve().is_relative_to(tmp_path.resolve())


def test_json_cache_rejects_parent_traversal(tmp_path: Path) -> None:
    cache = JsonCache(tmp_path)
    with pytest.raises(ValueError, match="invalid cache key"):
        cache.set("../secret", {"no": True})
    assert list(tmp_path.rglob("*.json")) == []
