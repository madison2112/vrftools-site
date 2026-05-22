"""
DAT tool routes — Flask Blueprint.

Routes for .dat file upload, group rearrangement, controller/group renaming,
sort, convert, split, and JSON export. Also serves the DAT tool page routes.

Pattern-setting notes (B-09 — first blueprint extraction):
- Blueprint location: web/lib/dat_routes.py (not web/blueprints/)
  following the convention used by the existing agent_routes.py.
- Naming: <tool>_routes.py (dat_routes, dsbx_routes, lev_kit_routes, etc.).
- Shared helpers: route-level helpers used by multiple blueprints live in
  web/lib/route_helpers.py. Domain functions stay in web/lib/<tool>_utils.py.
- Session helpers: session CRUD is called directly via `from . import sessions`.
  The `require_session` helper (B-13) is now introduced.
- Module-global constants: DAT-specific constants (_TOOL_ROUTES, _VALID_TOOLS)
  live in the blueprint module; shared constants (MAX_UPLOAD_BYTES) live in
  route_helpers.py.
"""

import base64
import io
import logging
import os
import xml.etree.ElementTree as ET

import pyzipper
from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    send_file,
)

from . import sessions
from .dat_utils import (
    apply_group_names,
    apply_rearrangement,
    convert_dat_bytes,
    extract_groups_from_xml,
    generate_dat_bytes,
    parse_dat_controllers,
    rearrange_and_convert_dat_bytes,
    rearrange_and_repackage_dat_bytes,
    rearrange_and_split_dat_bytes,
    safe_filename,
    sort_groups_by_tag,
    split_dat_bytes,
    _check_warnings,
)
from .json_utils import export_session_json
from .route_helpers import (
    _preloaded_session,
    _send_dat,
    _send_zip,
    _validate_upload,
    _zip_results,
)
from .session_utils import apply_order_to_groups, require_session

logger = logging.getLogger(__name__)

dat_bp = Blueprint("dat", __name__)

# ---------------------------------------------------------------------------
# Tool routing table (shared with Config Hub for redirect-on-restore)
# ---------------------------------------------------------------------------

_TOOL_ROUTES = {
    "dsbx-to-dat": "/dsbx-to-dat",
    "rearranger": "/rearranger",
    "convert": "/convert",
    "split": "/split",
}

_VALID_TOOLS = set(_TOOL_ROUTES.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _gather_export_state(s: dict) -> list:
    """
    Single source of truth for both DAT and JSON exports.

    For DAT sessions: parses raw dat_data, applies all user edits
    (controller names, group tag names, rearrangement orders), then
    re-extracts groups so slot numbers reflect the final arrangement.

    Returns a canonical list of controller blocks:
      [{name, controller_type, xml_bytes, groups, entry}, ...]
    """
    session_type = s.get("type", "dat")
    controller_names = s.get("controller_names", {})
    group_names = s.get("group_names", {})

    # DSBX sessions: work from in-memory blocks, no XML to parse
    if session_type == "dsbx":
        result = []
        blocks = s.get("blocks", [])
        for i, b in enumerate(blocks):
            groups = [dict(g) for g in b.get("groups", [])]
            # Apply rearrangement by remapping slot numbers
            apply_order_to_groups(groups, s.get(f"order_{i}"))
            result.append(
                {
                    "name": controller_names.get(str(i)) or b.get("name", ""),
                    "controller_type": b.get("controller_type", ""),
                    "xml_bytes": b"",  # no XML for DSBX sessions
                    "groups": groups,
                    "entry": str(i + 1),
                }
            )
        return result

    # DAT sessions: parse raw bytes, apply edits, re-extract
    raw_bytes = s.get("dat_data", b"")
    blocks = s.get("blocks", [])

    controllers = parse_dat_controllers(raw_bytes)

    result = []
    for i, ctrl in enumerate(controllers):
        xml = ctrl["xml_bytes"]

        # 1. Apply controller name
        name = controller_names.get(str(i)) or (
            blocks[i].get("name", "") if i < len(blocks) else ""
        )
        if name:
            try:
                root = ET.fromstring(xml)
                sd = root.find(".//SystemData")
                if sd is not None:
                    sd.set("Name", name)
                buf = io.BytesIO()
                ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
                xml = buf.getvalue()
            except ET.ParseError:
                logger.warning("XML parse error applying controller name for block %d", i)

        # 2. Apply group tag names
        tag_map = group_names.get(str(i), {})
        int_map = {int(k): v for k, v in tag_map.items()}
        if int_map:
            xml = apply_group_names(xml, int_map)

        # 3. Apply rearrangement
        order = s.get(f"order_{i}")
        if isinstance(order, list) and order:
            try:
                xml = apply_rearrangement(xml, order)
            except Exception:
                logger.warning("Rearrangement failed for block %d", i, exc_info=True)

        # 4. Re-extract groups with final slot positions
        groups = extract_groups_from_xml(xml)

        result.append(
            {
                "name": name or ctrl["name"],
                "controller_type": ctrl["controller_type"],
                "xml_bytes": xml,
                "groups": groups,
                "entry": ctrl["entry"],
            }
        )

    return result


def _package_export_dat(export_blocks: list, raw_bytes: bytes) -> bytes:
    """
    Package the canonical export blocks back into a .dat file.
    Preserves non-controller ZIP entries (NetworkSetting.xml, IMG/, etc.).
    """
    from .zipcrypto import build_dat_bytes, PASSWORD

    entries = []
    for block in export_blocks:
        entries.append((block["entry"], block["xml_bytes"], True))

    with pyzipper.AESZipFile(io.BytesIO(raw_bytes)) as z:
        ctrl_entry_names = {b["entry"] for b in export_blocks}
        for name in z.namelist():
            if name in ctrl_entry_names:
                continue
            if name.endswith("/"):
                entries.append((name, None, False))
            else:
                try:
                    data = z.read(name, pwd=PASSWORD)
                except Exception:
                    data = z.read(name)
                entries.append((name, data, True))

    return build_dat_bytes(entries)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@dat_bp.route("/rearranger")
def page_rearranger():
    preloaded = _preloaded_session("dat")
    return render_template("rearranger.html", preloaded_session=preloaded)


@dat_bp.route("/convert")
def page_convert():
    preloaded = _preloaded_session("dat")
    return render_template("convert.html", preloaded_session=preloaded)


@dat_bp.route("/split")
def page_split():
    preloaded = _preloaded_session("dat")
    return render_template("split.html", preloaded_session=preloaded)


@dat_bp.route("/docs")
def page_docs():
    return render_template("docs.html")


# ---------------------------------------------------------------------------
# API — DAT upload (shared by rearranger, convert, split)
# ---------------------------------------------------------------------------


@dat_bp.route("/api/upload/dat", methods=["POST"])
def api_upload_dat():
    data, _ = _validate_upload(request.files.get("file"), {".dat"})

    if not data[:4] == b"PK\x03\x04":
        abort(400, "File does not appear to be a valid .dat archive.")

    try:
        controllers = parse_dat_controllers(data)
    except Exception:
        logger.warning("Could not parse .dat file", exc_info=True)
        abort(
            400,
            "Could not parse the .dat file. Please verify it is a valid configuration export.",
        )

    if not controllers:
        abort(400, "No controller data found in this .dat file.")

    blocks = []
    for ctrl in controllers:
        cards = extract_groups_from_xml(ctrl["xml_bytes"])
        blocks.append(
            {
                "name": ctrl["name"],
                "controller_type": ctrl["controller_type"],
                "groups": cards,
                "warnings": _check_warnings(cards),
            }
        )

    sid = sessions.create(
        {
            "type": "dat",
            "dat_data": data,
            "blocks": blocks,
            "multi": len(controllers) > 1,
        }
    )

    return jsonify(
        {
            "session_id": sid,
            "blocks": blocks,
            "multi": len(controllers) > 1,
        }
    )


# ---------------------------------------------------------------------------
# API — Download: rearrange
# ---------------------------------------------------------------------------


@dat_bp.route("/api/download/rearrange/<sid>")
def api_download_rearrange(sid):
    s = require_session(sid, "dat")

    export = request.args.get("export", "packaged")
    export_blocks = _gather_export_state(s)
    dat_data = _package_export_dat(export_blocks, s.get("dat_data", b""))
    blocks = s.get("blocks", [])

    try:
        if export == "individual":
            results = rearrange_and_split_dat_bytes(dat_data, {})
            if len(results) == 1:
                return _send_dat(results[0]["data"], f"{results[0]['name']}_rearranged.dat")
            return _send_zip(_zip_results(results), "rearranged_controllers.zip")

        elif export == "converted":
            results = rearrange_and_convert_dat_bytes(dat_data, {})
            if len(results) == 1:
                return _send_dat(results[0]["data"], f"{results[0]['name']}.dat")
            return _send_zip(_zip_results(results), "converted_controllers.zip")

        else:  # packaged (default)
            result = rearrange_and_repackage_dat_bytes(dat_data, {})
            base = safe_filename(blocks[0]["name"]) if blocks else "rearranged"
            fname = f"{base}_rearranged.dat" if len(blocks) == 1 else "rearranged.dat"
            return _send_dat(result, fname)

    except Exception:
        logger.error("DAT export failed", exc_info=True)
        abort(500, "Export failed. Please try again or contact support.")


# ---------------------------------------------------------------------------
# API — Download: convert
# ---------------------------------------------------------------------------


@dat_bp.route("/api/download/convert/<sid>")
def api_download_convert(sid):
    s = require_session(sid, "dat")

    export_blocks = _gather_export_state(s)
    dat_data = _package_export_dat(export_blocks, s.get("dat_data", b""))

    try:
        results = convert_dat_bytes(dat_data)
    except Exception:
        logger.error("DAT conversion failed", exc_info=True)
        abort(500, "Conversion failed. Please try again or contact support.")

    if len(results) == 1:
        r = results[0]
        return _send_dat(r["data"], r["name"] + ".dat")

    return _send_zip(_zip_results(results), "converted.zip")


# ---------------------------------------------------------------------------
# API — Download: split
# ---------------------------------------------------------------------------


@dat_bp.route("/api/download/split/<sid>")
def api_download_split(sid):
    s = require_session(sid, "dat")

    export_blocks = _gather_export_state(s)
    dat_data = _package_export_dat(export_blocks, s.get("dat_data", b""))

    try:
        results = split_dat_bytes(dat_data)
    except ValueError as e:
        abort(400, str(e))
    except Exception:
        logger.error("DAT split failed", exc_info=True)
        abort(500, "Split failed. Please try again or contact support.")

    return _send_zip(_zip_results(results), "split_controllers.zip")


# ---------------------------------------------------------------------------
# API — Sort groups by tag name
# ---------------------------------------------------------------------------


@dat_bp.route("/api/session/<sid>/sort", methods=["POST"])
def api_sort_groups(sid):
    s = require_session(sid)

    body = request.get_json(force=True) or {}
    block_idx = body.get("block_index", 0)

    blocks = s.get("blocks", [])
    if block_idx >= len(blocks):
        abort(400, "Invalid block index.")

    cards = blocks[block_idx]["groups"]
    new_order = sort_groups_by_tag(cards)
    sessions.update(sid, {f"order_{block_idx}": new_order})

    return jsonify({"ok": True, "new_order": new_order})


@dat_bp.route("/api/session/<sid>/controller-name", methods=["POST"])
def api_update_controller_name(sid):
    s = require_session(sid)

    body = request.get_json(force=True) or {}
    block_idx = body.get("block_index", 0)
    new_name = str(body.get("name", "")).strip()

    if not new_name:
        abort(400, "Controller name cannot be empty.")

    blocks = s.get("blocks", [])
    if block_idx >= len(blocks):
        abort(400, "Invalid block index.")

    blocks[block_idx]["name"] = new_name

    names = s.get("controller_names", {})
    names[str(block_idx)] = new_name
    sessions.update(sid, {"blocks": blocks, "controller_names": names})

    return jsonify({"ok": True, "name": new_name})


@dat_bp.route("/api/session/<sid>/group-name", methods=["POST"])
def api_update_group_name(sid):
    s = require_session(sid)

    body = request.get_json(force=True) or {}
    block_idx = body.get("block_index", 0)
    slot = body.get("slot")
    new_tag = str(body.get("tag", "")).strip()

    if not new_tag:
        abort(400, "Group tag name cannot be empty.")
    if not isinstance(slot, int) or slot < 1:
        abort(400, "Invalid slot number.")

    blocks = s.get("blocks", [])
    if block_idx >= len(blocks):
        abort(400, "Invalid block index.")

    groups = blocks[block_idx].get("groups", [])
    updated = False
    for g in groups:
        if g.get("slot") == slot:
            g["tag"] = new_tag
            updated = True
            break

    if not updated:
        abort(400, f"Slot {slot} not found in block {block_idx}.")

    group_names = s.get("group_names", {})
    group_names.setdefault(str(block_idx), {})[str(slot)] = new_tag
    sessions.update(sid, {"blocks": blocks, "group_names": group_names})

    return jsonify({"ok": True, "tag": new_tag})


# ---------------------------------------------------------------------------
# API — DAT↔JSON export
# ---------------------------------------------------------------------------


@dat_bp.route("/api/export-json", methods=["POST"])
def api_export_json():
    body = request.get_json(force=True) or {}
    sid = body.get("session_id")
    tool = body.get("tool")

    if tool not in _VALID_TOOLS:
        abort(400, "Invalid tool.")

    s = require_session(sid)

    # Apply any orders the frontend sent in the request body.
    orders_payload = body.get("orders")
    if isinstance(orders_payload, dict):
        for idx_str, order in orders_payload.items():
            if isinstance(order, list):
                sessions.update(sid, {f"order_{idx_str}": order})

    # Re-read session to pick up the just-applied orders
    s = require_session(sid)

    # Canonical export state — names, group tags, and order all applied
    export_blocks = _gather_export_state(s)

    secret = (
        current_app.secret_key
        if isinstance(current_app.secret_key, bytes)
        else current_app.secret_key.encode()
    )
    try:
        json_bytes = export_session_json(export_blocks, s, tool, secret)
    except Exception:
        logger.error("JSON export failed", exc_info=True)
        abort(500, "Export failed. Please try again or contact support.")

    return send_file(
        io.BytesIO(json_bytes),
        mimetype="application/json",
        as_attachment=True,
        download_name="config_export.json",
    )
