"""
HMAC-signed JSON export/import for portable session sharing.
"""
import base64
import hashlib
import hmac as _hmac
import json


def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()


def _compute_hmac(payload_without_hmac: dict, secret: bytes) -> str:
    return _hmac.new(secret, _canonical(payload_without_hmac), hashlib.sha256).hexdigest()


def export_session_json(session_data: dict, tool: str, secret: bytes) -> bytes:
    """Build a signed, portable JSON payload from a live session."""
    blocks_clean = []
    for b in session_data.get("blocks", []):
        blocks_clean.append({
            "name":            b.get("name", ""),
            "controller_type": b.get("controller_type", ""),
            "groups":          b.get("groups", []),
        })

    orders = {}
    for key, val in session_data.items():
        if key.startswith("order_"):
            orders[key[6:]] = val  # strip "order_" prefix; key becomes string index

    raw = (
        session_data.get("dsbx_data", b"")
        if session_data.get("type") == "dsbx"
        else session_data.get("dat_data", b"")
    )

    payload = {
        "v":          1,
        "tool":       tool,
        "multi":      session_data.get("multi", False),
        "source_b64": base64.b64encode(raw).decode(),
        "blocks":     blocks_clean,
        "orders":     orders,
    }

    payload["hmac"] = _compute_hmac(payload, secret)
    return json.dumps(payload, indent=2).encode()


def import_session_json(raw: bytes, secret: bytes) -> dict:
    """Parse and validate a signed JSON export. Raises ValueError if tampered."""
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON: {e}")

    if not isinstance(payload, dict):
        raise ValueError("JSON must be an object.")

    received = payload.pop("hmac", None)
    if not received:
        raise ValueError("File is missing integrity data — it may have been modified.")

    expected = _compute_hmac(payload, secret)
    if not _hmac.compare_digest(received, expected):
        raise ValueError("File has been modified and cannot be imported.")

    payload["hmac"] = received  # restore for callers that want it
    return payload
