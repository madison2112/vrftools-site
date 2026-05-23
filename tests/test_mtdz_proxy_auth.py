#!/usr/bin/env python3
"""Tests for MTDZ proxy inbound authentication."""
import sys
sys.path.insert(0, "/home/claudecode/vrf-tools/web")

from app import app, MTDZ_PROXY_KEY


def test_proxy_requires_valid_key():
    """Proxy rejects requests without correct X-Proxy-Key."""
    with app.test_client() as c:
        # No header at all → 401
        r = c.get("/api/status")
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"
        assert r.is_json
        assert "proxy key" in r.json["error"].lower()

        # Wrong key → 401
        r = c.get("/api/status", headers={"X-Proxy-Key": "wrong-key"})
        assert r.status_code == 401, f"Expected 401, got {r.status_code}"

        # Correct key → 502 (backend unreachable) — proves auth passed
        r = c.get("/api/status", headers={"X-Proxy-Key": MTDZ_PROXY_KEY})
        assert r.status_code == 502, f"Expected 502 (backend down), got {r.status_code}"


def test_proxy_key_dev_default():
    """Dev default key is non-empty."""
    assert MTDZ_PROXY_KEY
    assert len(MTDZ_PROXY_KEY) > 8


def test_proxy_key_uses_compare_digest():
    """The proxy key comparison should use constant-time compare."""
    import inspect
    source = inspect.getsource(app.view_functions["proxy_mtdz"])
    assert "hmac.compare_digest" in source


if __name__ == "__main__":
    test_proxy_requires_valid_key()
    test_proxy_key_dev_default()
    test_proxy_key_uses_compare_digest()
    print("All MTDZ proxy auth tests passed!")
