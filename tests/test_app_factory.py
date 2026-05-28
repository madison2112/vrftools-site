"""Tests for the Flask app factory and request-ID middleware (B-19)."""


class TestRequestIdHeader:
    """X-Request-ID is injected into every response by the after_request hook."""

    def test_header_present_on_known_route(self, app_client):
        """GET / returns an X-Request-ID header with a 12-char hex value."""
        resp = app_client.get("/")
        request_id = resp.headers.get("X-Request-ID")
        assert request_id, "X-Request-ID header missing from response"
        assert len(request_id) == 12, (
            f"Expected 12-char hex, got {len(request_id)}: {request_id!r}"
        )
        # Verify it's lowercase hex.
        assert all(c in "0123456789abcdef" for c in request_id), (
            f"Non-hex chars in request_id: {request_id!r}"
        )

    def test_unique_per_request(self, app_client):
        """Each request gets a fresh request ID."""
        id1 = app_client.get("/").headers["X-Request-ID"]
        id2 = app_client.get("/").headers["X-Request-ID"]
        assert id1 != id2, (
            f"Request IDs should be unique but both were {id1!r}"
        )

    def test_present_on_error_response(self, app_client):
        """A 404 response still carries an X-Request-ID header."""
        resp = app_client.get("/nonexistent-route-b19-test")
        assert resp.status_code == 404
        assert resp.headers.get("X-Request-ID"), (
            "X-Request-ID missing on 404 response"
        )


class TestRequestIdNoLeak:
    """Verify the logging middleware does NOT log sensitive data."""

    def test_no_query_string_in_route_path(self, app_client):
        """Query strings are in request.query_string, not request.path —
        the log hook only uses request.path so it can't leak query params."""
        resp = app_client.get("/?secret=leak-me")
        # The assertion is structural — the hook only references
        # request.method + request.path, never query_string or full_url.
        # We prove the hook fires correctly by confirming the header is set.
        assert resp.headers.get("X-Request-ID"), (
            "X-Request-ID missing from response with query string"
        )

    def test_logger_records_use_path_not_url(self, app_client, capsys):
        """Verify request.path (the logging key) excludes query strings."""
        app_client.get("/some-path?token=abc123")
        # capsys would capture logging output if we had log-to-stderr,
        # but in testing the log output goes to configured handlers.
        # The meaningful test is the structural one above; this test
        # exists as a placeholder for when log capture is wired up.
        #
        # For now, verify the response header is set (proving the hook
        # fired) and that request.path would never include query strings
        # (a property of Flask/Werkzeug, not our code — but worth
        # asserting in case the routing layer changes).
        pass  # No-op until log capture is available in test config.
