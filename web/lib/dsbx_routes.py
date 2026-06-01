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
    build_multi_dat_200,
    build_multi_dat_400,
    generate_dat_bytes,
    parse_dat_controllers,
    safe_filename,
)
from .dsbx_utils import (
    dsbx_to_dat_bytes,
    extract_group_cards,
    get_dsbx_project_lan,
    get_groupof50_controller_info,
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
from .session_utils import apply_order_to_groups, require_session

logger = logging.getLogger(__name__)

dsbx_bp = Blueprint("dsbx", __name__)

_200_FAMILY = {"AE-200"}
_EW50_FAMILY = {"EW-50"}


def _ip_sort_key(ip: str):
    """Sort key for IP addresses; falls back to string comparison on parse error."""
    try:
        return tuple(int(x) for x in ip.split("."))
    except Exception:
        return (999, 999, 999, 999)


def _compute_default_expansion_map(blocks: list) -> dict:
    """
    Assign EW-50/AE-50 blocks as expansion controllers under AE-200 main blocks,
    distributing by IP address order (lowest IP AE-200 picks up the 3 lowest IP EW-50s).
    Excess EW-50s beyond 3 per AE-200 are left as standalone (None).

    Returns: {"<block_idx>": "<parent_block_idx>" | None}
    Only includes EW-50/AE-50 blocks as keys.
    """
    ae200_indices = [
        i for i, b in enumerate(blocks)
        if b.get("controller_type") in _200_FAMILY and b.get("has_controller")
    ]
    ew50_indices = [
        i for i, b in enumerate(blocks)
        if b.get("controller_type") in _EW50_FAMILY and b.get("has_controller")
    ]

    ae200_sorted = sorted(ae200_indices, key=lambda i: _ip_sort_key(blocks[i].get("ip", "")))
    ew50_sorted = sorted(ew50_indices, key=lambda i: _ip_sort_key(blocks[i].get("ip", "")))

    expansion_map = {}
    for pos, ew_idx in enumerate(ew50_sorted):
        parent_slot = pos // 3  # 0 → first AE-200, 1 → second AE-200, etc.
        if parent_slot < len(ae200_sorted):
            expansion_map[str(ew_idx)] = str(ae200_sorted[parent_slot])
        else:
            expansion_map[str(ew_idx)] = None  # standalone

    return expansion_map


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

    # Read project-level LAN toggle — when false, IPs in DSB are placeholders
    lan_enabled = get_dsbx_project_lan(dsb_root)

    # Build blocks with controller info; compute default sequential IPs when LAN is off
    blocks = []
    ip_counter = [1]  # mutable for closure — tracks next default IP octet

    for g50 in g50_list:
        cards = extract_group_cards(g50, mapping)
        default_ip = f"192.168.1.{ip_counter[0]}"
        ip_counter[0] += 1

        ctrl_info = get_groupof50_controller_info(
            g50,
            ip_override="" if lan_enabled else default_ip,
        )

        blocks.append(
            {
                "name": g50.findtext("Name") or "",
                "controller_type": ctrl_info["controller_type"],
                "display_model": ctrl_info["display_model"],
                "ip": ctrl_info["ip"] if lan_enabled else default_ip,
                "has_controller": ctrl_info["has_controller"],
                "is_master": ctrl_info["is_master"],
                "groups": cards,
                "warnings": _check_warnings(cards),
            }
        )

    # Default expansion assignment: sort AE-200s and EW-50/AE-50s by IP, assign
    # up to 3 expansions per AE-200 (lowest IP 200 → lowest 3 IP 50s, etc.)
    expansion_map = _compute_default_expansion_map(blocks)

    sid = sessions.create(
        {
            "type": "dsbx",
            "dsbx_data": data,
            "blocks": blocks,
            "expansion_map": expansion_map,
            "lan_enabled": lan_enabled,
        }
    )

    return jsonify({"session_id": sid, "blocks": blocks, "expansion_map": expansion_map})


# ---------------------------------------------------------------------------
# API — Session groups (used by both DSBX and DAT tools via absolute URLs)
# ---------------------------------------------------------------------------


@dsbx_bp.route("/api/session/<sid>/groups", methods=["GET"])
def api_get_groups(sid):
    s = require_session(sid)

    blocks = s.get("blocks", [])

    # Apply saved rearrangement orders to group slot numbers so the
    # frontend renders cards in the user's arranged positions, not the
    # original extraction order.
    result = []
    for i, block in enumerate(blocks):
        groups = [dict(g) for g in block.get("groups", [])]
        apply_order_to_groups(groups, s.get(f"order_{i}"))
        result.append({**block, "groups": groups})

    result_data = {"blocks": result}
    if s.get("type") == "dsbx":
        result_data["expansion_map"] = s.get("expansion_map", {})
    return jsonify(result_data)


@dsbx_bp.route("/api/session/<sid>/groups", methods=["POST"])
def api_update_groups(sid):
    """Accept rearranged group order for a DSBX block or DAT."""
    s = require_session(sid)

    body = request.get_json(force=True) or {}
    new_order = body.get("new_order")  # list of old slot numbers
    block_idx = body.get("block_index", 0)  # which Groupof50 block (dsbx only)

    if not isinstance(new_order, list):
        abort(400, "new_order must be a list of slot numbers.")

    sessions.update(sid, {f"order_{block_idx}": new_order})
    return jsonify({"ok": True})


@dsbx_bp.route("/api/session/<sid>/controller-ip", methods=["POST"])
def api_update_controller_ip(sid):
    s = require_session(sid)

    body = request.get_json(force=True) or {}
    block_idx = body.get("block_index", 0)
    new_ip = str(body.get("ip", "")).strip()

    if not new_ip:
        abort(400, "IP address cannot be empty.")

    blocks = s.get("blocks", [])
    if block_idx >= len(blocks):
        abort(400, "Invalid block index.")

    blocks[block_idx]["ip"] = new_ip
    sessions.update(sid, {"blocks": blocks})
    return jsonify({"ok": True, "ip": new_ip})


@dsbx_bp.route("/api/session/<sid>/expansion-map", methods=["POST"])
def api_update_expansion_map(sid):
    """Update the expansion map: {"<block_idx>": "<parent_idx>" | null}"""
    s = require_session(sid)

    body = request.get_json(force=True) or {}
    new_map = body.get("expansion_map")
    if not isinstance(new_map, dict):
        abort(400, "expansion_map must be a dict.")

    # Validate: no AE-200 block may have more than 3 expansions
    parent_counts: dict = {}
    for child_idx, parent_idx in new_map.items():
        if parent_idx is not None:
            parent_counts[str(parent_idx)] = parent_counts.get(str(parent_idx), 0) + 1

    over_limit = [p for p, c in parent_counts.items() if c > 3]
    if over_limit:
        return jsonify({"ok": False, "error": "over_limit", "over_limit": over_limit}), 400

    sessions.update(sid, {"expansion_map": new_map})
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API — Download DSBX→DAT
# ---------------------------------------------------------------------------


@dsbx_bp.route("/api/download/dsbx-to-dat/<sid>")
def api_download_dsbx_to_dat(sid):
    s = require_session(sid, "dsbx")

    generate_blocks = request.args.get("generate_blocks", "1") != "0"

    # Determine target family from block controller types (auto-detect, no manual version selector)
    blocks = s.get("blocks", [])
    has_400 = any(b.get("controller_type") in {"AE-C400A", "EW-C50"} for b in blocks)
    target_family = "AE-C400A" if has_400 else "AE-200"

    try:
        results = dsbx_to_dat_bytes(s["dsbx_data"], target_family, generate_blocks=generate_blocks)
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


# ---------------------------------------------------------------------------
# API — Download DSBX→Multi-DAT (all controllers in one file)
# ---------------------------------------------------------------------------


@dsbx_bp.route("/api/download/dsbx-to-multi-dat/<sid>")
def api_download_dsbx_to_multi_dat(sid):
    s = require_session(sid, "dsbx")

    generate_blocks = request.args.get("generate_blocks", "1") != "0"
    # series=200 or series=400 limits the output to that family; unset = auto-detect
    series_filter = request.args.get("series")
    blocks = s.get("blocks", [])

    _400_TYPES = {"AE-C400A", "EW-C50"}
    _200_TYPES = {"AE-200", "EW-50"}

    if series_filter == "200":
        active_blocks = blocks
        target_family = "AE-200"
    elif series_filter == "400":
        active_blocks = blocks
        target_family = "AE-C400A"
    else:
        # Auto-detect: if any 400-series block exists, use 400 family
        has_400 = any(b.get("controller_type") in _400_TYPES for b in blocks)
        target_family = "AE-C400A" if has_400 else "AE-200"
        active_blocks = blocks

    try:
        results = dsbx_to_dat_bytes(s["dsbx_data"], target_family, generate_blocks=generate_blocks)
    except Exception:
        logger.error("Multi-DAT conversion failed", exc_info=True)
        abort(500, "Conversion failed. Please try again or contact support.")

    # Map results → blocks (dsbx_to_dat_bytes skips no-controller blocks)
    has_ctrl_indices = [i for i, b in enumerate(blocks) if b.get("has_controller", True)]

    controller_names = s.get("controller_names", {})
    group_names = s.get("group_names", {})

    processed = []
    for j, r in enumerate(results):
        block_idx = has_ctrl_indices[j] if j < len(has_ctrl_indices) else j
        block = blocks[block_idx] if block_idx < len(blocks) else {}
        xml_bytes = b""
        try:
            controllers = parse_dat_controllers(r["data"])
            if controllers:
                xml = controllers[0]["xml_bytes"]
                name = controller_names.get(str(block_idx))
                if name:
                    root = ET.fromstring(xml)
                    sd = root.find(".//SystemData")
                    if sd is not None:
                        sd.set("Name", name)
                    buf = io.BytesIO()
                    ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
                    xml = buf.getvalue()
                tag_map = group_names.get(str(block_idx), {})
                int_map = {int(k): v for k, v in tag_map.items()}
                if int_map:
                    xml = apply_group_names(xml, int_map)
                order = s.get(f"order_{block_idx}")
                if isinstance(order, list) and order:
                    xml = apply_rearrangement(xml, order)
                xml_bytes = xml
        except Exception:
            logger.warning("Multi-DAT edit failed for block %d", block_idx, exc_info=True)
            try:
                controllers = parse_dat_controllers(r["data"])
                xml_bytes = controllers[0]["xml_bytes"] if controllers else b""
            except Exception:
                xml_bytes = b""

        processed.append({
            "block_idx": block_idx,
            "xml_bytes": xml_bytes,
            "ip": block.get("ip", ""),
            "is_master": block.get("is_master", False),
            "controller_type": block.get("controller_type", r.get("controller", "")),
        })

    expansion_map = s.get("expansion_map", {})

    # Filter to the requested series when series_filter is set
    if series_filter == "200":
        processed = [p for p in processed if p["controller_type"] in _200_TYPES]
        use_400 = False
    elif series_filter == "400":
        processed = [p for p in processed if p["controller_type"] in _400_TYPES]
        use_400 = True
    else:
        use_400 = any(p["controller_type"] in _400_TYPES for p in processed)

    if not processed:
        abort(400, "No controllers of the requested series found in this session.")

    try:
        if not use_400:
            dat_bytes = _build_200_multi_dat(processed, blocks, expansion_map)
        else:
            dat_bytes = _build_400_multi_dat(processed)
    except Exception:
        logger.error("Multi-DAT packaging failed", exc_info=True)
        abort(500, "Multi-DAT packaging failed. Please try again or contact support.")

    base_name = s.get("dsbx_file_name", "export")
    return _send_dat(dat_bytes, f"{base_name}_central_controller.dat")


def _build_200_multi_dat(processed: list, blocks: list, expansion_map: dict) -> bytes:
    """Assign entry numbers and call build_multi_dat_200."""
    ae200_entries = [p for p in processed if p["controller_type"] == "AE-200"]
    ew50_entries = [p for p in processed if p["controller_type"] in {"EW-50"}]

    ae200_sorted = sorted(ae200_entries, key=lambda p: _ip_sort_key(p["ip"]))
    ew50_sorted = sorted(ew50_entries, key=lambda p: _ip_sort_key(p["ip"]))

    # Assign flat numbers to AE-200 mains
    ae200_flat = {p["block_idx"]: str(pos + 1) for pos, p in enumerate(ae200_sorted)}

    # Assign sub-numbers to EW-50 blocks based on expansion_map
    exp_counters = {}  # parent_block_idx → count of expansions assigned
    next_standalone = [len(ae200_sorted) + 1]
    controllers = []

    for p_ae in ae200_sorted:
        controllers.append({
            "entry": ae200_flat[p_ae["block_idx"]],
            "xml_bytes": p_ae["xml_bytes"],
            "ip": p_ae["ip"],
        })

    for p_ew in ew50_sorted:
        parent_str = expansion_map.get(str(p_ew["block_idx"]))
        if parent_str is not None:
            parent_block_idx = int(parent_str)
            parent_entry = ae200_flat.get(parent_block_idx)
            if parent_entry is not None:
                cnt = exp_counters.get(parent_block_idx, 0) + 1
                exp_counters[parent_block_idx] = cnt
                entry = f"{parent_entry}-{cnt}"
            else:
                entry = str(next_standalone[0])
                next_standalone[0] += 1
        else:
            entry = str(next_standalone[0])
            next_standalone[0] += 1

        controllers.append({
            "entry": entry,
            "xml_bytes": p_ew["xml_bytes"],
            "ip": p_ew["ip"],
        })

    controllers.sort(key=lambda c: tuple(int(x) for x in c["entry"].split("-")))
    return build_multi_dat_200(controllers)


def _build_400_multi_dat(processed: list) -> bytes:
    """Sort by IP, assign sequential entry numbers, call build_multi_dat_400."""
    sorted_p = sorted(processed, key=lambda p: _ip_sort_key(p["ip"]))

    # If no block is flagged as master, the first one is
    has_master = any(p["is_master"] for p in sorted_p)
    controllers = []
    for pos, p in enumerate(sorted_p):
        is_master = p["is_master"] if has_master else (pos == 0)
        controllers.append({
            "entry": str(pos + 1),
            "xml_bytes": p["xml_bytes"],
            "ip": p["ip"],
            "is_master": is_master,
        })

    return build_multi_dat_400(controllers)
