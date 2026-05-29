"""Flask integration tests for Config Hub and Agent API routes — B-18.

Tests /api/upload/config-hub import, agent blueprint auth gates,
and cross-blueprint error matrix.
"""

import base64
import io
import json
import os

# Set AGENT_API_KEY before any web.lib imports so agent_routes._AGENT_KEY
# picks it up at module-import time.
os.environ.setdefault("AGENT_API_KEY", "b18-test-agent-key")

import pytest


# ---------------------------------------------------------------------------
# Config Hub — JSON import
# ---------------------------------------------------------------------------


class TestConfigHubJsonImport:
    """Verify the Config Hub /api/upload/config-hub endpoint with .json files."""

    @pytest.fixture
    def valid_export_json(self, app_client, sample_dat_bytes):
        """Build a valid HMAC-signed JSON export from a fresh DAT session."""
        from web.lib import sessions
        from web.lib.json_utils import export_session_json

        # Upload a DAT file to create a session we can export from
        upload_resp = app_client.post(
            "/api/upload/dat",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        sid = upload_resp.get_json()["session_id"]
        session_data = sessions.get(sid)
        assert session_data is not None, "Session should exist"

        # Build export blocks from the raw bytes
        from web.lib.dat_utils import parse_dat_controllers, extract_groups_from_xml

        controllers = parse_dat_controllers(sample_dat_bytes)
        blocks = []
        for ctrl in controllers:
            cards = extract_groups_from_xml(ctrl["xml_bytes"])
            blocks.append(
                {
                    "name": ctrl["name"],
                    "controller_type": ctrl["controller_type"],
                    "groups": cards,
                }
            )

        secret = b"testing-session-secret"  # TestingConfig.SECRET_KEY
        json_bytes = export_session_json(blocks, session_data, "rearranger", secret)
        return json_bytes

    def test_json_import_returns_redirect(self, app_client, valid_export_json):
        """POST a valid .json export → returns session_id and redirect URL."""
        resp = app_client.post(
            "/api/upload/config-hub",
            data={"file": (io.BytesIO(valid_export_json), "export.json")},
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert "session_id" in payload
        assert "redirect" in payload
        assert payload["redirect"].endswith(f"?session={payload['session_id']}")

    def test_json_import_tampered_returns_400(self, app_client):
        """POST a JSON file with invalid HMAC returns 400."""
        bad_json = json.dumps(
            {"v": 1, "tool": "rearranger", "source_b64": "AAAA", "hmac": "deadbeef"}
        ).encode()
        resp = app_client.post(
            "/api/upload/config-hub",
            data={"file": (io.BytesIO(bad_json), "bad.json")},
        )
        assert resp.status_code == 400

    def test_json_import_invalid_json_returns_400(self, app_client):
        """POST a file that isn't valid JSON returns 400."""
        resp = app_client.post(
            "/api/upload/config-hub",
            data={"file": (io.BytesIO(b"not json"), "bad.json")},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Config Hub — DAT upload
# ---------------------------------------------------------------------------


class TestConfigHubDatUpload:
    """Verify Config Hub handles .dat uploads."""

    def test_dat_upload_returns_applicable_tools(self, app_client, sample_dat_bytes):
        """POST a .dat file → session_id + applicable_tools list."""
        resp = app_client.post(
            "/api/upload/config-hub",
            data={"file": (io.BytesIO(sample_dat_bytes), "test.dat")},
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert "session_id" in payload
        assert "applicable_tools" in payload
        assert "blocks" in payload
        assert "rearranger" in payload["applicable_tools"]

    def test_dat_upload_no_file_returns_400(self, app_client):
        """Config Hub POST without a file returns 400."""
        resp = app_client.post("/api/upload/config-hub")
        assert resp.status_code == 400

    def test_dat_upload_non_zip_returns_400(self, app_client):
        """Config Hub POST with non-ZIP .dat returns 400."""
        resp = app_client.post(
            "/api/upload/config-hub",
            data={"file": (io.BytesIO(b"not a zip"), "bad.dat")},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Config Hub — DSBX upload
# ---------------------------------------------------------------------------


class TestConfigHubDsbxUpload:
    """Verify Config Hub handles .dsbx uploads (error paths, no fixture)."""

    def test_dsbx_upload_non_zip_returns_400(self, app_client):
        """Config Hub POST with non-ZIP .dsbx returns 400."""
        resp = app_client.post(
            "/api/upload/config-hub",
            data={"file": (io.BytesIO(b"not a zip"), "bad.dsbx")},
        )
        assert resp.status_code == 400

    def test_dsbx_upload_wrong_ext_returns_400(self, app_client):
        """Config Hub POST with .txt file returns 400."""
        resp = app_client.post(
            "/api/upload/config-hub",
            data={"file": (io.BytesIO(b"hello"), "notes.txt")},
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Agent blueprint — auth gates
# ---------------------------------------------------------------------------


class TestAgentBlueprintAuth:
    """Verify agent blueprint requires X-Agent-Key for protected endpoints."""

    TEST_KEY = "b18-test-agent-key"

    def test_agent_status_unauthenticated(self, app_client):
        """GET /agent/status works without auth (read-only)."""
        resp = app_client.get("/agent/status")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["ok"] is True

    def test_agent_ping_no_auth_returns_401(self, app_client):
        """POST /agent/ping without X-Agent-Key returns 401."""
        resp = app_client.post("/agent/ping", json={"message": "hello"})
        assert resp.status_code == 401

    def test_agent_ping_wrong_key_returns_401(self, app_client):
        """POST /agent/ping with wrong X-Agent-Key returns 401."""
        resp = app_client.post(
            "/agent/ping",
            json={"message": "hello"},
            headers={"X-Agent-Key": "wrong-key"},
        )
        assert resp.status_code == 401

    def test_agent_ping_correct_key_returns_200(self, app_client):
        """POST /agent/ping with correct X-Agent-Key returns 200."""
        resp = app_client.post(
            "/agent/ping",
            json={"message": "b18-test"},
            headers={"X-Agent-Key": self.TEST_KEY},
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["pong"] is True
        assert payload["echo"] == "b18-test"


# ---------------------------------------------------------------------------
# Generic error matrix — missing session → 404 (page routes tolerate bogus)
# ---------------------------------------------------------------------------


class TestMissingSessionErrors:
    """Page routes with bogus ?session= load fine (just no preload)."""

    def test_dat_rearranger_page_bogus_session(self, app_client):
        resp = app_client.get("/rearranger?session=bogus-id")
        assert resp.status_code == 200

    def test_dat_convert_page_bogus_session(self, app_client):
        resp = app_client.get("/convert?session=bogus-id")
        assert resp.status_code == 200

    def test_dat_split_page_bogus_session(self, app_client):
        resp = app_client.get("/split?session=bogus-id")
        assert resp.status_code == 200

    def test_dsbx_page_bogus_session(self, app_client):
        resp = app_client.get("/dsbx-to-dat?session=bogus-id")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 405 on non-API page routes (where Flask's method checking works)
# ---------------------------------------------------------------------------


class TestCrossBlueprintMethodNotAllowed:
    """PUT/DELETE on page routes that only allow GET → 405."""

    def test_put_status_returns_405(self, app_client):
        resp = app_client.put("/status")
        assert resp.status_code == 405

    def test_put_rearranger_page_returns_405(self, app_client):
        resp = app_client.put("/rearranger")
        assert resp.status_code == 405

    def test_delete_convert_page_returns_405(self, app_client):
        resp = app_client.delete("/convert")
        assert resp.status_code == 405

    def test_put_lev_kit_page_returns_405(self, app_client):
        resp = app_client.put("/lev-kit-configurator")
        assert resp.status_code == 405

    def test_put_config_tools_returns_405(self, app_client):
        resp = app_client.put("/config-tools")
        assert resp.status_code == 405


# ---------------------------------------------------------------------------
# Status endpoint
# ---------------------------------------------------------------------------


class TestStatusEndpoint:
    """Verify the /status health-check endpoint."""

    def test_status_returns_ok(self, app_client):
        resp = app_client.get("/status")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["ok"] is True
        assert "env" in payload
