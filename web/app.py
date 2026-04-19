"""
Central Controller Config Tools — Flask web application.
"""
import io
import os
import zipfile

from flask import (Flask, jsonify, render_template, request,
                   send_file, abort)

from lib import sessions
from lib.dat_utils import (
    convert_dat_bytes, detect_controller_type, extract_groups_from_xml,
    parse_dat_controllers, rearrange_dat_bytes, sort_groups_by_tag,
    split_dat_bytes, _check_warnings,
)
from lib.dsbx_utils import (
    dsbx_to_dat_bytes, extract_group_cards, get_groupof50_list,
    load_mapping, parse_dsbx_bytes,
)

app = Flask(__name__)

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXT = {".dsbx", ".dat"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/dsbx-to-dat")
def page_dsbx_to_dat():
    return render_template("dsbx_to_dat.html")


@app.route("/rearranger")
def page_rearranger():
    return render_template("rearranger.html")


@app.route("/convert")
def page_convert():
    return render_template("convert.html")


@app.route("/split")
def page_split():
    return render_template("split.html")


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
# API — Download: rearrange
# ---------------------------------------------------------------------------

@app.route("/api/download/rearrange/<sid>")
def api_download_rearrange(sid):
    s = sessions.get(sid)
    if not s or s.get("type") != "dat":
        abort(404, "Session not found or expired.")

    if s.get("multi"):
        abort(400, "Rearrangement is only available for single-controller DAT files.")

    order = s.get("order_0")
    if not order:
        abort(400, "No rearrangement has been applied to this session.")

    try:
        result = rearrange_dat_bytes(s["dat_data"], order)
    except Exception as e:
        abort(500, f"Rearrangement failed: {e}")

    name = s["blocks"][0]["name"] if s.get("blocks") else "rearranged"
    return _send_dat(result, f"{name}_rearranged.dat")


# ---------------------------------------------------------------------------
# API — Download: convert
# ---------------------------------------------------------------------------

@app.route("/api/download/convert/<sid>")
def api_download_convert(sid):
    s = sessions.get(sid)
    if not s or s.get("type") != "dat":
        abort(404, "Session not found or expired.")

    try:
        results = convert_dat_bytes(s["dat_data"])
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

    try:
        results = split_dat_bytes(s["dat_data"])
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
