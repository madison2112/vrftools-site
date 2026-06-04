"""
Portable, human-readable session export/import (format v2).

A saved session is plain JSON: readable controller/group fields on top, plus the
original controller config carried as readable XML (not a base64 blob) so it
round-trips with full fidelity. There is no signature — the importer validates
the structure strictly instead, which also lets sessions move freely between
deployments (the old v1 format was HMAC-signed with each server's secret key,
which is why cross-site imports reported "modified").

Backward compatible: v1 files (base64 source + HMAC) still import — the HMAC is
treated as a non-fatal note rather than a hard rejection.
"""

import base64
import io
import json
import logging
import re
import zipfile

from .zipcrypto import PASSWORD, build_dat_bytes

logger = logging.getLogger("vrftools.json")

CONTROLLER_TYPES = {"AE-200", "AE-C400A", "EW-50", "EW-C50"}
VALID_TOOLS = {"dsbx-to-dat", "rearranger", "convert", "split", "dat-json"}
_IP_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")
MAX_TAG_LEN = 64

_README = (
    "This is a VRF Tools saved session. To open it, go to https://vrftools.com, "
    "open Config Tools, and upload this file — it will resume your work."
)
_SHARED_NOTE = (
    "If this file was shared with you: it holds a Mitsubishi central-controller "
    "configuration. Upload it at vrftools.com (Config Tools) to use it. The fields "
    "below are human-readable and may be edited; the site validates everything on import."
)


# ---------------------------------------------------------------------------
# DAT <-> readable XML (DAT is a ZipCrypto zip of numbered XML entries + IMG dirs)
# ---------------------------------------------------------------------------


def _dat_to_readable(dat_bytes: bytes) -> dict:
    """Decompose a .dat into readable XML entries + the directory layout."""
    entries = []
    dirs = []
    with zipfile.ZipFile(io.BytesIO(dat_bytes)) as z:
        for info in z.infolist():
            name = info.filename
            if name.endswith("/"):
                dirs.append(name)
            else:
                entries.append(
                    {"entry": name, "xml": z.read(name, pwd=PASSWORD).decode("utf-8")}
                )
    return {"entries": entries, "dirs": dirs}


def _readable_to_dat(src: dict) -> bytes:
    """Re-encrypt readable XML entries (and empty dirs) back into a .dat."""
    build = []
    for e in src.get("entries", []):
        build.append((e["entry"], e["xml"].encode("utf-8"), True))
    for d in src.get("dirs", []):
        build.append((d, None, False))
    return build_dat_bytes(build)


def _dsbx_to_readable(dsbx_bytes: bytes) -> dict:
    """A .dsbx is a plain zip wrapping a single 'xml' document."""
    with zipfile.ZipFile(io.BytesIO(dsbx_bytes)) as z:
        return {"xml": z.read("xml").decode("utf-8-sig")}


def _readable_to_dsbx(src: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("xml", src["xml"])
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_session_json(export_blocks: list, session_data: dict, tool: str) -> bytes:
    """Build a readable v2 session file.

    export_blocks: canonical blocks from _gather_export_state(s) (edits applied),
    used only for the human-readable summary. The authoritative source is the
    raw config carried as readable XML plus the edit fields below.
    """
    source_kind = "dsbx" if session_data.get("type") == "dsbx" else "dat"

    sess_blocks = session_data.get("blocks", [])
    controllers = []
    for i, b in enumerate(export_blocks):
        ip = b.get("ip") or (sess_blocks[i].get("ip", "") if i < len(sess_blocks) else "")
        controllers.append(
            {
                "name": b.get("name", ""),
                "type": b.get("controller_type", ""),
                "ip": ip,
                "groups": [
                    {
                        "slot": g.get("slot"),
                        "tag": g.get("tag", ""),
                        "mnet": g.get("mnet_addresses", []),
                        "units": g.get("unit_types", []),
                        "icon": g.get("icon"),
                    }
                    for g in b.get("groups", [])
                ],
            }
        )

    if source_kind == "dsbx":
        source = {"kind": "dsbx", **_dsbx_to_readable(session_data.get("dsbx_data", b""))}
    else:
        source = {"kind": "dat", **_dat_to_readable(session_data.get("dat_data", b""))}

    edits = {
        "orders": {k[6:]: v for k, v in session_data.items() if k.startswith("order_")},
        "controller_names": session_data.get("controller_names", {}),
        "group_names": session_data.get("group_names", {}),
    }
    if session_data.get("force_family"):
        edits["force_family"] = session_data["force_family"]
    if "expansion_map" in session_data:
        edits["expansion_map"] = session_data["expansion_map"]
    if "generate_blocks" in session_data:
        edits["generate_blocks"] = session_data["generate_blocks"]

    site_series = None
    if source_kind == "dsbx":
        site_series = "AE-C400" if session_data.get("force_family") == "AE-C400A" else "AE-200"

    payload = {
        "_readme": _README,
        "_shared_with_you": _SHARED_NOTE,
        "format": "vrftools-session",
        "version": 2,
        "tool": tool,
        "source_kind": source_kind,
        "site_series": site_series,
        "file_name": session_data.get("dsbx_file_name") or session_data.get("dat_file_name") or "session",
        "multi": session_data.get("multi", False),
        "controllers": controllers,
        "edits": edits,
        "source": source,
    }
    return json.dumps(payload, indent=2).encode()


# ---------------------------------------------------------------------------
# Import — returns a normalized dict for both v1 and v2
# ---------------------------------------------------------------------------


def _err(msg: str) -> ValueError:
    return ValueError(msg)


def _validate_v2(payload: dict) -> None:
    if payload.get("tool") not in VALID_TOOLS:
        raise _err("Unknown tool in session file.")
    if payload.get("source_kind") not in {"dat", "dsbx"}:
        raise _err("Session file has an invalid source_kind.")
    controllers = payload.get("controllers")
    if not isinstance(controllers, list):
        raise _err("Session file 'controllers' must be a list.")
    for c in controllers:
        if not isinstance(c, dict):
            raise _err("Each controller must be an object.")
        if not isinstance(c.get("name", ""), str):
            raise _err("Controller name must be text.")
        ctype = c.get("type", "")
        if ctype and ctype not in CONTROLLER_TYPES:
            raise _err(f"Unknown controller type {ctype!r}.")
        ip = c.get("ip", "")
        if ip and not _IP_RE.match(ip):
            raise _err(f"Invalid IP address {ip!r}.")
        groups = c.get("groups", [])
        if not isinstance(groups, list):
            raise _err("Controller 'groups' must be a list.")
        for g in groups:
            if not isinstance(g, dict):
                raise _err("Each group must be an object.")
            if g.get("slot") is not None and not isinstance(g.get("slot"), int):
                raise _err("Group slot must be a whole number.")
            if not isinstance(g.get("tag", ""), str) or len(g.get("tag", "")) > MAX_TAG_LEN:
                raise _err("Group tag must be text up to 64 characters.")
    src = payload.get("source")
    if not isinstance(src, dict):
        raise _err("Session file is missing its source config.")


def _normalize_v2(payload: dict) -> dict:
    _validate_v2(payload)
    src = payload["source"]
    try:
        if payload["source_kind"] == "dsbx":
            source_bytes = _readable_to_dsbx(src)
        else:
            source_bytes = _readable_to_dat(src)
    except Exception as e:
        raise _err(f"Could not rebuild the configuration from the session file: {e}")

    edits = payload.get("edits", {}) or {}

    # Readable controller fields (name/ip) act as an editable overlay.
    controller_names = dict(edits.get("controller_names", {}) or {})
    for i, c in enumerate(payload.get("controllers", [])):
        if c.get("name"):
            controller_names[str(i)] = c["name"]

    return {
        "version": 2,
        "tool": payload["tool"],
        "source_kind": payload["source_kind"],
        "source_bytes": source_bytes,
        "multi": payload.get("multi", False),
        "orders": edits.get("orders", {}) or {},
        "controller_names": controller_names,
        "group_names": edits.get("group_names", {}) or {},
        "force_family": edits.get("force_family"),
        "expansion_map": edits.get("expansion_map"),
        "generate_blocks": edits.get("generate_blocks"),
        "controllers": payload.get("controllers", []),
    }


def _normalize_v1(payload: dict) -> dict:
    """Old format: base64 source + per-deploy HMAC. We no longer verify the HMAC
    (it broke cross-site imports); the structure still loads."""
    if "hmac" not in payload:
        logger.info("v1 session file without HMAC — importing on structure only")
    source_b64 = payload.get("source_b64", "")
    try:
        source_bytes = base64.b64decode(source_b64)
    except Exception:
        raise _err("Session file source data is not valid.")
    return {
        "version": 1,
        "tool": payload.get("tool", "dat-json"),
        "source_kind": "dsbx" if payload.get("tool") == "dsbx-to-dat" else "dat",
        "source_bytes": source_bytes,
        "multi": payload.get("multi", False),
        "orders": payload.get("orders", {}) or {},
        "controller_names": payload.get("controller_names", {}) or {},
        "group_names": payload.get("group_names", {}) or {},
        "force_family": None,
        "expansion_map": None,
        "generate_blocks": None,
        "controllers": payload.get("blocks", []),
    }


def import_session_json(raw: bytes, secret: bytes = b"") -> dict:
    """Parse a session file (v1 or v2) into a normalized dict.

    `secret` is accepted for signature compatibility but no longer used — v2 is
    unsigned and v1's HMAC is not enforced. Raises ValueError on malformed input.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise _err(f"Invalid JSON: {e}")
    if not isinstance(payload, dict):
        raise _err("Session file must be a JSON object.")

    if payload.get("version") == 2 or payload.get("format") == "vrftools-session":
        return _normalize_v2(payload)
    return _normalize_v1(payload)
