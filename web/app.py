"""
Central Controller Config Tools — Flask web application.
"""
import base64
import io
import os
import xml.etree.ElementTree as ET
import zipfile

import requests as req_lib
from flask import (Flask, Response, jsonify, render_template, request,
                   send_file, abort)

from lib import sessions
from lib import lev_kit_utils
from lib.dat_utils import (
    convert_dat_bytes, detect_controller_type, extract_groups_from_xml,
    parse_dat_controllers, rearrange_and_repackage_dat_bytes,
    rearrange_and_split_dat_bytes, rearrange_and_convert_dat_bytes,
    sort_groups_by_tag, split_dat_bytes, _check_warnings, _safe_filename,
)
from lib.dsbx_utils import (
    dsbx_to_dat_bytes, extract_group_cards, get_groupof50_list,
    load_mapping, parse_dsbx_bytes,
)
from lib.json_utils import export_session_json, import_session_json
from lib.agent_routes import agent_bp

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-fallback-key-change-in-prod")
app.register_blueprint(agent_bp)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXT = {".dsbx", ".dat"}
MTDZ_BACKEND = os.environ.get("MTDZ_BACKEND_URL", "http://mtdz-backend:8000")

# Deployment environment label — "prod" or "test". Read by /status and exposed
# to templates so the frontend banner script knows which container it's in.
APP_ENV = os.environ.get("APP_ENV", "test")
SIGNAL_FILE = os.environ.get("RESTART_SIGNAL_FILE", "/app/signals/restart.json")

# Feature flag — new DAT↔JSON tool is only active on the codetest subdomain.
# Hostname check is the primary gate (both domains hit the same container).
# CODETEST env var acts as an override for local development.
_CODETEST_ENV = os.environ.get("CODETEST", "0") == "1"


def _is_codetest() -> bool:
    """True when the request is coming from codetest.vrftools.com (or CODETEST env)."""
    return _CODETEST_ENV or request.host.startswith("codetest.")


@app.context_processor
def inject_globals():
    return {"codetest": _is_codetest(), "app_env": APP_ENV}


def _read_restart_signal() -> str | None:
    """Return ISO timestamp of an upcoming restart, or None if none scheduled."""
    try:
        with open(SIGNAL_FILE, "r") as f:
            import json as _json
            data = _json.load(f)
        ts = data.get("restart_at")
        return ts if isinstance(ts, str) and ts else None
    except (FileNotFoundError, ValueError, OSError):
        return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _preloaded_session(expected_type: str) -> str | None:
    """Return a valid session ID from ?session= if CODETEST and type matches."""
    if not _is_codetest():
        return None
    sid = request.args.get("session")
    if not sid:
        return None
    s = sessions.get(sid)
    if s and s.get("type") == expected_type:
        return sid
    return None


def _validate_upload(file, allowed=None):
    """Validate size and extension; return (bytes, ext) or raise."""
    if not file or file.filename == "":
        abort(400, "No file provided.")
    data = file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        abort(400, "File exceeds 5 MB limit.")
    ext = os.path.splitext(file.filename)[1].lower()
    if allowed and ext not in allowed:
        abort(400, f"Expected {' or '.join(sorted(allowed))} file, got {ext!r}.")
    return data, ext


def _zip_results(results: list) -> bytes:
    """Package a list of {"name", "data"} dicts into a ZIP archive."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for r in results:
            zf.writestr(r["name"] + ".dat", r["data"])
    return buf.getvalue()


def _send_dat(data: bytes, filename: str):
    return send_file(
        io.BytesIO(data),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=filename,
    )


def _send_zip(data: bytes, filename: str):
    return send_file(
        io.BytesIO(data),
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
    )


def _rebuild_dat_with_names(dat_data: bytes, blocks: list, group_names_by_block: dict) -> bytes:
    """
    Rebuild a .dat file with updated controller names (from blocks)
    and group tag names (from group_names_by_block).
    Returns new .dat bytes, or the original if nothing changed.
    """
    from lib.dat_utils import generate_dat_bytes, apply_group_names
    from lib.zipcrypto import build_dat_bytes, PASSWORD

    controllers = parse_dat_controllers(dat_data)
    changed = False

    for i, ctrl in enumerate(controllers):
        xml = ctrl["xml_bytes"]

        # Apply controller name
        if i < len(blocks):
            new_name = blocks[i].get("name", "")
            if new_name and new_name != ctrl.get("name", ""):
                try:
                    root = ET.fromstring(xml)
                    sd = root.find(".//SystemData")
                    if sd is not None:
                        sd.set("Name", new_name)
                    buf = io.BytesIO()
                    ET.ElementTree(root).write(buf, encoding="utf-8", xml_declaration=True)
                    xml = buf.getvalue()
                    ctrl["name"] = new_name
                    changed = True
                except ET.ParseError:
                    pass

        # Apply group tag names
        tag_map = group_names_by_block.get(str(i), {})
        int_map = {int(k): v for k, v in tag_map.items()}
        if int_map:
            xml = apply_group_names(xml, int_map)
            changed = True

        ctrl["xml_bytes"] = xml

    if not changed:
        return dat_data

    entries = []
    for ctrl in controllers:
        entries.append((ctrl["entry"], ctrl["xml_bytes"], True))

    with pyzipper.AESZipFile(io.BytesIO(dat_data)) as z:
        ctrl_entry_names = {c["entry"] for c in controllers}
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

@app.route("/status")
def status():
    """Liveness + restart-window probe. Read by Docker healthcheck and the
    frontend banner poller. Cheap by design: no DB, no template render."""
    return jsonify({
        "ok": True,
        "env": APP_ENV,
        "restart_at": _read_restart_signal(),
    })


@app.route("/")
def index():
    return render_template("site_index.html")


@app.route("/config-tools")
def page_config_tools():
    return render_template("index.html")


@app.route("/contact")
def page_contact():
    return render_template("site_contact.html")


@app.route("/lev-kit-configurator")
def page_lev_kit():
    """LEV Kit landing page — shows the two-card chooser (Batch / Single Unit).

    Each card links to its dedicated page so the breadcrumb correctly reflects
    which workflow the user is in.
    """
    return render_template("site_lev_kit_chooser.html")


@app.route("/lev-kit-batch")
def page_lev_kit_batch():
    """LEV Kit batch configurator — multi-unit DSBX upload + submittal PDF."""
    return render_template("site_lev_kit.html")


@app.route("/lev-kit-single")
def page_lev_kit_single():
    return render_template("site_lev_kit_single.html")


@app.route("/lev-kit-single/ah002")
def page_lev_kit_single_ah002():
    return render_template("site_lev_kit_single_ah002.html")


@app.route("/lev-kit-single/ah001")
def page_lev_kit_single_ah001():
    return render_template("site_lev_kit_single_ah001.html")


# ============================================================================
# LEV Kit Configurator — routes added 2026-05-10
# ============================================================================
#
# Flow (matches the upload->session->download pattern used by the rest of the app):
#
#   POST /api/upload/lev-kit            multipart .dsbx -> session + parsed units
#   POST /api/session/lev-kit-blank     create empty session for manual entry
#   POST /api/session/<sid>/lev-kit-update   persist edits from UI
#   GET  /api/download/lev-kit/<sid>?layout=horizontal|vertical    PDF
#   GET  /api/lev-kit/config-data       capacity/thermo/setpoint dropdown data
#   POST /api/lev-kit/compute-switches  stateless single-unit switch calc
# ============================================================================

import io as _io_lev_kit

LEV_KIT_VOLTAGES = {"208", "230"}
LEV_KIT_LAYOUTS  = {"horizontal", "vertical"}
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
LEV_KIT_OVERRIDE_KEYS = frozenset({
    "heat_pump",
    "discharge_enable", "discharge_setpoint",
    "thermo_temp", "dat_setpoint",
    "return_control", "return_enable", "temp_adjustment",
    "fan_controlled_by", "run_fan_defrost",
    "electric_heat", "use_defrost_error",
    "humidifier_installed", "run_humidifier",
})
LEV_KIT_CONTROL_MODES = {"discharge", "return"}
LEV_KIT_CAPACITY_RANGE = range(0, 21)
LEV_KIT_PROJECT_NAME_MAX = 120


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
        _io_lev_kit.BytesIO(data_bytes),
        mimetype="application/pdf",
        as_attachment=True,
        download_name=filename,
    )


def _lev_kit_session(sid):
    s = sessions.get(sid)
    if not s or s.get("type") != "lev-kit":
        abort(404, "Session not found or expired.")
    return s


def _lev_kit_filename(project_name):
    safe = "".join(
        c if c.isalnum() or c in " -_" else "_"
        for c in (project_name or "")
    ).strip().replace(" ", "_")
    return f"{safe or 'LEV_Config'}_LEV_Kit_Config.pdf"


@app.route("/api/session/lev-kit-blank", methods=["POST"])
def api_session_lev_kit_blank():
    sid = sessions.create({
        "type":                  "lev-kit",
        "project_name":          "",
        "parsed_units":          [],
        "voltage":               "208",
        "layout":                "horizontal",
        "refrigerant_selection": "ah002",   # manual default = R-32
        "overrides":             {},
        "controllers_found":     {lev_kit_utils.CONTROLLER_AH001: 0,
                                  lev_kit_utils.CONTROLLER_AH002: 0},
        "warnings":              [],
    })
    return jsonify({
        "session_id":            sid,
        "project_name":          "",
        "units":                 [],
        "refrigerant_selection": "ah002",
        "controllers_found":     {lev_kit_utils.CONTROLLER_AH001: 0,
                                  lev_kit_utils.CONTROLLER_AH002: 0},
        "warnings":              [],
    })


@app.route("/api/upload/lev-kit", methods=["POST"])
def api_upload_lev_kit():
    data, _ext = _validate_upload(request.files.get("file"), {".dsbx"})
    try:
        parsed = lev_kit_utils.parse_dsbx(data)
    except ValueError as exc:
        abort(400, f"Could not read .dsbx file: {exc}")

    if not parsed["units"]:
        abort(400, "No LEV Kits (PAC-AH001 or PAC-AH002) found in this project.")

    refrigerant_selection = _refrigerant_from_controllers(parsed["controllers_found"])

    sid = sessions.create({
        "type":                  "lev-kit",
        "project_name":          parsed["project_name"],
        "parsed_units":          parsed["units"],
        "voltage":               "208",
        "layout":                "horizontal",
        "refrigerant_selection": refrigerant_selection,
        "overrides":             {},
        "controllers_found":     parsed["controllers_found"],
        "warnings":              parsed["warnings"],
    })
    return jsonify({
        "session_id":            sid,
        "project_name":          parsed["project_name"],
        "units":                 parsed["units"],
        "refrigerant_selection": refrigerant_selection,
        "controllers_found":     parsed["controllers_found"],
        "warnings":              parsed["warnings"],
    })


@app.route("/api/session/<sid>/lev-kit-update", methods=["POST"])
def api_lev_kit_update(sid):
    s = _lev_kit_session(sid)
    body = request.get_json(silent=True) or {}

    voltage = str(body.get("voltage", s["voltage"]))
    layout  = str(body.get("layout",  s["layout"]))
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

        new_parsed.append({
            "tag":             tag,
            "capacity_index":  cap_idx,
            "control_mode":    control_mode,
            "mnet":            mnet,
            "controller_type": controller_type,
        })
        new_overrides[tag] = {
            k: entry[k] for k in LEV_KIT_OVERRIDE_KEYS if k in entry
        }

    sessions.update(sid, {
        "voltage":               voltage,
        "layout":                layout,
        "project_name":          project_name,
        "parsed_units":          new_parsed,
        "overrides":             new_overrides,
        "refrigerant_selection": refrigerant_selection,
    })
    return jsonify({"ok": True})


@app.route("/api/download/lev-kit/<sid>", methods=["GET"])
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
        abort(500, f"PDF generation failed: {exc}")

    return _send_pdf(pdf_bytes, _lev_kit_filename(s["project_name"]))


@app.route("/api/lev-kit/config-data", methods=["GET"])
def api_lev_kit_config_data():
    return jsonify({
        # Top-level keys remain for back-compat (AH002 callers consume these directly)
        "capacityOptions":        lev_kit_utils.CAPACITY_OPTIONS,
        "thermoOptions":          lev_kit_utils.THERMO_OPTIONS,
        "heatingSetpointOptions": lev_kit_utils.HEATING_SETPOINT_OPTIONS,
        # Per-controller subtrees for clients that need both
        "controllers": {
            lev_kit_utils.CONTROLLER_AH002: {
                "label":                  "PAC-AH002 (R-32)",
                "capacityOptions":        lev_kit_utils.CAPACITY_OPTIONS,
                "thermoOptions":          lev_kit_utils.THERMO_OPTIONS,
                "heatingSetpointOptions": lev_kit_utils.HEATING_SETPOINT_OPTIONS,
                "switchBanks":            lev_kit_utils.SWITCH_BANKS,
            },
            lev_kit_utils.CONTROLLER_AH001: {
                "label":                  "PAC-AH001 (R-410A)",
                "capacityOptions":        lev_kit_utils.CAPACITY_OPTIONS_AH001,
                "thermoOptions":          lev_kit_utils.THERMO_OPTIONS_AH001,
                "heatingSetpointOptions": lev_kit_utils.DAT_SETPOINT_OPTIONS_AH001,
                "switchBanks":            lev_kit_utils.SWITCH_BANKS_AH001,
            },
        },
    })


@app.route("/api/lev-kit/compute-switches", methods=["POST"])
def api_lev_kit_compute_switches():
    body = request.get_json(force=True) or {}
    controller_type = body.get("controllerType", lev_kit_utils.CONTROLLER_AH002)
    if controller_type not in LEV_KIT_CONTROLLER_TYPES:
        abort(400, "controllerType must be PAC-AH001 or PAC-AH002.")

    is_ah001 = controller_type == lev_kit_utils.CONTROLLER_AH001

    # Defaults differ per controller: AH001 thermo default = 4 (59°F), dat = 1 (82°F upper)
    default_thermo = 4 if is_ah001 else 0
    default_dat    = 1 if is_ah001 else 2

    config = {
        "controller_type":    controller_type,
        "capacity":           body.get("capacity", 0),
        "control_mode":       body.get("controlMode", "discharge"),
        "heat_pump":          body.get("heatPump", True),
        "input_voltage":      body.get("inputVoltage", "208"),
        "discharge_enable":   body.get("dischargeEnableType", "central"),
        "discharge_setpoint": body.get("dischargeSetpointType", "central"),
        "thermo_temp":        body.get("thermoTemp", default_thermo),
        "dat_setpoint":       body.get("datSetpoint", default_dat),
        "return_control":     body.get("returnControl", "rat"),
        "return_enable":      body.get("returnEnableMethod", "central"),
        "temp_adjustment":    bool(body.get("tempAdjustment", False)),
    }
    if is_ah001:
        config.update({
            "fan_controlled_by":    body.get("fanControlledBy", "bas"),
            "run_fan_defrost":      bool(body.get("runFanDefrost", False)),
            "electric_heat":        bool(body.get("electricHeat", False)),
            "use_defrost_error":    bool(body.get("useDefrostError", False)),
            "humidifier_installed": bool(body.get("humidifierInstalled", False)),
            "run_humidifier":       bool(body.get("runHumidifier", False)),
        })

    result = lev_kit_utils.generate_switch_positions(config)
    return jsonify({
        "switches":      result["switches"],
        "cnrmConnected": result["cnrm_connected"],
    })


@app.route("/disclaimer")
def page_disclaimer():
    return render_template("disclaimer.html")


@app.route("/mtdz/")
def page_mtdz_index():
    return render_template("mtdz/index.html")


@app.route("/mtdz/viewer")
def page_mtdz_viewer():
    return render_template("mtdz/viewer.html")


@app.route("/mtdz/report")
def page_mtdz_report():
    return render_template("mtdz/report.html")


@app.route("/mtdz/sysinfo")
def page_mtdz_sysinfo():
    return render_template("mtdz/sysinfo.html")


@app.route("/dsbx-to-dat")
def page_dsbx_to_dat():
    preloaded = _preloaded_session("dsbx")
    return render_template("dsbx_to_dat.html", preloaded_session=preloaded)


@app.route("/rearranger")
def page_rearranger():
    preloaded = _preloaded_session("dat")
    return render_template("rearranger.html", preloaded_session=preloaded)


@app.route("/convert")
def page_convert():
    preloaded = _preloaded_session("dat")
    return render_template("convert.html", preloaded_session=preloaded)


@app.route("/split")
def page_split():
    preloaded = _preloaded_session("dat")
    return render_template("split.html", preloaded_session=preloaded)


@app.route("/docs")
def page_docs():
    return render_template("docs.html")





# ---------------------------------------------------------------------------
# API — DSBX to DAT
# ---------------------------------------------------------------------------

@app.route("/api/upload/dsbx", methods=["POST"])
def api_upload_dsbx():
    data, _ = _validate_upload(request.files.get("file"), {".dsbx"})

    # Validate it's a ZIP
    if not data[:4] == b"PK\x03\x04":
        abort(400, "File does not appear to be a valid .dsbx archive.")

    try:
        mapping   = load_mapping()
        dsb_root  = parse_dsbx_bytes(data)
        g50_list  = get_groupof50_list(dsb_root)
    except Exception as e:
        abort(400, f"Could not parse .dsbx file: {e}")

    blocks = []
    for g50 in g50_list:
        cards = extract_group_cards(g50, mapping)
        blocks.append({
            "name":     g50.findtext("Name") or "",
            "groups":   cards,
            "warnings": _check_warnings(cards),
        })

    sid = sessions.create({
        "type":      "dsbx",
        "dsbx_data": data,
        "blocks":    blocks,
    })

    return jsonify({"session_id": sid, "blocks": blocks})


@app.route("/api/session/<sid>/groups", methods=["GET"])
def api_get_groups(sid):
    s = sessions.get(sid)
    if not s:
        abort(404, "Session not found or expired.")
    return jsonify({"blocks": s.get("blocks", [])})


@app.route("/api/session/<sid>/groups", methods=["POST"])
def api_update_groups(sid):
    """Accept rearranged group order for a DSBX block or DAT."""
    s = sessions.get(sid)
    if not s:
        abort(404, "Session not found or expired.")

    body      = request.get_json(force=True) or {}
    new_order = body.get("new_order")       # list of old slot numbers
    block_idx = body.get("block_index", 0)  # which Groupof50 block (dsbx only)

    if not isinstance(new_order, list):
        abort(400, "new_order must be a list of slot numbers.")

    sessions.update(sid, {f"order_{block_idx}": new_order})
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# API — Download DSBX→DAT
# ---------------------------------------------------------------------------

@app.route("/api/download/dsbx-to-dat/<sid>")
def api_download_dsbx_to_dat(sid):
    s = sessions.get(sid)
    if not s or s.get("type") != "dsbx":
        abort(404, "Session not found or expired.")

    version = request.args.get("version", "AE-C400A")
    if version not in ("AE-C400A", "AE-200"):
        abort(400, "version must be AE-C400A or AE-200.")

    try:
        results = dsbx_to_dat_bytes(s["dsbx_data"], version)
    except Exception as e:
        abort(500, f"Conversion failed: {e}")

    # Apply any user rearrangements
    from lib.dat_utils import apply_rearrangement
    for i, r in enumerate(results):
        order = s.get(f"order_{i}")
        if order:
            try:
                import xml.etree.ElementTree as ET
                import pyzipper
                from lib.zipcrypto import PASSWORD
                from lib.dat_utils import generate_dat_bytes, parse_dat_controllers
                controllers = parse_dat_controllers(r["data"])
                if controllers:
                    new_xml = apply_rearrangement(controllers[0]["xml_bytes"], order)
                    r["data"] = generate_dat_bytes(new_xml, r["controller"])
            except Exception:
                pass  # rearrangement failure is non-fatal

    # Apply user-edited controller names and group tag names
    blocks = s.get("blocks", [])
    group_names_by_block = s.get("group_names", {})
    for i, r in enumerate(results):
        try:
            r["data"] = _rebuild_dat_with_names(r["data"], blocks[i:i+1], {str(i): group_names_by_block.get(str(i), {})})
        except Exception:
            pass  # name application failure is non-fatal

    if len(results) == 1:
        r = results[0]
        return _send_dat(r["data"], r["name"] + ".dat")

    return _send_zip(_zip_results(results), "dsbx_export.zip")


# ---------------------------------------------------------------------------
# API — DAT upload (shared by rearranger, convert, split)
# ---------------------------------------------------------------------------

@app.route("/api/upload/dat", methods=["POST"])
def api_upload_dat():
    data, _ = _validate_upload(request.files.get("file"), {".dat"})

    if not data[:4] == b"PK\x03\x04":
        abort(400, "File does not appear to be a valid .dat archive.")

    try:
        controllers = parse_dat_controllers(data)
    except Exception as e:
        abort(400, f"Could not parse .dat file: {e}")

    if not controllers:
        abort(400, "No controller data found in this .dat file.")

    blocks = []
    for ctrl in controllers:
        cards = extract_groups_from_xml(ctrl["xml_bytes"])
        blocks.append({
            "name":            ctrl["name"],
            "controller_type": ctrl["controller_type"],
            "groups":          cards,
            "warnings":        _check_warnings(cards),
        })

    sid = sessions.create({
        "type":      "dat",
        "dat_data":  data,
        "blocks":    blocks,
        "multi":     len(controllers) > 1,
    })

    return jsonify({
        "session_id": sid,
        "blocks":     blocks,
        "multi":      len(controllers) > 1,
    })


# ---------------------------------------------------------------------------
# API — Config Hub unified upload (codetest feature)
# ---------------------------------------------------------------------------

@app.route("/api/upload/config-hub", methods=["POST"])
def api_upload_config_hub():
    if not _is_codetest():
        abort(404)

    data, ext = _validate_upload(request.files.get("file"), {".dsbx", ".dat", ".json"})

    # --- .json: restore session, return redirect to originating tool ---
    if ext == ".json":
        secret = app.secret_key if isinstance(app.secret_key, bytes) else app.secret_key.encode()
        try:
            payload = import_session_json(data, secret)
        except ValueError as e:
            abort(400, str(e))

        tool = payload.get("tool", "dat-json")
        source_bytes = base64.b64decode(payload.get("source_b64", ""))
        orders = payload.get("orders", {})
        controller_names = payload.get("controller_names", {})
        group_names = payload.get("group_names", {})

        if tool == "dsbx-to-dat":
            if not source_bytes[:4] == b"PK\x03\x04":
                abort(400, "Stored source data does not appear to be a valid .dsbx archive.")
            try:
                mapping = load_mapping()
                dsb_root = parse_dsbx_bytes(source_bytes)
                g50_list = get_groupof50_list(dsb_root)
            except Exception as e:
                abort(400, f"Could not restore session: {e}")

            blocks = []
            for g50 in g50_list:
                cards = extract_group_cards(g50, mapping)
                blocks.append({
                    "name": g50.findtext("Name") or "",
                    "groups": cards,
                    "warnings": _check_warnings(cards),
                })
            session_data = {"type": "dsbx", "dsbx_data": source_bytes, "blocks": blocks}
        else:
            if not source_bytes[:4] == b"PK\x03\x04":
                abort(400, "Stored source data does not appear to be a valid .dat archive.")
            try:
                controllers = parse_dat_controllers(source_bytes)
            except Exception as e:
                abort(400, f"Could not restore session: {e}")

            if not controllers:
                abort(400, "No controller data found in stored source.")

            blocks = []
            for ctrl in controllers:
                cards = extract_groups_from_xml(ctrl["xml_bytes"])
                blocks.append({
                    "name": ctrl["name"],
                    "controller_type": ctrl["controller_type"],
                    "groups": cards,
                    "warnings": _check_warnings(cards),
                })

            session_type = "dat-json" if tool == "dat-json" else "dat"
            session_data = {
                "type": session_type,
                "dat_data": source_bytes,
                "blocks": blocks,
                "multi": len(controllers) > 1,
            }

        for idx_str, order in orders.items():
            session_data[f"order_{idx_str}"] = order
        if controller_names:
            session_data["controller_names"] = controller_names
        if group_names:
            session_data["group_names"] = group_names

        sid = sessions.create(session_data)
        redirect_url = _TOOL_ROUTES.get(tool, "/rearranger") + f"?session={sid}"
        return jsonify({
            "session_id": sid,
            "redirect": redirect_url,
        })

    # --- .dsbx: create session, return applicable tool list ---
    if ext == ".dsbx":
        if not data[:4] == b"PK\x03\x04":
            abort(400, "File does not appear to be a valid .dsbx archive.")
        try:
            mapping = load_mapping()
            dsb_root = parse_dsbx_bytes(data)
            g50_list = get_groupof50_list(dsb_root)
        except Exception as e:
            abort(400, f"Could not parse .dsbx file: {e}")

        blocks = []
        for g50 in g50_list:
            cards = extract_group_cards(g50, mapping)
            blocks.append({
                "name": g50.findtext("Name") or "",
                "groups": cards,
                "warnings": _check_warnings(cards),
            })

        sid = sessions.create({
            "type": "dsbx",
            "dsbx_data": data,
            "blocks": blocks,
        })
        return jsonify({
            "session_id": sid,
            "applicable_tools": ["dsbx-to-dat"],
            "blocks": blocks,
        })

    # --- .dat: create session, return applicable tool list ---
    if not data[:4] == b"PK\x03\x04":
        abort(400, "File does not appear to be a valid .dat archive.")
    try:
        controllers = parse_dat_controllers(data)
    except Exception as e:
        abort(400, f"Could not parse .dat file: {e}")
    if not controllers:
        abort(400, "No controller data found in this .dat file.")

    blocks = []
    for ctrl in controllers:
        cards = extract_groups_from_xml(ctrl["xml_bytes"])
        blocks.append({
            "name": ctrl["name"],
            "controller_type": ctrl["controller_type"],
            "groups": cards,
            "warnings": _check_warnings(cards),
        })

    sid = sessions.create({
        "type": "dat",
        "dat_data": data,
        "blocks": blocks,
        "multi": len(controllers) > 1,
    })
    return jsonify({
        "session_id": sid,
        "applicable_tools": ["rearranger", "convert", "split"],
        "blocks": blocks,
    })


# ---------------------------------------------------------------------------
# API — Download: rearrange
# ---------------------------------------------------------------------------

@app.route("/api/download/rearrange/<sid>")
def api_download_rearrange(sid):
    s = sessions.get(sid)
    if not s or s.get("type") != "dat":
        abort(404, "Session not found or expired.")

    export = request.args.get("export", "packaged")
    blocks = s.get("blocks", [])
    orders = {i: s.get(f"order_{i}") for i in range(len(blocks)) if s.get(f"order_{i}")}

    # Apply user-edited controller names and group tag names
    group_names_by_block = s.get("group_names", {})
    dat_data = _rebuild_dat_with_names(s["dat_data"], blocks, group_names_by_block)

    try:
        if export == "individual":
            results = rearrange_and_split_dat_bytes(dat_data, orders)
            if len(results) == 1:
                return _send_dat(results[0]["data"], f"{results[0]['name']}_rearranged.dat")
            return _send_zip(_zip_results(results), "rearranged_controllers.zip")

        elif export == "converted":
            results = rearrange_and_convert_dat_bytes(dat_data, orders)
            if len(results) == 1:
                return _send_dat(results[0]["data"], f"{results[0]['name']}.dat")
            return _send_zip(_zip_results(results), "converted_controllers.zip")

        else:  # packaged (default)
            result = rearrange_and_repackage_dat_bytes(dat_data, orders)
            base = _safe_filename(blocks[0]["name"]) if blocks else "rearranged"
            fname = f"{base}_rearranged.dat" if len(blocks) == 1 else "rearranged.dat"
            return _send_dat(result, fname)

    except Exception as e:
        abort(500, f"Export failed: {e}")


# ---------------------------------------------------------------------------
# API — Download: convert
# ---------------------------------------------------------------------------

@app.route("/api/download/convert/<sid>")
def api_download_convert(sid):
    s = sessions.get(sid)
    if not s or s.get("type") != "dat":
        abort(404, "Session not found or expired.")

    blocks = s.get("blocks", [])
    group_names_by_block = s.get("group_names", {})
    dat_data = _rebuild_dat_with_names(s["dat_data"], blocks, group_names_by_block)

    try:
        results = convert_dat_bytes(dat_data)
    except Exception as e:
        abort(500, f"Conversion failed: {e}")

    if len(results) == 1:
        r = results[0]
        return _send_dat(r["data"], r["name"] + ".dat")

    return _send_zip(_zip_results(results), "converted.zip")


# ---------------------------------------------------------------------------
# API — Download: split
# ---------------------------------------------------------------------------

@app.route("/api/download/split/<sid>")
def api_download_split(sid):
    s = sessions.get(sid)
    if not s or s.get("type") != "dat":
        abort(404, "Session not found or expired.")

    blocks = s.get("blocks", [])
    group_names_by_block = s.get("group_names", {})
    dat_data = _rebuild_dat_with_names(s["dat_data"], blocks, group_names_by_block)

    try:
        results = split_dat_bytes(dat_data)
    except ValueError as e:
        abort(400, str(e))
    except Exception as e:
        abort(500, f"Split failed: {e}")

    return _send_zip(_zip_results(results), "split_controllers.zip")


# ---------------------------------------------------------------------------
# API — Sort groups by tag name
# ---------------------------------------------------------------------------

@app.route("/api/session/<sid>/sort", methods=["POST"])
def api_sort_groups(sid):
    s = sessions.get(sid)
    if not s:
        abort(404, "Session not found or expired.")

    body      = request.get_json(force=True) or {}
    block_idx = body.get("block_index", 0)

    blocks = s.get("blocks", [])
    if block_idx >= len(blocks):
        abort(400, "Invalid block index.")

    cards     = blocks[block_idx]["groups"]
    new_order = sort_groups_by_tag(cards)
    sessions.update(sid, {f"order_{block_idx}": new_order})

    return jsonify({"ok": True, "new_order": new_order})


@app.route("/api/session/<sid>/controller-name", methods=["POST"])
def api_update_controller_name(sid):
    s = sessions.get(sid)
    if not s:
        abort(404, "Session not found or expired.")

    body = request.get_json(force=True) or {}
    block_idx = body.get("block_index", 0)
    new_name = str(body.get("name", "")).strip()

    if not new_name:
        abort(400, "Controller name cannot be empty.")

    blocks = s.get("blocks", [])
    if block_idx >= len(blocks):
        abort(400, "Invalid block index.")

    blocks[block_idx]["name"] = new_name
    sessions.update(sid, {"blocks": blocks})

    names = s.get("controller_names", {})
    names[str(block_idx)] = new_name
    sessions.update(sid, {"controller_names": names})

    return jsonify({"ok": True, "name": new_name})


@app.route("/api/session/<sid>/group-name", methods=["POST"])
def api_update_group_name(sid):
    s = sessions.get(sid)
    if not s:
        abort(404, "Session not found or expired.")

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

    sessions.update(sid, {"blocks": blocks})

    group_names = s.get("group_names", {})
    group_names.setdefault(str(block_idx), {})[str(slot)] = new_tag
    sessions.update(sid, {"group_names": group_names})

    return jsonify({"ok": True, "tag": new_tag})


# ---------------------------------------------------------------------------
# API — DAT↔JSON (codetest only)
# ---------------------------------------------------------------------------

_TOOL_ROUTES = {
    "dsbx-to-dat": "/dsbx-to-dat",
    "rearranger":   "/rearranger",
    "convert":      "/convert",
    "split":        "/split",
}

_VALID_TOOLS = set(_TOOL_ROUTES.keys())


@app.route("/api/export-json", methods=["POST"])
def api_export_json():
    if not _is_codetest():
        abort(404)

    body = request.get_json(force=True) or {}
    sid  = body.get("session_id")
    tool = body.get("tool")

    if tool not in _VALID_TOOLS:
        abort(400, "Invalid tool.")

    s = sessions.get(sid)
    if not s:
        abort(404, "Session not found or expired.")

    secret = app.secret_key if isinstance(app.secret_key, bytes) else app.secret_key.encode()
    try:
        json_bytes = export_session_json(s, tool, secret)
    except Exception as e:
        abort(500, f"Export failed: {e}")

    return send_file(
        io.BytesIO(json_bytes),
        mimetype="application/json",
        as_attachment=True,
        download_name="config_export.json",
    )


# ---------------------------------------------------------------------------
# MTDZ backend proxy — catch-all for any /api/ paths not handled above
# ---------------------------------------------------------------------------

@app.route("/api/<path:path>", methods=["GET", "POST", "DELETE", "PUT", "PATCH"])
def proxy_mtdz(path):
    url = f"{MTDZ_BACKEND}/api/{path}"
    try:
        if request.files:
            files = {k: (v.filename, v.stream, v.content_type)
                     for k, v in request.files.items()}
            form = {k: v for k, v in request.form.items()}
            resp = req_lib.request(
                method=request.method,
                url=url,
                files=files,
                data=form,
                params=request.args,
                allow_redirects=False,
                timeout=120,
            )
        else:
            ct = request.content_type or ""
            resp = req_lib.request(
                method=request.method,
                url=url,
                data=request.get_data(),
                headers={"Content-Type": ct} if ct else {},
                params=request.args,
                allow_redirects=False,
                timeout=120,
            )
    except req_lib.exceptions.ConnectionError:
        if request.path.startswith("/api/"):
            return jsonify({"error": "MTDZ backend unavailable."}), 502
        abort(502)

    exclude = {"content-encoding", "content-length", "transfer-encoding", "connection"}
    headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in exclude]
    return Response(resp.content, resp.status_code, headers)


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(400)
@app.errorhandler(404)
@app.errorhandler(500)
def handle_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": str(e.description)}), e.code
    return render_template("error.html", error=e), e.code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
