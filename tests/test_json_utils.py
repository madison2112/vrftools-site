"""Unit tests for web.lib.json_utils — readable v2 session export/import.

v2 is unsigned and human-readable: readable controller/group fields plus the
original config carried as readable XML (no base64 blob, no HMAC). Old v1 files
still import (signature not enforced).
"""

from __future__ import annotations

import base64
import io
import json
import zipfile
from pathlib import Path

import pytest

from web.lib.json_utils import export_session_json, import_session_json

FIX = Path(__file__).parent / "fixtures"
DAT = (FIX / "sample_multi_central.dat").read_bytes()
DSBX = (FIX / "sample_multi_central_mixed.dsbx").read_bytes()


def _dat_session():
    return {
        "type": "dat",
        "dat_data": DAT,
        "multi": True,
        "blocks": [{"name": "Floor 1", "controller_type": "AE-200", "ip": "192.168.2.1", "groups": []}],
    }


def _export_blocks():
    return [
        {
            "name": "Floor 1",
            "controller_type": "AE-200",
            "ip": "192.168.2.1",
            "groups": [{"slot": 1, "tag": "Lobby", "mnet_addresses": ["50"], "unit_types": ["IC"], "icon": 10}],
        }
    ]


class TestExportV2:
    def test_readable_json_no_base64_no_hmac(self):
        p = json.loads(export_session_json(_export_blocks(), _dat_session(), "rearranger"))
        assert p["version"] == 2
        assert p["format"] == "vrftools-session"
        assert "hmac" not in p and "source_b64" not in p
        assert p["_readme"]
        assert p["source"]["kind"] == "dat"
        assert p["controllers"][0]["name"] == "Floor 1"
        assert p["controllers"][0]["ip"] == "192.168.2.1"

    def test_orders_captured(self):
        s = _dat_session()
        s["order_0"] = [1, 2, 3]
        p = json.loads(export_session_json(_export_blocks(), s, "rearranger"))
        assert p["edits"]["orders"] == {"0": [1, 2, 3]}

    def test_dsbx_source_is_readable_xml(self):
        s = {"type": "dsbx", "dsbx_data": DSBX, "multi": True, "force_family": "AE-C400A", "blocks": []}
        p = json.loads(export_session_json([], s, "dsbx-to-dat"))
        assert p["source"]["kind"] == "dsbx"
        assert "<" in p["source"]["xml"]  # readable XML, not base64 gibberish
        assert p["site_series"] == "AE-C400"
        assert p["edits"]["force_family"] == "AE-C400A"


class TestImportV2:
    def test_round_trip_rebuilds_valid_source(self):
        out = export_session_json(_export_blocks(), _dat_session(), "rearranger")
        imp = import_session_json(out)
        assert imp["version"] == 2
        assert imp["tool"] == "rearranger"
        assert imp["source_bytes"][:2] == b"PK"  # a valid zip was rebuilt
        z = zipfile.ZipFile(io.BytesIO(imp["source_bytes"]))
        # numbered XML entries decrypt with the MELCO password
        entry = next(n for n in z.namelist() if not n.endswith("/"))
        assert z.read(entry, pwd=b"MELCO")[:1] in (b"<", b"\xef")

    def test_rejects_bad_ip(self):
        p = json.loads(export_session_json(_export_blocks(), _dat_session(), "rearranger"))
        p["controllers"][0]["ip"] = "999.999.x"
        with pytest.raises(ValueError, match="IP"):
            import_session_json(json.dumps(p).encode())

    def test_rejects_unknown_controller_type(self):
        p = json.loads(export_session_json(_export_blocks(), _dat_session(), "rearranger"))
        p["controllers"][0]["type"] = "AE-999"
        with pytest.raises(ValueError, match="controller type"):
            import_session_json(json.dumps(p).encode())

    def test_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Invalid JSON"):
            import_session_json(b"not json at all {{{")

    def test_non_dict_raises(self):
        with pytest.raises(ValueError, match="object"):
            import_session_json(json.dumps([1, 2, 3]).encode())


class TestV1BackCompat:
    def test_v1_file_imports_without_signature_check(self):
        v1 = {
            "v": 1,
            "tool": "rearranger",
            "multi": True,
            "source_b64": base64.b64encode(DAT).decode(),
            "orders": {},
            "controller_names": {"0": "X"},
            "group_names": {},
            "blocks": [],
            "hmac": "deadbeef" * 8,  # wrong/foreign signature — must NOT block import
        }
        imp = import_session_json(json.dumps(v1).encode())
        assert imp["version"] == 1
        assert imp["tool"] == "rearranger"
        assert imp["source_bytes"][:2] == b"PK"
        assert imp["controller_names"] == {"0": "X"}
