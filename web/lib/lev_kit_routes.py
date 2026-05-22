"""
LEV Kit tool routes — Flask Blueprint.

Routes for the LEV Kit Configurator: batch (DSBX upload → submittal PDF),
single-unit switch calculator, and manual-entry sessions.

Pattern note (B-11 — third blueprint extraction, following B-09 and B-10):
- Blueprint location: web/lib/lev_kit_routes.py (not web/blueprints/)
- Naming: <tool>_routes.py matching dat_routes, dsbx_routes pattern.
- Shared helpers: route-level helpers from web/lib/route_helpers.py.
  Domain functions stay in web/lib/lev_kit_utils.py (already 1830 lines —
  do NOT inline LEV Kit parsing/computation into routes).
- Session helpers: session CRUD called directly via `from . import sessions`.

Naming smell note (B-11):
  `api_session_get` is registered at `/api/session/<sid>` but is
  LEV-Kit-specific (calls `_lev_kit_session(sid)` internally). Its only
  caller is `web/static/js/lev_kit.js:543`. The URL should probably be
  `/api/lev-kit/session/<sid>`, but fixing it requires a frontend change
  too — tracked separately (candidate: B-XX rename).
"""

import io
import logging

from flask import Blueprint, abort, jsonify, render_template, request, send_file

from . import lev_kit_utils, sessions
from .route_helpers import _validate_upload
from .session_utils import require_session

logger = logging.getLogger(__name__)

lev_kit_bp = Blueprint("lev_kit", __name__)

# ---------------------------------------------------------------------------
# Flow (matches the upload->session->download pattern used by the rest of the app):
#
#   POST /api/upload/lev-kit            multipart .dsbx -> session + parsed units
#   POST /api/session/lev-kit-blank     create empty session for manual entry
#   POST /api/session/<sid>/lev-kit-update   persist edits from UI
#   GET  /api/download/lev-kit/<sid>?layout=horizontal|vertical    PDF
#   GET  /api/lev-kit/config-data       capacity/thermo/setpoint dropdown data
#   POST /api/lev-kit/compute-switches  stateless single-unit switch calc
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LEV_KIT_VOLTAGES = {"208", "230"}
LEV_KIT_LAYOUTS = {"horizontal", "vertical"}
LEV_KIT_REFRIGERANTS = {"ah001", "ah002", "both"}
LEV_KIT_CONTROLLER_TYPES = {
    lev_kit_utils.CONTROLLER_AH001,
    lev_kit_utils.CONTROLLER_AH002,
}

# Per-unit override fields accepted by build_unit_record() via **kwargs.
# tag, capacity_index, and control_mode live on the parsed_unit dict itself
# (the UI is the source of truth — the update route rebuilds parsed_units on
# every call) so they are NOT included here.
# AH001-specific fields (fan_controlled_by, run_fan_defrost, electric_heat,
# use_defrost_error, humidifier_installed, run_humidifier) ride through as
# overrides as well; build_unit_record ignores them on AH002 records.
LEV_KIT_OVERRIDE_KEYS = frozenset(
    {
        "heat_pump",
        "discharge_enable",
        "discharge_setpoint",
        "thermo_temp",
        "dat_setpoint",
        "return_control",
        "return_enable",
        "temp_adjustment",
        "fan_controlled_by",
        "run_fan_defrost",
        "electric_heat",
        "use_defrost_error",
        "humidifier_installed",
        "run_humidifier",
    }
)
LEV_KIT_CONTROL_MODES = {"discharge", "return"}
LEV_KIT_CAPACITY_RANGE = range(0, 21)
LEV_KIT_PROJECT_NAME_MAX = 120

# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _refrigerant_from_controllers(controllers_found: dict) -> str:
    """Derive UI refrigerant_selection from a controllers_found summary dict."""
    n_ah001 = controllers_found.get(lev_kit_utils.CONTROLLER_AH001, 0)
    n_ah002 = controllers_found.get(lev_kit_utils.CONTROLLER_AH002, 0)
    if n_ah001 and n_ah002:
        return "both"
    if n_ah001:
        return "ah001"
    return "ah002"


def _send_pdf(data_bytes, filename):
    return send_file(
        io.BytesIO(data_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


def _lev_kit_session(sid):
    return require_session(sid, "lev-kit")


def _lev_kit_filename(project_name):
    safe = (
        "".join(c if c.isalnum() or c in " -_" else "_" for c in (project_name or ""))
        .strip()
        .replace(" ", "_")
    )
    return f"{safe or 'LEV_Config'}_LEV_Kit_Config.pdf"


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@lev_kit_bp.route("/lev-kit-configurator")
def page_lev_kit():
    """LEV Kit landing page — shows the two-card chooser (Batch / Single Unit).

    Each card links to its dedicated page so the breadcrumb correctly reflects
    which workflow the user is in.
    """
    return render_template("site_lev_kit_chooser.html")


@lev_kit_bp.route("/lev-kit-batch")
def page_lev_kit_batch():
    """LEV Kit batch configurator — multi-unit DSBX upload + submittal PDF."""
    return render_template("site_lev_kit.html")


@lev_kit_bp.route("/lev-kit-single")
def page_lev_kit_single():
    return render_template("site_lev_kit_single.html")


@lev_kit_bp.route("/lev-kit-single/ah002")
def page_lev_kit_single_ah002():
    return render_template("site_lev_kit_single_ah002.html")


@lev_kit_bp.route("/lev-kit-single/ah001")
def page_lev_kit_single_ah001():
    return render_template("site_lev_kit_single_ah001.html")


# ---------------------------------------------------------------------------
# API — Session management
# ---------------------------------------------------------------------------


@lev_kit_bp.route("/api/session/lev-kit-blank", methods=["POST"])
def api_session_lev_kit_blank():
    sid = sessions.create(
        {
            "type": "lev-kit",
            "project_name": "",
            "parsed_units": [],
            "voltage": "208",
            "layout": "horizontal",
            "refrigerant_selection": "ah002",  # manual default = R-32
            "overrides": {},
            "controllers_found": {
                lev_kit_utils.CONTROLLER_AH001: 0,
                lev_kit_utils.CONTROLLER_AH002: 0,
            },
            "warnings": [],
        }
    )
    return jsonify(
        {
            "session_id": sid,
            "project_name": "",
            "units": [],
            "refrigerant_selection": "ah002",
            "controllers_found": {
                lev_kit_utils.CONTROLLER_AH001: 0,
                lev_kit_utils.CONTROLLER_AH002: 0,
            },
            "warnings": [],
        }
    )


@lev_kit_bp.route("/api/session/<sid>", methods=["GET"])
def api_session_get(sid):
    """Return full session data so the frontend can restore saved overrides.

    Naming smell (B-11): this URL /api/session/<sid> is LEV-Kit-specific
    (calls _lev_kit_session internally) but the URL pattern suggests a
    generic session endpoint. Its only caller is lev_kit.js:543.
    Rename to /api/lev-kit/session/<sid> tracked separately.
    """
    s = _lev_kit_session(sid)
    return jsonify(
        {
            "session_id": sid,
            "project_name": s.get("project_name", ""),
            "units": s.get("parsed_units", []),
            "overrides": s.get("overrides", {}),
            "voltage": s.get("voltage", "208"),
            "layout": s.get("layout", "horizontal"),
            "refrigerant_selection": s.get("refrigerant_selection", "ah002"),
            "controllers_found": s.get("controllers_found", {}),
            "warnings": s.get("warnings", []),
        }
    )


# ---------------------------------------------------------------------------
# API — Upload
# ---------------------------------------------------------------------------


@lev_kit_bp.route("/api/upload/lev-kit", methods=["POST"])
def api_upload_lev_kit():
    data, _ext = _validate_upload(request.files.get("file"), {".dsbx"})
    try:
        parsed = lev_kit_utils.parse_dsbx(data)
    except ValueError as exc:
        logger.warning("Could not read .dsbx file", exc_info=True)
        abort(400, "Could not read the .dsbx file. Please verify it is a valid DSBX export.")

    if not parsed["units"]:
        abort(400, "No LEV Kits (PAC-AH001 or PAC-AH002) found in this project.")

    refrigerant_selection = _refrigerant_from_controllers(parsed["controllers_found"])

    sid = sessions.create(
        {
            "type": "lev-kit",
            "project_name": parsed["project_name"],
            "parsed_units": parsed["units"],
            "voltage": "208",
            "layout": "horizontal",
            "refrigerant_selection": refrigerant_selection,
            "overrides": {},
            "controllers_found": parsed["controllers_found"],
            "warnings": parsed["warnings"],
        }
    )
    return jsonify(
        {
            "session_id": sid,
            "project_name": parsed["project_name"],
            "units": parsed["units"],
            "refrigerant_selection": refrigerant_selection,
            "controllers_found": parsed["controllers_found"],
            "warnings": parsed["warnings"],
        }
    )


# ---------------------------------------------------------------------------
# API — Update
# ---------------------------------------------------------------------------


@lev_kit_bp.route("/api/session/<sid>/lev-kit-update", methods=["POST"])
def api_lev_kit_update(sid):
    s = _lev_kit_session(sid)
    body = request.get_json(silent=True) or {}

    voltage = str(body.get("voltage", s["voltage"]))
    layout = str(body.get("layout", s["layout"]))
    if voltage not in LEV_KIT_VOLTAGES:
        abort(400, f"Voltage must be one of {sorted(LEV_KIT_VOLTAGES)}.")
    if layout not in LEV_KIT_LAYOUTS:
        abort(400, f"Layout must be one of {sorted(LEV_KIT_LAYOUTS)}.")

    refrigerant_selection = str(
        body.get("refrigerant_selection", s.get("refrigerant_selection", "ah002"))
    )
    if refrigerant_selection not in LEV_KIT_REFRIGERANTS:
        abort(400, f"refrigerant_selection must be one of {sorted(LEV_KIT_REFRIGERANTS)}.")

    project_name = str(body.get("project_name", s.get("project_name", ""))).strip()
    project_name = project_name[:LEV_KIT_PROJECT_NAME_MAX]

    prior_parsed = s["parsed_units"]
    # Map old tag → mnet so we can preserve M-Net addresses across rename/reorder.
    prior_mnet_by_tag = {p.get("tag"): p.get("mnet") for p in prior_parsed if p.get("tag")}

    new_parsed: list[dict] = []
    new_overrides: dict[str, dict] = {}

    for i, entry in enumerate(body.get("units") or []):
        tag = str(entry.get("tag") or "").strip()
        if not tag:
            continue

        try:
            cap_idx = int(entry.get("capacity", 0))
        except (TypeError, ValueError):
            abort(400, f"Unit '{tag}': capacity must be an integer.")
        if cap_idx not in LEV_KIT_CAPACITY_RANGE:
            abort(400, f"Unit '{tag}': capacity index out of range.")

        control_mode = entry.get("control_mode", "discharge")
        if control_mode not in LEV_KIT_CONTROL_MODES:
            abort(400, f"Unit '{tag}': control_mode must be 'discharge' or 'return'.")

        # Controller type defaults to AH002 for in-flight pre-migration sessions
        controller_type = entry.get("controller_type", lev_kit_utils.CONTROLLER_AH002)
        if controller_type not in LEV_KIT_CONTROLLER_TYPES:
            abort(400, f"Unit '{tag}': controller_type must be PAC-AH001 or PAC-AH002.")

        # Preserve mnet from the prior session (lookup by tag, falling back to
        # positional matching for legacy sessions where parsed_units had no tags)
        mnet = prior_mnet_by_tag.get(tag)
        if mnet is None and i < len(prior_parsed):
            mnet = prior_parsed[i].get("mnet")

        new_parsed.append(
            {
                "tag": tag,
                "capacity_index": cap_idx,
                "control_mode": control_mode,
                "mnet": mnet,
                "controller_type": controller_type,
            }
        )
        new_overrides[tag] = {k: entry[k] for k in LEV_KIT_OVERRIDE_KEYS if k in entry}

    sessions.update(
        sid,
        {
            "voltage": voltage,
            "layout": layout,
            "project_name": project_name,
            "parsed_units": new_parsed,
            "overrides": new_overrides,
            "refrigerant_selection": refrigerant_selection,
        },
    )
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API — Download (PDF)
# ---------------------------------------------------------------------------


@lev_kit_bp.route("/api/download/lev-kit/<sid>", methods=["GET"])
def api_download_lev_kit(sid):
    s = _lev_kit_session(sid)
    layout = request.args.get("layout", s.get("layout", "horizontal"))
    if layout not in LEV_KIT_LAYOUTS:
        abort(400, f"Layout must be one of {sorted(LEV_KIT_LAYOUTS)}.")
    voltage = s.get("voltage", "208")

    records = []
    for parsed in s["parsed_units"]:
        ovr = s["overrides"].get(parsed["tag"], {})
        records.append(
            lev_kit_utils.build_unit_record(
                parsed,
                input_voltage=voltage,
                **ovr,
            )
        )

    try:
        pdf_bytes = lev_kit_utils.render_submittal_pdf(
            records,
            project_name=s["project_name"],
            voltage=voltage,
            layout=layout,
            refrigerant_selection=s.get("refrigerant_selection", "ah002"),
        )
    except Exception as exc:
        logger.error("PDF generation failed", exc_info=True)
        abort(500, "PDF generation failed. Please try again or contact support.")

    return _send_pdf(pdf_bytes, _lev_kit_filename(s["project_name"]))


# ---------------------------------------------------------------------------
# API — Config data + switch calculator
# ---------------------------------------------------------------------------


@lev_kit_bp.route("/api/lev-kit/config-data", methods=["GET"])
def api_lev_kit_config_data():
    return jsonify(
        {
            # Top-level keys remain for back-compat (AH002 callers consume these directly)
            "capacityOptions": lev_kit_utils.CAPACITY_OPTIONS,
            "thermoOptions": lev_kit_utils.THERMO_OPTIONS,
            "heatingSetpointOptions": lev_kit_utils.HEATING_SETPOINT_OPTIONS,
            # Per-controller subtrees for clients that need both
            "controllers": {
                lev_kit_utils.CONTROLLER_AH002: {
                    "label": "PAC-AH002 (R-32)",
                    "capacityOptions": lev_kit_utils.CAPACITY_OPTIONS,
                    "thermoOptions": lev_kit_utils.THERMO_OPTIONS,
                    "heatingSetpointOptions": lev_kit_utils.HEATING_SETPOINT_OPTIONS,
                    "switchBanks": lev_kit_utils.SWITCH_BANKS,
                },
                lev_kit_utils.CONTROLLER_AH001: {
                    "label": "PAC-AH001 (R-410A)",
                    "capacityOptions": lev_kit_utils.CAPACITY_OPTIONS_AH001,
                    "thermoOptions": lev_kit_utils.THERMO_OPTIONS_AH001,
                    "heatingSetpointOptions": lev_kit_utils.DAT_SETPOINT_OPTIONS_AH001,
                    "switchBanks": lev_kit_utils.SWITCH_BANKS_AH001,
                },
            },
        }
    )


@lev_kit_bp.route("/api/lev-kit/compute-switches", methods=["POST"])
def api_lev_kit_compute_switches():
    body = request.get_json(force=True) or {}
    controller_type = body.get("controllerType", lev_kit_utils.CONTROLLER_AH002)
    if controller_type not in LEV_KIT_CONTROLLER_TYPES:
        abort(400, "controllerType must be PAC-AH001 or PAC-AH002.")

    is_ah001 = controller_type == lev_kit_utils.CONTROLLER_AH001

    # Defaults differ per controller: AH001 thermo default = 4 (59°F), dat = 1 (82°F upper)
    default_thermo = 4 if is_ah001 else 0
    default_dat = 1 if is_ah001 else 2

    config = {
        "controller_type": controller_type,
        "capacity": body.get("capacity", 0),
        "control_mode": body.get("controlMode", "discharge"),
        "heat_pump": body.get("heatPump", True),
        "input_voltage": body.get("inputVoltage", "208"),
        "discharge_enable": body.get("dischargeEnableType", "central"),
        "discharge_setpoint": body.get("dischargeSetpointType", "central"),
        "thermo_temp": body.get("thermoTemp", default_thermo),
        "dat_setpoint": body.get("datSetpoint", default_dat),
        "return_control": body.get("returnControl", "rat"),
        "return_enable": body.get("returnEnableMethod", "central"),
        "temp_adjustment": bool(body.get("tempAdjustment", False)),
    }
    if is_ah001:
        config.update(
            {
                "fan_controlled_by": body.get("fanControlledBy", "bas"),
                "run_fan_defrost": bool(body.get("runFanDefrost", False)),
                "electric_heat": bool(body.get("electricHeat", False)),
                "use_defrost_error": bool(body.get("useDefrostError", False)),
                "humidifier_installed": bool(body.get("humidifierInstalled", False)),
                "run_humidifier": bool(body.get("runHumidifier", False)),
            }
        )

    result = lev_kit_utils.generate_switch_positions(config)
    return jsonify(
        {
            "switches": result["switches"],
            "cnrmConnected": result["cnrm_connected"],
        }
    )
