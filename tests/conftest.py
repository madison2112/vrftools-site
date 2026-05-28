"""Shared pytest fixtures for the vrf-tools test suite."""

import socket
import sys
import threading
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# Ensure the repo root is on sys.path so that `web.app` and `web.*`
# modules are importable without an installed package.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# The app is designed to run with `web/` as the working directory
# (see Dockerfile WORKDIR /app/web).  Add it to sys.path so that
# intra-web imports like `from config import CONFIG_BY_NAME` resolve.
_WEB_DIR = REPO_ROOT / "web"
if str(_WEB_DIR) not in sys.path:
    sys.path.insert(0, str(_WEB_DIR))


@pytest.fixture
def app_client():
    """Flask test client via the app factory with TestingConfig."""
    from web.app import create_app

    flask_app = create_app("testing")
    with flask_app.test_client() as client:
        yield client


@pytest.fixture
def sample_dat_bytes():
    """Return bytes of a known-good empty DAT file (AE-C400)."""
    return (FIXTURES_DIR / "sample_ae_c400_empty.dat").read_bytes()


# ---------------------------------------------------------------------------
# HC-08 — Live server fixture for Playwright visual regression tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def live_server():
    """Start the Flask app on a random localhost port in a background thread.

    Returns the base URL (``http://127.0.0.1:<port>``).  The server is
    shut down automatically when the test session finishes.
    """
    from werkzeug.serving import make_server
    from web.app import create_app

    app = create_app("testing")
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    server = make_server("127.0.0.1", port, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    # Give the server a moment to start accepting connections.
    time.sleep(0.3)

    base_url = f"http://127.0.0.1:{port}"
    yield base_url

    server.shutdown()
    thread.join(timeout=2)
