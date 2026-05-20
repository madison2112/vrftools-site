"""
Shared routing helpers used across blueprints and app.py.

These are thin HTTP-context wrappers — no business logic, no domain imports.
Keep them here instead of duplicating across blueprints.
"""

import io as _io
import os as _os
import zipfile as _zipfile

from flask import abort, request, send_file

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
ALLOWED_EXT = {".dsbx", ".dat"}


def _preloaded_session(expected_type: str) -> str | None:
    """Return a valid session ID from ?session= if type matches."""
    from . import sessions as _sessions

    sid = request.args.get("session")
    if not sid:
        return None
    s = _sessions.get(sid)
    if s and s.get("type") == expected_type:
        return sid
    return None


def _validate_upload(file, allowed=None):
    """Validate size and extension; return (bytes, ext) or raise."""
    if not file or file.filename == "":
        abort(400, "No file provided.")
    data = file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        abort(413, "File exceeds 5 MB limit.")
    ext = _os.path.splitext(file.filename)[1].lower()
    if allowed and ext not in allowed:
        abort(400, f"Expected {' or '.join(sorted(allowed))} file, got {ext!r}.")
    return data, ext


def _zip_results(results: list) -> bytes:
    """Package a list of {"name", "data"} dicts into a ZIP archive."""
    buf = _io.BytesIO()
    with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as zf:
        for r in results:
            zf.writestr(r["name"] + ".dat", r["data"])
    return buf.getvalue()


def _send_dat(data: bytes, filename: str):
    return send_file(
        _io.BytesIO(data),
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=filename,
    )


def _send_zip(data: bytes, filename: str):
    return send_file(
        _io.BytesIO(data),
        mimetype="application/zip",
        as_attachment=True,
        download_name=filename,
    )
