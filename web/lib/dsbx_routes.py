"""
DSBX tool routes — Flask Blueprint.

Routes for .dsbx file upload, group viewing/rearrangement, and DSBX→DAT
download. Also serves the DSBX-to-DAT page route.

Pattern note (B-10 — second blueprint extraction, following B-09):
- Blueprint location: web/lib/dsbx_routes.py (not web/blueprints/)
- Naming: <tool>_routes.py matching dat_routes, lev_kit_routes, etc.
- Shared helpers: route-level helpers from web/lib/route_helpers.py.
  Domain functions stay in web/lib/dsbx_utils.py (DSBX parsing) and
  web/lib/dat_utils.py (DAT XML generation/editing).
- Session helpers: session CRUD called directly via `from . import sessions`.
- _check_warnings: imported from dat_utils.py (option a — keeps card focused;
  long-term promotion to route_helpers.py or warnings.py is tracked
  separately).
"""

import io
import logging
import xml.etree.ElementTree as ET

from flask import Blueprint, abort, jsonify, render_template, request, send_file

from . import sessions
from .dat_utils import (
    _check_warnings,
    apply_group_names,
    apply_rearrangement,
    generate_dat_bytes,
    parse_dat_controllers,
)
from .dsbx_utils import (
    dsbx_to_dat_bytes,
    extract_group_cards,
    get_groupof50_list,
    load_mapping,
    parse_dsbx_bytes,
)
from .route_helpers import (
    _preloaded_session,
    _send_dat,
    _send_zip,
    _validate_upload,
    _zip_results,
)
from .session_utils import apply_order_to_groups

logger = logging.getLogger(__name__)

dsbx_bp = Blueprint("dsbx", __name__)


# ---------------------------------------------------------------------------
# Page route
# ---------------------------------------------------------------------------


@dsbx_bp.route("/dsbx-to-dat")
def page_dsbx_to_dat():
    preloaded = _preloaded_session("dsbx")
    return render_template("dsbx_to_dat.html", preloaded_session=preloaded)


# ---------------------------------------------------------------------------
# API — DSBX upload
# ---------------------------------------------------------------------------


@dsbx_bp.route("/api/upload/dsbx", methods=["POST"])
def api_upload_dsbx():
    data, _ = _validate_upload(request.files.get("file"), {".dsbx"})

    # Validate it's a ZIP
    if not data[:4] == b"PK\x03\x04":
        abort(400, "File does not appear to be a valid .dsbx archive.")

    try:
        mapping = load_mapping()
        dsb_root = parse_dsbx_bytes(data)
        g50_list = get_groupof50_list(dsb_root)
    except Exception:
        logger.warning("Could not parse .dsbx file", exc_info=True)
        abort(400, "Could not parse the .dsbx file. Please verify it is a valid DSBX export.")

    blocks = []
    for g50 in g50_list:
        cards = extract_group_cards(g50, mapping)
        blocks.append(
            {
                "name": g50.findtext("Name") or "",
                "groups": cards,
                "warnings": _check_warnings(cards),
            }
        )

    sid = sessions.create(
        {
            "type": "dsbx",
            "dsbx_data": data,
            "blocks": blocks,
        }
    )

    return jsonify({"session_id": sid, "blocks": blocks})


# ---------------------------------------------------------------------------
# API — Session groups (used by both DSBX and DAT tools via absolute URLs)
# ---------------------------------------------------------------------------


@dsbx_bp.route("/api/session/<sid>/groups", methods=["GET"])
def api_get_groups(sid):
    s = sessions.get(sid)
    if not s:
        abort(404, "Session not found or expired.")

    blocks = s.get("blocks", [])

    # Apply saved rearrangement orders to group slot numbers so the
    # frontend renders cards in the user's arranged positions, not the
    # original extraction order.
    result = []
    for i, block in enumerate(blocks):
        groups = [dict(g) for g in block.get("groups", [])]
        apply_order_to_groups(groups, s.get(f"order_{i}"))
        result.append({**block, "groups": groups})

    return jsonify({"blocks": result})


@dsbx_bp.route("/api/session/<sid>/groups", methods=["POST"])
def api_update_groups(sid):
    """Accept rearranged group order for a DSBX block or DAT."""
    s = sessions.get(sid)
    if not s:
        abort(404, "Session not found or expired.")

    body = request.get_json(force=True) or {}
    new_order = body.get("new_order")  # list of old slot numbers
    block_idx = body.get("block_index", 0)  # which Groupof50 block (dsbx only)

    if not isinstance(new_order, list):
        abort(400, "new_order must be a list of slot numbers.")

    sessions.update(sid, {f"order_{block_idx}": new_order})
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API — Download DSBX→DAT
# ---------------------------------------------------------------------------


@dsbx_bp.route("/api/download/dsbx-to-dat/<sid>")
def api_download_dsbx_to_dat(sid):
    s = sessions.get(sid)
    if not s or s.get("type") != "dsbx":
        abort(404, "Session not found or expired.")

    version = request.args.get("version", "AE-C400A")
    if version not in ("AE-C400A", "AE-200"):
        abort(400, "version must be AE-C400A or AE-200.")

    try:
        results = dsbx_to_dat_bytes(s["dsbx_data"], version)
    except Exception:
        logger.error("Conversion failed", exc_info=True)
        abort(500, "Conversion failed. Please try again or contact support.")

    # Apply user edits in correct order: names FIRST, then rearrangement.
    # Names must be written to the original Group numbers before
    # apply_rearrangement remaps them — otherwise renames hit wrong records.
    controller_names = s.get("controller_names", {})
    group_names = s.get("group_names", {})

    for i, r in enumerate(results):
        try:
            controllers = parse_dat_controllers(r["data"])
            if controllers:
                xml = controllers[0]["xml_bytes"]

                # 1. Apply controller name
                name = controller_names.get(str(i))
                if name:
                    root = ET.fromstring(xml)
                    sd = root.find(".//SystemData")
                    if sd is not None:
                        sd.set("Name", name)
                    buf = io.BytesIO()
                    ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
                    xml = buf.getvalue()

                # 2. Apply group tag names (on original Group numbers)
                tag_map = group_names.get(str(i), {})
                int_map = {int(k): v for k, v in tag_map.items()}
                if int_map:
                    xml = apply_group_names(xml, int_map)

                # 3. Apply rearrangement (remaps Group numbers AFTER names)
                order = s.get(f"order_{i}")
                if isinstance(order, list) and order:
                    xml = apply_rearrangement(xml, order)

                r["data"] = generate_dat_bytes(xml, r["controller"])

                # Use the renamed controller name for the filename
                if name:
                    r["name"] = f"{name} {r['controller']}"
        except Exception:
            logger.warning("DSBX→DAT export edit failed for block %d", i, exc_info=True)

    if len(results) == 1:
        r = results[0]
        return _send_dat(r["data"], r["name"] + ".dat")

    return _send_zip(_zip_results(results), "dsbx_export.zip")
