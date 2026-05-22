"""Agent API blueprint — endpoints for the Hermes autonomous agent.

All write endpoints require an X-Agent-Key header matching the AGENT_API_KEY
environment variable. Read-only endpoints (like /status) are unauthenticated
so the agent can check liveness without credentials.
"""

import functools
import hmac
import os

from flask import Blueprint, jsonify, request

from extensions import csrf

agent_bp = Blueprint("agent", __name__, url_prefix="/agent")

_AGENT_KEY = os.environ.get("AGENT_API_KEY", "")


def require_agent_key(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        if not _AGENT_KEY:
            return jsonify({"error": "Agent API not configured — set AGENT_API_KEY"}), 503
        if not hmac.compare_digest(request.headers.get("X-Agent-Key", ""), _AGENT_KEY):
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)

    return wrapper


@agent_bp.route("/status")
def agent_status():
    """Unauthenticated liveness probe — safe for agent health checks."""
    return jsonify({"ok": True, "service": "vrftools-ccct"})


@agent_bp.route("/ping", methods=["POST"])
@csrf.exempt
@require_agent_key
def agent_ping():
    """Authenticated round-trip test. Returns the message echoed back."""
    payload = request.get_json(silent=True) or {}
    return jsonify({"pong": True, "echo": payload.get("message", "")})
