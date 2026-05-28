"""
Main page routes and API handlers — Flask Blueprint.

Route origins (moved from web/app.py — B-20 app factory refactor):
  - /status                     — liveness + restart-window probe
  - /                           — site index
  - /config-tools               — DAT/DSBX/JSON config tools
  - /contact                    — contact page
  - /disclaimer                 — disclaimer page
  - /api/upload/config-hub      — unified config hub upload (codetest)
  - /api/<path:path>            — MTDZ backend proxy (catch-all)
  - Error handlers               — 400, 404, 405, 413, 500
"""

import base64
import json as _json
import logging
import os
import smtplib
from email.message import EmailMessage

import requests as req_lib
from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
)

from extensions import csrf
from . import sessions
from .dat_routes import _TOOL_ROUTES
from .dat_utils import extract_groups_from_xml, parse_dat_controllers, _check_warnings
from .dsbx_utils import extract_group_cards, get_groupof50_list, load_mapping, parse_dsbx_bytes
from .json_utils import import_session_json
from .route_helpers import _validate_upload

logger = logging.getLogger(__name__)

main_bp = Blueprint("main", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_restart_signal() -> str | None:
    """Return ISO timestamp of an upcoming restart, or None if none scheduled."""
    signal_file = current_app.config["RESTART_SIGNAL_FILE"]
    try:
        with open(signal_file, "r") as f:
            data = _json.load(f)
        ts = data.get("restart_at")
        return ts if isinstance(ts, str) and ts else None
    except (FileNotFoundError, ValueError, OSError):
        return None


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@main_bp.route("/status")
def status():
    """Liveness + restart-window + session-expiry probe. Read by Docker
    healthcheck and the frontend banner poller. Cheap by design: no DB,
    no template render."""
    from .sessions import _expiry as _session_expiry

    return jsonify(
        {
            "ok": True,
            "env": current_app.config["APP_ENV"],
            "restart_at": _read_restart_signal(),
            "session_expiry_at": _session_expiry(),
        }
    )


@main_bp.route("/")
def index():
    return render_template("site_index.html")


@main_bp.route("/config-tools")
def page_config_tools():
    return render_template("index.html")


@main_bp.route("/contact")
def page_contact():
    return render_template("site_contact.html")


@main_bp.route("/disclaimer")
def page_disclaimer():
    return render_template("disclaimer.html")


# ---------------------------------------------------------------------------
# API — Contact form (sends email via Hostinger SMTP to MAIL_TO)
# ---------------------------------------------------------------------------


_CONTACT_ALLOWED_EXTS = {".mtdz", ".mtlz", ".png", ".jpg", ".jpeg", ".gif"}
_CONTACT_MAX_FILES = 3
_CONTACT_MAX_TOTAL_BYTES = 25 * 1024 * 1024
_CONTACT_MAX_MESSAGE_LEN = 10_000
_CONTACT_MAX_FIELD_LEN = 200


@main_bp.route("/api/contact", methods=["POST"])
def api_contact():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    message = (request.form.get("message") or "").strip()
    category = (request.form.get("category") or "").strip()
    tools = (request.form.get("tools") or "").strip()
    reply_consent = request.form.get("reply_consent") == "true"

    if not email or "@" not in email or "." not in email.split("@", 1)[-1]:
        return jsonify({"detail": "A valid email address is required."}), 400
    if not message:
        return jsonify({"detail": "Please include a message."}), 400
    if not category:
        return jsonify({"detail": "Please select a category."}), 400
    if len(message) > _CONTACT_MAX_MESSAGE_LEN:
        return jsonify({"detail": "Message exceeds the allowed length."}), 400
    if len(email) > _CONTACT_MAX_FIELD_LEN or len(name) > _CONTACT_MAX_FIELD_LEN:
        return jsonify({"detail": "One or more fields exceed the allowed length."}), 400

    files = [f for f in request.files.getlist("attachments") if f and f.filename]
    if len(files) > _CONTACT_MAX_FILES:
        return jsonify({"detail": f"Maximum {_CONTACT_MAX_FILES} attachments allowed."}), 400

    file_payloads = []
    total_size = 0
    for f in files:
        ext = "." + f.filename.rsplit(".", 1)[-1].lower() if "." in f.filename else ""
        if ext not in _CONTACT_ALLOWED_EXTS:
            return jsonify({"detail": f"Unsupported attachment type: {ext}"}), 400
        data = f.read()
        total_size += len(data)
        if total_size > _CONTACT_MAX_TOTAL_BYTES:
            return jsonify({"detail": "Attachments exceed the 25 MB total size limit."}), 400
        file_payloads.append((f.filename, data, f.content_type or "application/octet-stream"))

    smtp_host = current_app.config["MAIL_SMTP_HOST"]
    smtp_port = current_app.config["MAIL_SMTP_PORT"]
    smtp_user = current_app.config["MAIL_USERNAME"]
    smtp_pass = current_app.config["MAIL_PASSWORD"]
    if not smtp_user or not smtp_pass:
        logger.error("Contact form: SMTP credentials not configured (MAIL_USERNAME/MAIL_PASSWORD)")
        return jsonify({
            "detail": "Email service is not configured. Please email support@vrftools.com directly."
        }), 503

    msg = EmailMessage()
    msg["From"] = current_app.config["MAIL_FROM"]
    msg["To"] = current_app.config["MAIL_TO"]
    msg["Reply-To"] = email
    msg["Subject"] = f"[VRFTools / {category}] from {name or email}"

    body_lines = [
        f"Category:  {category}",
        f"Name:      {name or '(not provided)'}",
        f"Email:     {email}",
        f"Reply OK:  {'yes' if reply_consent else 'no'}",
    ]
    if tools:
        body_lines.append(f"Tools:     {tools}")
    body_lines.append(f"Env:       {current_app.config['APP_ENV']}")
    body_lines.append("")
    body_lines.append("Message:")
    body_lines.append("-" * 40)
    body_lines.append(message)
    msg.set_content("\n".join(body_lines))

    for filename, data, ctype in file_payloads:
        maintype, _, subtype = ctype.partition("/")
        if not maintype or not subtype:
            maintype, subtype = "application", "octet-stream"
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=filename)

    try:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=current_app.config["MAIL_TIMEOUT"]) as smtp:
            smtp.login(smtp_user, smtp_pass)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        logger.exception("Contact form: SMTP authentication failed")
        return jsonify({
            "detail": "Email service authentication failed. Please email support@vrftools.com directly."
        }), 502
    except Exception:
        logger.exception("Contact form: SMTP send failed")
        return jsonify({
            "detail": "Could not send message. Please try again or email support@vrftools.com directly."
        }), 502

    return jsonify({"ok": True}), 200


# ---------------------------------------------------------------------------
# API — Config Hub unified upload (codetest feature)
# ---------------------------------------------------------------------------


@main_bp.route("/api/upload/config-hub", methods=["POST"])
def api_upload_config_hub():

    data, ext = _validate_upload(request.files.get("file"), {".dsbx", ".dat", ".json"})

    secret = (
        current_app.secret_key
        if isinstance(current_app.secret_key, bytes)
        else current_app.secret_key.encode()
    )

    # --- .json: restore session, return redirect to originating tool ---
    if ext == ".json":
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


# ---------------------------------------------------------------------------
# MTDZ backend proxy — catch-all for any /api/ paths not handled above
# ---------------------------------------------------------------------------


@main_bp.route("/api/<path:path>", methods=["GET", "POST", "DELETE", "PUT", "PATCH"])
@csrf.exempt
def proxy_mtdz(path):
    mtdz_backend = current_app.config["MTDZ_BACKEND_URL"]
    url = f"{mtdz_backend}/api/{path}"
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
# Error handlers  (app-wide via blueprint.app_errorhandler)
# ---------------------------------------------------------------------------


@main_bp.app_errorhandler(400)
@main_bp.app_errorhandler(404)
@main_bp.app_errorhandler(405)
@main_bp.app_errorhandler(413)
@main_bp.app_errorhandler(500)
def handle_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": str(e.description)}), e.code
    return render_template("error.html", error=e), e.code
