"""Flask integration tests for LEV Kit API routes — B-18.

Tests the blank-session → update → download PDF cycle, plus error paths
for the LEV Kit configurator API endpoints.
"""

import io

import pytest


# ---------------------------------------------------------------------------
# Blank session → update → download PDF cycle
# ---------------------------------------------------------------------------


class TestLevKitSessionCycle:
    """Happy path: create blank session, update, download PDF."""

    def test_blank_session_returns_session_id(self, app_client):
        """POST /api/session/lev-kit-blank returns a session_id."""
        resp = app_client.post("/api/session/lev-kit-blank")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert "session_id" in payload
        assert isinstance(payload["session_id"], str)
        assert len(payload["session_id"]) == 36

    def test_blank_to_update_to_download_pdf(self, app_client):
        """Full cycle: blank → update → download PDF."""
        # 1. Create blank session
        blank_resp = app_client.post("/api/session/lev-kit-blank")
        assert blank_resp.status_code == 200
        sid = blank_resp.get_json()["session_id"]

        # 2. Update session with a unit + metadata
        update_resp = app_client.post(
            f"/api/session/{sid}/lev-kit-update",
            json={
                "project_name": "Test Project",
                "voltage": "208",
                "layout": "horizontal",
                "refrigerant_selection": "ah002",
                "units": [
                    {
                        "tag": "Unit-1",
                        "capacity": 0,
                        "control_mode": "discharge",
                        "controller_type": "PAC-AH002",
                    }
                ],
            },
        )
        assert update_resp.status_code == 200
        assert update_resp.get_json()["ok"] is True

        # 3. Download PDF
        dl_resp = app_client.get(f"/api/download/lev-kit/{sid}")
        assert dl_resp.status_code == 200
        assert dl_resp.content_type == "application/pdf"
        body = dl_resp.data
        assert len(body) > 0
        assert body[:4] == b"%PDF"

    def test_blank_session_get(self, app_client):
        """GET /api/session/<sid> returns session data for a LEV Kit session."""
        blank_resp = app_client.post("/api/session/lev-kit-blank")
        sid = blank_resp.get_json()["session_id"]

        resp = app_client.get(f"/api/session/{sid}")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert payload["session_id"] == sid
        assert "project_name" in payload
        assert "units" in payload

    def test_download_pdf_accepts_layout_param(self, app_client):
        """GET /api/download/lev-kit/<sid>?layout=vertical works."""
        blank_resp = app_client.post("/api/session/lev-kit-blank")
        sid = blank_resp.get_json()["session_id"]

        # Update with one unit
        app_client.post(
            f"/api/session/{sid}/lev-kit-update",
            json={
                "project_name": "Layout Test",
                "voltage": "230",
                "layout": "vertical",
                "units": [
                    {
                        "tag": "Unit-A",
                        "capacity": 0,
                        "control_mode": "discharge",
                        "controller_type": "PAC-AH002",
                    }
                ],
            },
        )

        resp = app_client.get(
            f"/api/download/lev-kit/{sid}",
            query_string={"layout": "vertical"},
        )
        assert resp.status_code == 200
        assert resp.content_type == "application/pdf"


# ---------------------------------------------------------------------------
# LEV Kit error paths
# ---------------------------------------------------------------------------


class TestLevKitErrorResponses:
    """Validate error handling for invalid LEV Kit inputs."""

    def test_download_bogus_session_returns_404(self, app_client):
        """GET download with a nonexistent session returns 404."""
        resp = app_client.get("/api/download/lev-kit/bogus-id")
        assert resp.status_code == 404

    def test_update_bogus_session_returns_404(self, app_client):
        """POST update on a nonexistent session returns 404."""
        resp = app_client.post(
            "/api/session/bogus-id/lev-kit-update",
            json={"voltage": "208"},
        )
        assert resp.status_code == 404

    def test_update_invalid_voltage_returns_400(self, app_client):
        """POST update with invalid voltage returns 400."""
        blank_resp = app_client.post("/api/session/lev-kit-blank")
        sid = blank_resp.get_json()["session_id"]

        resp = app_client.post(
            f"/api/session/{sid}/lev-kit-update",
            json={"voltage": "999"},
        )
        assert resp.status_code == 400

    def test_update_invalid_layout_returns_400(self, app_client):
        """POST update with invalid layout returns 400."""
        blank_resp = app_client.post("/api/session/lev-kit-blank")
        sid = blank_resp.get_json()["session_id"]

        resp = app_client.post(
            f"/api/session/{sid}/lev-kit-update",
            json={"layout": "diagonal"},
        )
        assert resp.status_code == 400

    def test_update_invalid_capacity_returns_400(self, app_client):
        """POST update with capacity out of range returns 400."""
        blank_resp = app_client.post("/api/session/lev-kit-blank")
        sid = blank_resp.get_json()["session_id"]

        resp = app_client.post(
            f"/api/session/{sid}/lev-kit-update",
            json={
                "units": [
                    {
                        "tag": "X",
                        "capacity": 999,
                        "control_mode": "discharge",
                    }
                ],
            },
        )
        assert resp.status_code == 400

    def test_update_invalid_control_mode_returns_400(self, app_client):
        """POST update with invalid control_mode returns 400."""
        blank_resp = app_client.post("/api/session/lev-kit-blank")
        sid = blank_resp.get_json()["session_id"]

        resp = app_client.post(
            f"/api/session/{sid}/lev-kit-update",
            json={
                "units": [
                    {
                        "tag": "X",
                        "capacity": 0,
                        "control_mode": "nonsense",
                    }
                ],
            },
        )
        assert resp.status_code == 400

    def test_download_pdf_invalid_layout_param_returns_400(self, app_client):
        """GET download with invalid layout query arg returns 400."""
        blank_resp = app_client.post("/api/session/lev-kit-blank")
        sid = blank_resp.get_json()["session_id"]

        resp = app_client.get(
            f"/api/download/lev-kit/{sid}",
            query_string={"layout": "curved"},
        )
        assert resp.status_code == 400

    def test_get_session_bogus_returns_404(self, app_client):
        """GET /api/session/<sid> with nonexistent session returns 404."""
        resp = app_client.get("/api/session/bogus-id")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# LEV Kit static data endpoint
# ---------------------------------------------------------------------------


class TestLevKitConfigData:
    """Verify the config-data endpoint returns expected structure."""

    def test_config_data_returns_200(self, app_client):
        """GET /api/lev-kit/config-data returns valid JSON."""
        resp = app_client.get("/api/lev-kit/config-data")
        assert resp.status_code == 200
        payload = resp.get_json()
        assert "capacityOptions" in payload
        assert "thermoOptions" in payload
        assert "controllers" in payload
        assert "PAC-AH001" in payload["controllers"]
        assert "PAC-AH002" in payload["controllers"]


# ---------------------------------------------------------------------------
# LEV Kit compute-switches endpoint
# ---------------------------------------------------------------------------


class TestLevKitComputeSwitches:
    """Verify the stateless switch-calculator endpoint."""

    def test_compute_switches_defaults(self, app_client):
        """POST /api/lev-kit/compute-switches with minimal body returns switches."""
        resp = app_client.post(
            "/api/lev-kit/compute-switches",
            json={"controllerType": "PAC-AH002"},
        )
        assert resp.status_code == 200
        payload = resp.get_json()
        assert "switches" in payload
        assert "cnrmConnected" in payload

    def test_compute_switches_invalid_controller_returns_400(self, app_client):
        """POST with invalid controllerType returns 400."""
        resp = app_client.post(
            "/api/lev-kit/compute-switches",
            json={"controllerType": "PAC-FAKE"},
        )
        assert resp.status_code == 400
