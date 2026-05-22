"""
Central Controller Config Tools — Flask web application.
"""

import base64
import logging
import os
import zipfile

import requests as req_lib
from flask import Flask, Response, jsonify, render_template, request, send_file, abort

from lib import sessions
from lib.dat_utils import (
    parse_dat_controllers,
    extract_groups_from_xml,
    _check_warnings,
)
from lib.dsbx_utils import (
    extract_group_cards,
    get_groupof50_list,
    load_mapping,
    parse_dsbx_bytes,
)
from lib.json_utils import import_session_json
from lib.agent_routes import agent_bp
from lib.dat_routes import dat_bp, _TOOL_ROUTES
from lib.dsbx_routes import dsbx_bp
from lib.lev_kit_routes import lev_kit_bp
from lib.mtdz_routes import mtdz_bp
from lib.route_helpers import _validate_upload

logger = logging.getLogger(__name__)

app = Flask(__name__)

# Deployment environment label — "prod" or "test". Read by /status and exposed
# to templates so the frontend banner script knows which container it's in.
# Must be read BEFORE SECRET_KEY so the fail-fast check can gate on it.
APP_ENV = os.environ.get("APP_ENV", "test")

_secret_key = os.environ.get("SECRET_KEY")
if not _secret_key and APP_ENV == "prod":
    raise RuntimeError("SECRET_KEY must be set in production")
app.secret_key = _secret_key or "dev-only-insecure-key"
app.register_blueprint(agent_bp)
app.register_blueprint(dat_bp)
app.register_blueprint(dsbx_bp)
app.register_blueprint(lev_kit_bp)
app.register_blueprint(mtdz_bp)

MTDZ_BACKEND = os.environ.get("MTDZ_BACKEND_URL", "http://mtdz-backend:8000")
SIGNAL_FILE = os.environ.get("RESTART_SIGNAL_FILE", "/app/signals/restart.json")


@app.context_processor
def inject_globals():
    return {"codetest": True, "app_env": APP_ENV}


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
# Shared helpers (_preloaded_session, _validate_upload, _zip_results,
# _send_dat, _send_zip) moved to web/lib/route_helpers.py.
# DAT helpers (_gather_export_state, _package_export_dat) moved to
# web/lib/dat_routes.py.

# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@app.route("/status")
def status():
    """Liveness + restart-window + session-expiry probe. Read by Docker
    healthcheck and the frontend banner poller. Cheap by design: no DB,
    no template render."""
    from lib.sessions import _expiry as _session_expiry

    return jsonify(
        {
            "ok": True,
            "env": APP_ENV,
            "restart_at": _read_restart_signal(),
            "session_expiry_at": _session_expiry(),
        }
    )


@app.route("/")
def index():
    return render_template("site_index.html")


@app.route("/config-tools")
def page_config_tools():
    return render_template("index.html")


@app.route("/contact")
def page_contact():
    return render_template("site_contact.html")


# LEV Kit Configurator routes (page + API + helpers) extracted to
# web/lib/lev_kit_routes.py (Blueprints B-11).  Registered below as lev_kit_bp.
#
# See web/lib/lev_kit_routes.py for:
#   - 5 page routes       (/lev-kit-*)
#   - 7 API routes        (/api/session/lev-kit-blank, /api/session/<sid>,
#                           /api/upload/lev-kit, /api/session/<sid>/lev-kit-update,
#                           /api/download/lev-kit/<sid>, /api/lev-kit/config-data,
#                           /api/lev-kit/compute-switches)
#   - 4 private helpers   (_refrigerant_from_controllers, _send_pdf,
#                           _lev_kit_session, _lev_kit_filename)


@app.route("/disclaimer")
def page_disclaimer():
    return render_template("disclaimer.html")


# MTDZ page routes (/mtdz/, /mtdz/viewer, /mtdz/report, /mtdz/sysinfo)
# are registered by mtdz_routes.py (mtdz_bp above).


# DSBX tool routes (/dsbx-to-dat, /api/upload/dsbx, /api/session/<sid>/groups,
# /api/download/dsbx-to-dat/<sid>) are registered by dsbx_routes.py (dsbx_bp below).
# DAT tool page routes (/rearranger, /convert, /split, /docs)
# are registered by dat_routes.py (dat_bp above).
# DAT upload route (/api/upload/dat) is registered by dat_routes.py.
# DAT upload route (/api/upload/dat) is registered by dat_routes.py.

# ---------------------------------------------------------------------------
# API — Config Hub unified upload (codetest feature)
# ---------------------------------------------------------------------------


@app.route("/api/upload/config-hub", methods=["POST"])
def api_upload_config_hub():

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
                logger.warning("Could not restore DSBX session", exc_info=True)
                abort(
                    400,
                    "Could not restore the session from the stored source. Please try re-uploading the file.",
                )

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
            session_data = {"type": "dsbx", "dsbx_data": source_bytes, "blocks": blocks}
        else:
            if not source_bytes[:4] == b"PK\x03\x04":
                abort(400, "Stored source data does not appear to be a valid .dat archive.")
            try:
                controllers = parse_dat_controllers(source_bytes)
            except Exception as e:
                logger.warning("Could not restore DAT session", exc_info=True)
                abort(
                    400,
                    "Could not restore the session from the stored source. Please try re-uploading the file.",
                )

            if not controllers:
                abort(400, "No controller data found in stored source.")

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
            # Apply saved controller names to blocks
            for idx_str, name in controller_names.items():
                try:
                    idx = int(idx_str)
                    if idx < len(session_data.get("blocks", [])):
                        session_data["blocks"][idx]["name"] = name
                except (ValueError, KeyError):
                    pass
            session_data["controller_names"] = controller_names
        if group_names:
            # Apply saved group tag names to blocks
            for block_idx_str, slots in group_names.items():
                try:
                    block_idx = int(block_idx_str)
                    blocks_list = session_data.get("blocks", [])
                    if block_idx < len(blocks_list):
                        for slot_str, tag in slots.items():
                            for g in blocks_list[block_idx].get("groups", []):
                                if g.get("slot") == int(slot_str):
                                    g["tag"] = tag
                except (ValueError, KeyError):
                    pass
            session_data["group_names"] = group_names

        sid = sessions.create(session_data)
        redirect_url = _TOOL_ROUTES.get(tool, "/rearranger") + f"?session={sid}"
        return jsonify(
            {
                "session_id": sid,
                "redirect": redirect_url,
            }
        )

    # --- .dsbx: create session, return applicable tool list ---
    if ext == ".dsbx":
        if not data[:4] == b"PK\x03\x04":
            abort(400, "File does not appear to be a valid .dsbx archive.")
        try:
            mapping = load_mapping()
            dsb_root = parse_dsbx_bytes(data)
            g50_list = get_groupof50_list(dsb_root)
        except Exception as e:
            logger.warning("Could not parse .dsbx file (config hub)", exc_info=True)
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
        return jsonify(
            {
                "session_id": sid,
                "applicable_tools": ["dsbx-to-dat"],
                "blocks": blocks,
            }
        )

    # --- .dat: create session, return applicable tool list ---
    if not data[:4] == b"PK\x03\x04":
        abort(400, "File does not appear to be a valid .dat archive.")
    try:
        controllers = parse_dat_controllers(data)
    except Exception as e:
        logger.warning("Could not parse .dat file (config hub)", exc_info=True)
        abort(
            400, "Could not parse the .dat file. Please verify it is a valid configuration export."
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
            "applicable_tools": ["rearranger", "convert", "split"],
            "blocks": blocks,
        }
    )


# DAT download/sort/rename/export routes are registered by dat_routes.py.

# ---------------------------------------------------------------------------
# MTDZ backend proxy — catch-all for any /api/ paths not handled above
# ---------------------------------------------------------------------------


@app.route("/api/<path:path>", methods=["GET", "POST", "DELETE", "PUT", "PATCH"])
def proxy_mtdz(path):
    url = f"{MTDZ_BACKEND}/api/{path}"
    try:
        if request.files:
            files = {k: (v.filename, v.stream, v.content_type) for k, v in request.files.items()}
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
@app.errorhandler(405)
@app.errorhandler(413)
@app.errorhandler(500)
def handle_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": str(e.description)}), e.code
    return render_template("error.html", error=e), e.code


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
