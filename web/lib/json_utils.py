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


def export_session_json(export_blocks: list, session_data: dict,
                        tool: str, secret: bytes) -> bytes:
    """
    Build a signed, portable JSON payload from canonical export blocks.

    export_blocks comes from _gather_export_state(s) — it already has
    controller names, group tag names, and rearrangement orders applied.
    """
    blocks_clean = []
    for block in export_blocks:
        blocks_clean.append({
            "name":            block.get("name", ""),
            "controller_type": block.get("controller_type", ""),
            "groups":          block.get("groups", []),
        })

    # Orders are already encoded in the group positions — no need to
    # export raw order_N lists.
    orders = {}

    controller_names = session_data.get("controller_names", {})
    group_names = session_data.get("group_names", {})

    # Capture current names from blocks
    for i, b in enumerate(blocks_clean):
        name = b.get("name", "")
        if name and str(i) not in controller_names:
            controller_names[str(i)] = name

    raw = (
        session_data.get("dsbx_data", b"")
        if session_data.get("type") == "dsbx"
        else session_data.get("dat_data", b"")
    )

    payload = {
        "v":               1,
        "tool":            tool,
        "multi":           session_data.get("multi", False),
        "source_b64":      base64.b64encode(raw).decode(),
        "blocks":          blocks_clean,
        "orders":          orders,
        "controller_names": controller_names,
        "group_names":     group_names,
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
