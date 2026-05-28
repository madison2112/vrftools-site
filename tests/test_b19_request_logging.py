"""B-19: smoke tests for request-ID logging middleware.

Validates that every response carries an ``X-Request-ID`` header and that
the health-check endpoint is logged at DEBUG level (not INFO).
"""

import logging


# ---------------------------------------------------------------------------
# X-Request-ID header
# ---------------------------------------------------------------------------

def test_response_includes_x_request_id(app_client):
    """Every successful response should include the X-Request-ID header."""
    resp = app_client.get("/")
    request_id = resp.headers.get("X-Request-ID", "")
    # 12-char hex from uuid.uuid4().hex[:12]
    assert len(request_id) == 12, f"expected 12-char hex, got {request_id!r}"
    assert all(c in "0123456789abcdef" for c in request_id), (
        f"non-hex in request ID: {request_id!r}"
    )


def test_x_request_id_present_on_error(app_client):
    """Even 4xx/5xx responses should carry the X-Request-ID header."""
    # CSRF is disabled in testing, but this exercises the middleware.
    resp = app_client.get("/api/contact")  # GET on a POST-only endpoint
    request_id = resp.headers.get("X-Request-ID", "")
    assert len(request_id) == 12, f"expected 12-char hex on {resp.status_code}, got {request_id!r}"


# ---------------------------------------------------------------------------
# Health-check endpoint stays at DEBUG
# ---------------------------------------------------------------------------

def test_status_route_logged_at_debug(caplog, app_client):
    """Requests to /status must be logged at DEBUG, not INFO.

    This keeps frequent health-check noise out of production INFO logs.
    """
    caplog.set_level(logging.DEBUG, logger="vrftools.request")
    app_client.get("/status")
    # Collect all log records from the vrftools.request logger
    request_logs = [
        r for r in caplog.records if r.name == "vrftools.request"
    ]
    assert request_logs, "no request-logger output captured for /status"
    # Every entry must be at DEBUG or lower (i.e. not INFO or above)
    for record in request_logs:
        assert record.levelno <= logging.DEBUG, (
            f"/status logged at {record.levelname} ({record.levelno}); "
            f"expected DEBUG or lower"
        )


# ---------------------------------------------------------------------------
# Non-status routes are logged at INFO
# ---------------------------------------------------------------------------

def test_non_status_route_logged_at_info(caplog, app_client):
    """Requests to non-status paths should be logged at INFO."""
    caplog.set_level(logging.INFO, logger="vrftools.request")
    app_client.get("/")
    request_logs = [
        r for r in caplog.records if r.name == "vrftools.request"
    ]
    assert request_logs, "no request-logger output captured for /"
    for record in request_logs:
        assert record.levelno == logging.INFO, (
            f"/ logged at {record.levelname} ({record.levelno}); "
            f"expected INFO"
        )
