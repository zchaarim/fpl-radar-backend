from __future__ import annotations

from pathlib import Path

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
