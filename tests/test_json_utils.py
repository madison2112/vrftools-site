"""Unit tests for web.lib.json_utils — HMAC-signed JSON export/import."""

from __future__ import annotations

import pytest

from web.lib.json_utils import export_session_json, import_session_json


# A fixed secret for deterministic test HMACs
TEST_SECRET = b"test-secret-key-12345"


class TestExportSessionJson:
    """Tests for export_session_json."""

    def test_returns_bytes(self):
        export_blocks = [
            {
                "name": "Controller-1",
                "controller_type": "AE-200",
                "groups": [
                    {"slot": 1, "tag": "Floor-01", "mnet_addresses": ["50"], "unit_types": ["IC"], "icon": 10},
                ],
            },
        ]
        session_data = {
            "type": "dat",
            "dat_data": b"dummy-dat-bytes",
            "multi": False,
        }
        result = export_session_json(export_blocks, session_data, "dat-configure", TEST_SECRET)
        assert isinstance(result, bytes)

    def test_output_is_valid_json(self):
        export_blocks = []
        session_data = {"type": "dat", "dat_data": b"hello", "multi": False}
        result = export_session_json(export_blocks, session_data, "dat-configure", TEST_SECRET)
        import json
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_output_contains_hmac(self):
        export_blocks = []
        session_data = {"type": "dat", "dat_data": b"hello", "multi": False}
        result = export_session_json(export_blocks, session_data, "dat-configure", TEST_SECRET)
        import json
        parsed = json.loads(result)
        assert "hmac" in parsed
        assert isinstance(parsed["hmac"], str)
        assert len(parsed["hmac"]) == 64  # SHA-256 hex digest

    def test_handles_orders_from_session_data(self):
        export_blocks = [
            {"name": "Ctrl-1", "controller_type": "AE-200", "groups": []},
        ]
        session_data = {
            "type": "dat",
            "dat_data": b"hello",
            "multi": False,
            "order_0": [1, 2],
            "order_1": [3],
        }
        result = export_session_json(export_blocks, session_data, "dat-rearrange", TEST_SECRET)
        import json
        parsed = json.loads(result)
        assert "orders" in parsed
        assert parsed["orders"] == {"0": [1, 2], "1": [3]}

    def test_handles_dsbx_type(self):
        export_blocks = [
            {"name": "DSBX-Project", "controller_type": "AE-C400A", "groups": []},
        ]
        session_data = {
            "type": "dsbx",
            "dsbx_data": b"dsbx-raw-bytes-here",
            "multi": True,
        }
        result = export_session_json(export_blocks, session_data, "dsbx-configure", TEST_SECRET)
        import json
        parsed = json.loads(result)
        assert parsed["tool"] == "dsbx-configure"
        assert parsed["multi"] is True

    def test_controller_names_in_output(self):
        export_blocks = [
            {"name": "MyCtrl", "controller_type": "AE-200", "groups": []},
        ]
        session_data = {
            "type": "dat",
            "dat_data": b"hello",
            "multi": False,
            "controller_names": {"0": "OriginalName"},
        }
        result = export_session_json(export_blocks, session_data, "dat-configure", TEST_SECRET)
        import json
        parsed = json.loads(result)
        assert "controller_names" in parsed
        # Block name should be captured if not already in controller_names
        assert "0" in parsed["controller_names"]


class TestImportSessionJson:
    """Tests for import_session_json."""

    def test_valid_round_trip(self):
        """export → import should return the same payload."""
        export_blocks = [
            {
                "name": "RoundTrip-Test",
                "controller_type": "AE-C400A",
                "groups": [
                    {"slot": 1, "tag": "Floor-01", "mnet_addresses": ["50"], "unit_types": ["IC"], "icon": 10},
                ],
            },
        ]
        session_data = {
            "type": "dat",
            "dat_data": b"roundtrip-data",
            "multi": False,
            "order_0": [1, 2, 3],
            "controller_names": {"0": "RoundTrip-Test"},
            "group_names": {},
        }
        exported = export_session_json(export_blocks, session_data, "dat-configure", TEST_SECRET)
        imported = import_session_json(exported, TEST_SECRET)
        assert imported["tool"] == "dat-configure"
        assert imported["v"] == 1
        assert imported["multi"] is False
        assert "orders" in imported
        assert imported["blocks"] == [
            {"name": "RoundTrip-Test", "controller_type": "AE-C400A", "groups": [
                {"slot": 1, "tag": "Floor-01", "mnet_addresses": ["50"], "unit_types": ["IC"], "icon": 10}
            ]},
        ]

    def test_tampered_hmac_raises(self):
        export_blocks = [{"name": "Test", "controller_type": "AE-200", "groups": []}]
        session_data = {"type": "dat", "dat_data": b"data", "multi": False}
        exported = export_session_json(export_blocks, session_data, "dat-configure", TEST_SECRET)
        # Tamper: replace the HMAC
        import json
        payload = json.loads(exported)
        payload["hmac"] = "0" * 64  # obviously wrong
        tampered = json.dumps(payload).encode()
        with pytest.raises(ValueError, match="modified"):
            import_session_json(tampered, TEST_SECRET)

    def test_missing_hmac_raises(self):
        import json
        payload = {"v": 1, "tool": "test", "blocks": []}
        raw = json.dumps(payload).encode()
        with pytest.raises(ValueError, match="missing integrity"):
            import_session_json(raw, TEST_SECRET)

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            import_session_json(b"not json at all {{{{{", TEST_SECRET)

    def test_non_dict_json_raises(self):
        import json
        raw = json.dumps([1, 2, 3]).encode()
        with pytest.raises(ValueError, match="must be an object"):
            import_session_json(raw, TEST_SECRET)

    def test_different_secret_fails(self):
        export_blocks = [{"name": "Test", "controller_type": "AE-200", "groups": []}]
        session_data = {"type": "dat", "dat_data": b"data", "multi": False}
        exported = export_session_json(export_blocks, session_data, "dat-configure", TEST_SECRET)
        with pytest.raises(ValueError, match="modified"):
            import_session_json(exported, b"different-secret-key")
