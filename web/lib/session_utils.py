"""
Session utility helpers shared across routes and blueprints.
"""

from flask import abort

from . import sessions


def require_session(sid: str, expected_type: str | None = None) -> dict:
    """Return the session dict for ``sid`` or abort 404.

    If ``expected_type`` is supplied, also abort 404 when the session's
    ``"type"`` field does not match. The 404 message is sanitized — do
    NOT leak the session id or expected type into the response body.
    """
    s = sessions.get(sid)
    if not s:
        abort(404, "Session not found.")
    if expected_type is not None and s.get("type") != expected_type:
        abort(404, "Session not found.")
    return s


def apply_order_to_groups(groups: list[dict], order: list[int] | None) -> list[dict]:
    """Remap group slot numbers according to a rearrangement order.

    ``order`` is a list of old slot numbers in their desired new positions
    (e.g. ``[3, 1, 2]`` means old slot 3 → new slot 1, old slot 1 → new
    slot 2, etc.).  Zeros represent empty / deselected positions and are
    skipped so gaps are preserved.

    Groups are mutated in place and also returned for convenience.
    """
    if not isinstance(order, list) or not order:
        return groups

    old_to_new = {old_slot: pos + 1 for pos, old_slot in enumerate(order) if old_slot > 0}

    for g in groups:
        if g["slot"] in old_to_new:
            g["slot"] = old_to_new[g["slot"]]

    return groups
