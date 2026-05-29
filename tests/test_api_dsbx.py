"""Flask integration tests for DSBX API routes — B-18.

Fixture gap: no .dsbx fixture exists in the repo (same gap as B-17).
These tests cover error paths only. A follow-up card should add a real
DSBX fixture for full upload-cycle coverage.
"""

import io

import pytest


# ---------------------------------------------------------------------------
# DSBX upload — error paths only (fixture-gapped)
# ---------------------------------------------------------------------------


class TestDsbxUploadErrors:
    """Validate that the DSBX upload endpoint rejects invalid input properly."""

    def test_empty_body_returns_400(self, app_client):
        """Uploading an empty .dsbx file returns HTTP 400 (not a valid ZIP)."""
        resp = app_client.post(
            "/api/upload/dsbx",
            data={"file": (io.BytesIO(b""), "empty.dsbx")},
        )
        assert resp.status_code == 400

    def test_no_file_returns_400(self, app_client):
        """POST without a file returns HTTP 400."""
        resp = app_client.post("/api/upload/dsbx")
        assert resp.status_code == 400

    def test_malformed_bytes_returns_400(self, app_client):
        """Random bytes that aren't a ZIP should return 400."""
        resp = app_client.post(
            "/api/upload/dsbx",
            data={"file": (io.BytesIO(b"not a zip at all"), "bad.dsbx")},
        )
        assert resp.status_code == 400

    def test_oversized_returns_413(self, app_client):
        """Payload > 5 MB returns HTTP 413."""
        big_data = b"\x00" * (5 * 1024 * 1024 + 1)
        resp = app_client.post(
            "/api/upload/dsbx",
            data={"file": (io.BytesIO(big_data), "big.dsbx")},
        )
        assert resp.status_code == 413

    def test_wrong_extension_returns_400(self, app_client):
        """Uploading a .txt file to the DSBX endpoint returns 400."""
        resp = app_client.post(
            "/api/upload/dsbx",
            data={"file": (io.BytesIO(b"hello"), "notes.txt")},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DSBX session get — error paths
# ---------------------------------------------------------------------------


class TestDsbxSessionErrors:
    """Validate error responses for DSBX session endpoints."""

    def test_get_groups_bogus_session_returns_404(self, app_client):
        """GET /api/session/<sid>/groups with nonexistent session returns 404."""
        resp = app_client.get("/api/session/bogus-id/groups")
        assert resp.status_code == 404

    def test_update_groups_bogus_session_returns_404(self, app_client):
        """POST /api/session/<sid>/groups with nonexistent session returns 404."""
        resp = app_client.post(
            "/api/session/bogus-id/groups",
            json={"new_order": [1, 2, 3], "block_index": 0},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DSBX download — error paths
# ---------------------------------------------------------------------------


class TestDsbxDownloadErrors:
    """Validate error responses for DSBX download endpoint."""

    def test_download_bogus_session_returns_404(self, app_client):
        """GET /api/download/dsbx-to-dat/<sid> with nonexistent session → 404."""
        resp = app_client.get("/api/download/dsbx-to-dat/bogus-id")
        assert resp.status_code == 404
