"""Regression tests for the Phase 1 bug fixes (June 2026).

Covers the backend-observable fixes:
  * config-hub .dat upload now carries controller IPs (rearranger empty-IP bug)
  * per-controller DSBX download respects the selected series (no C400/C50 leak
    into a 200-series job, and vice versa)
  * switch-series converts an older AE-200/EW-50 site to AE-C400/EW-C50 in place
  * multi-system output names use "<file> - AE-C400 site" / "- AE-200 site"
"""

import io
import re
import zipfile
import xml.etree.ElementTree as ET

from web.lib.zipcrypto import PASSWORD

_400_MODELS = {"AE-C400A", "EW-C50A"}
_200_MODELS = {"AE-200A", "AE-50A"}


def _first_entry_model(dat_bytes: bytes) -> str:
    """Return the SystemData/@Model of a single-controller .dat's first entry."""
    z = zipfile.ZipFile(io.BytesIO(dat_bytes))
    entries = sorted(e for e in z.namelist() if re.match(r"^\d+(-\d+)*$", e))
    sd = ET.fromstring(z.read(entries[0], pwd=PASSWORD)).find(".//SystemData")
    return sd.get("Model", "")


def _zip_member_models(zip_bytes: bytes) -> list[str]:
    z = zipfile.ZipFile(io.BytesIO(zip_bytes))
    return [_first_entry_model(z.read(n)) for n in z.namelist()]


def _upload_dsbx(client, data: bytes):
    resp = client.post(
        "/api/upload/config-hub",
        data={"file": (io.BytesIO(data), "sample.dsbx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    return resp.get_json()


def _upload_file(client, data, fname, ctype):
    resp = client.post(
        "/api/upload/config-hub",
        data={"file": (io.BytesIO(data), fname)},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    return resp.get_json()


class TestSessionJsonRoundTrip:
    def test_dsbx_switch_survives_json_round_trip(self, app_client, sample_mixed_dsbx_bytes):
        """A site switched to AE-C400 must still be 400-series after export+import
        (this was reverting to AE-200 on re-import)."""
        j = _upload_file(app_client, sample_mixed_dsbx_bytes, "m.dsbx", "dsbx")
        sid = j["session_id"]
        app_client.post(f"/api/session/{sid}/switch-series")

        export = app_client.post("/api/export-json", json={"session_id": sid, "tool": "dsbx-to-dat"})
        assert export.status_code == 200

        ri = _upload_file(app_client, export.data, "m.json", "json")
        sid2 = ri["session_id"]
        dl = app_client.get(f"/api/download/dsbx-to-dat/{sid2}")
        assert dl.status_code == 200
        z = zipfile.ZipFile(io.BytesIO(dl.data))
        models = []
        for n in z.namelist():
            models += [_first_entry_model(z.read(n))]
        assert models and all(m in _400_MODELS for m in models), models

    def test_dat_round_trip_preserves_output(self, app_client, sample_multi_central_dat_bytes):
        j = _upload_file(app_client, sample_multi_central_dat_bytes, "s.dat", "dat")
        sid = j["session_id"]
        orig = app_client.get(f"/api/download/rearrange/{sid}?export=packaged").data

        export = app_client.post("/api/export-json", json={"session_id": sid, "tool": "rearranger"})
        # Readable, not a base64 wall.
        import json as _json
        payload = _json.loads(export.data)
        assert payload["version"] == 2 and "source_b64" not in payload

        ri = _upload_file(app_client, export.data, "s.json", "json")
        rt = app_client.get(f"/api/download/rearrange/{ri['session_id']}?export=packaged").data
        # First-entry model is preserved through the round trip.
        assert _first_entry_model(orig) == _first_entry_model(rt)


class TestConfigHubDatIp:
    def test_dat_upload_populates_ip(self, app_client, sample_multi_central_dat_bytes):
        """Each controller block returned from a .dat upload carries its IP."""
        resp = app_client.post(
            "/api/upload/config-hub",
            data={"file": (io.BytesIO(sample_multi_central_dat_bytes), "s.dat")},
            content_type="multipart/form-data",
        )
        assert resp.status_code == 200
        blocks = resp.get_json()["blocks"]
        ips = [b.get("ip") for b in blocks]
        assert all(ips), f"expected every block to have an IP, got {ips}"
        assert any(ip.startswith("192.168.") for ip in ips)


class TestPerControllerSeriesFilter:
    def test_series_200_excludes_400_controllers(self, app_client, sample_mixed_dsbx_bytes):
        j = _upload_dsbx(app_client, sample_mixed_dsbx_bytes)
        resp = app_client.get(f"/api/download/dsbx-to-dat/{j['session_id']}?series=200")
        assert resp.status_code == 200
        models = _zip_member_models(resp.data)
        assert models, "expected at least one 200-series file"
        assert all(m in _200_MODELS for m in models), models

    def test_series_400_excludes_200_controllers(self, app_client, sample_mixed_dsbx_bytes):
        j = _upload_dsbx(app_client, sample_mixed_dsbx_bytes)
        resp = app_client.get(f"/api/download/dsbx-to-dat/{j['session_id']}?series=400")
        assert resp.status_code == 200
        models = _zip_member_models(resp.data)
        assert models, "expected at least one 400-series file"
        assert all(m in _400_MODELS for m in models), models


class TestSwitchSeries:
    def test_switch_converts_site_to_400(self, app_client, sample_mixed_dsbx_bytes):
        j = _upload_dsbx(app_client, sample_mixed_dsbx_bytes)
        sid = j["session_id"]

        sw = app_client.post(f"/api/session/{sid}/switch-series")
        assert sw.status_code == 200
        types = [b["controller_type"] for b in sw.get_json()["blocks"] if b.get("has_controller", True)]
        assert types and all(t in {"AE-C400A", "EW-C50"} for t in types), types

        # Download (no series param) must now emit only 400-series files.
        resp = app_client.get(f"/api/download/dsbx-to-dat/{sid}")
        assert resp.status_code == 200
        assert all(m in _400_MODELS for m in _zip_member_models(resp.data))


class TestMultiDatNaming:
    def test_multi_dat_filename_uses_site_label(self, app_client, sample_mixed_dsbx_bytes):
        j = _upload_dsbx(app_client, sample_mixed_dsbx_bytes)
        resp = app_client.get(
            f"/api/download/dsbx-to-multi-dat/{j['session_id']}?series=400"
        )
        assert resp.status_code == 200
        disposition = resp.headers.get("Content-Disposition", "")
        assert "AE-C400 site.dat" in disposition, disposition
