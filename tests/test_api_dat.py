"""Flask integration tests for DAT API routes — B-18.

Tests the /api/upload/dat, /api/download/*, and /api/session/* endpoints
using the Flask test client and shared conftest fixtures.
"""

import io

import pytest


# ---------------------------------------------------------------------------
# Upload → rearrange → download cycle
# ---------------------------------------------------------------------------


class TestDatUploadRearrangeDownloadCycle:
    """Happy path: upload a valid .dat, sort groups, download the result."""

    def test_upload_returns_session_id(self, app_client, sample_dat_bytes):
        """POST /api/upload/dat with valid .dat returns session_id and blocks."""
        resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert "session_id" in payload
        assert isinstance(payload["session_id"], str)
        assert len(payload["session_id"]) == 36
        assert "blocks" in payload
        assert isinstance(payload["blocks"], list)

    def test_upload_then_sort_then_download_rearrange(
        self, app_client, sample_dat_bytes
    ):
        """Full cycle: upload → sort → download rearranged .dat."""
        # 1. Upload
        upload_resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        assert upload_resp.status_code == 200
        sid = upload_resp.get_json()["session_id"]

        # 2. Sort groups (valid rearrangement)
        sort_resp = app_client.post(
            f"/api/session/{sid}/sort",
            json={"block_index": 0},
        )
        assert sort_resp.status_code == 200
        assert sort_resp.get_json()["ok"] is True

        # 3. Download rearranged .dat
        dl_resp = app_client.get(f"/api/download/rearrange/{sid}")
        assert dl_resp.status_code == 200
        body = dl_resp.data
        assert len(body) > 0
        # .dat files are ZIP archives — verify PK header
        assert body[:4] == b"PK\x03\x04"

    def test_download_convert(self, app_client, sample_dat_bytes):
        """Upload and download converted .dat."""
        upload_resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        sid = upload_resp.get_json()["session_id"]

        dl_resp = app_client.get(f"/api/download/convert/{sid}")
        assert dl_resp.status_code == 200
        body = dl_resp.data
        assert len(body) > 0
        assert body[:4] == b"PK\x03\x04"

    def test_split_single_controller_returns_400(self, app_client, sample_dat_bytes):
        """Split on a single-controller DAT returns 400 (nothing to split)."""
        upload_resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        sid = upload_resp.get_json()["session_id"]

        dl_resp = app_client.get(f"/api/download/split/{sid}")
        assert dl_resp.status_code == 400

    def test_controller_name_update(self, app_client, sample_dat_bytes):
        """POST /api/session/<sid>/controller-name updates a controller name."""
        upload_resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        sid = upload_resp.get_json()["session_id"]

        resp = app_client.post(
            f"/api/session/{sid}/controller-name",
            json={"block_index": 0, "name": "Updated Ctrl"},
        )
        assert resp.status_code == 200
        assert resp.get_json()["ok"] is True
        assert resp.get_json()["name"] == "Updated Ctrl"

    @pytest.mark.parametrize("export_mode", ["individual", "converted"])
    def test_download_rearrange_export_modes(
        self, app_client, sample_dat_bytes, export_mode
    ):
        """Download rearranged .dat with export=individual and export=converted."""
        upload_resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        sid = upload_resp.get_json()["session_id"]

        dl_resp = app_client.get(
            f"/api/download/rearrange/{sid}",
            query_string={"export": export_mode},
        )
        assert dl_resp.status_code == 200
        body = dl_resp.data
        assert len(body) > 0
        assert body[:4] == b"PK\x03\x04"


# ---------------------------------------------------------------------------
# JSON export endpoint
# ---------------------------------------------------------------------------


class TestDatJsonExport:
    """Verify the /api/export-json endpoint."""

    def test_export_json_returns_json_file(self, app_client, sample_dat_bytes):
        """POST /api/export-json with valid session returns a JSON file."""
        upload_resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        sid = upload_resp.get_json()["session_id"]

        resp = app_client.post(
            "/api/export-json",
            json={"session_id": sid, "tool": "rearranger"},
        )
        assert resp.status_code == 200
        assert resp.content_type == "application/json"
        body = resp.data
        assert len(body) > 0
        # Should be valid JSON
        import json
        payload = json.loads(body)
        assert "v" in payload
        assert "hmac" in payload

    def test_export_json_invalid_tool_returns_400(self, app_client, sample_dat_bytes):
        """POST /api/export-json with invalid tool returns 400."""
        upload_resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        sid = upload_resp.get_json()["session_id"]

        resp = app_client.post(
            "/api/export-json",
            json={"session_id": sid, "tool": "bogus-tool"},
        )
        assert resp.status_code == 400

    def test_export_json_bogus_session_returns_404(self, app_client):
        """POST /api/export-json with nonexistent session returns 404."""
        resp = app_client.post(
            "/api/export-json",
            json={"session_id": "bogus-id", "tool": "rearranger"},
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DAT error paths
# ---------------------------------------------------------------------------


class TestDatErrorResponses:
    """Verify error handling for invalid inputs."""

    def test_upload_txt_file_returns_400(self, app_client):
        """Uploading a .txt file (wrong extension) returns HTTP 400."""
        resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(b"hello world"), "notes.txt")},
        )
        assert resp.status_code == 400

    def test_upload_non_zip_dat_returns_400(self, app_client):
        """Uploading bytes that don't start with PK header returns 400."""
        resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(b"not a zip file at all"), "bad.dat")},
        )
        assert resp.status_code == 400

    def test_upload_no_file_returns_400(self, app_client):
        """POST without a file returns HTTP 400."""
        resp = app_client.post("/api/upload/dat")
        assert resp.status_code == 400

    def test_upload_oversized_returns_413(self, app_client):
        """POST with payload > 5 MB returns HTTP 413."""
        big_data = b"\x00" * (5 * 1024 * 1024 + 1)
        resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(big_data), "big.dat")},
        )
        assert resp.status_code == 413

    def test_download_bogus_session_returns_404(self, app_client):
        """GET download with a nonexistent session returns 404."""
        resp = app_client.get("/api/download/rearrange/bogus-id")
        assert resp.status_code == 404

    def test_sort_bogus_session_returns_404(self, app_client):
        """POST sort on a nonexistent session returns 404."""
        resp = app_client.post(
            "/api/session/bogus-id/sort",
            json={"block_index": 0},
        )
        assert resp.status_code == 404

    def test_controller_name_empty_returns_400(self, app_client, sample_dat_bytes):
        """Empty controller name returns 400."""
        upload_resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        sid = upload_resp.get_json()["session_id"]

        resp = app_client.post(
            f"/api/session/{sid}/controller-name",
            json={"block_index": 0, "name": ""},
        )
        assert resp.status_code == 400

    def test_group_name_empty_returns_400(self, app_client, sample_dat_bytes):
        """Empty group tag name returns 400 (slot check runs first on empty DAT,
        but empty tag is still a clear validation error to document)."""
        upload_resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        sid = upload_resp.get_json()["session_id"]

        resp = app_client.post(
            f"/api/session/{sid}/group-name",
            json={"block_index": 0, "slot": 1, "tag": ""},
        )
        # The AE-C400 empty DAT has 0 groups, so slot 1 won't be found (400).
        # This exercises the validation path — the error response is verified.
        assert resp.status_code == 400

    def test_group_name_invalid_slot_returns_400(self, app_client, sample_dat_bytes):
        """Invalid slot number returns 400."""
        upload_resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        sid = upload_resp.get_json()["session_id"]

        resp = app_client.post(
            f"/api/session/{sid}/group-name",
            json={"block_index": 0, "slot": -1, "tag": "BadSlot"},
        )
        assert resp.status_code == 400

    def test_sort_invalid_block_index_returns_400(
        self, app_client, sample_dat_bytes
    ):
        """POST sort with out-of-range block_index returns 400."""
        upload_resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        sid = upload_resp.get_json()["session_id"]

        resp = app_client.post(
            f"/api/session/{sid}/sort",
            json={"block_index": 999},
        )
        assert resp.status_code == 400

    def test_controller_name_invalid_block_index_returns_400(
        self, app_client, sample_dat_bytes
    ):
        """POST controller-name with out-of-range block_index returns 400."""
        upload_resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        sid = upload_resp.get_json()["session_id"]

        resp = app_client.post(
            f"/api/session/{sid}/controller-name",
            json={"block_index": 999, "name": "Bad"},
        )
        assert resp.status_code == 400
