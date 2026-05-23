"""Shared pytest fixtures for the vrf-tools test suite."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def app_client():
    """Flask test client.

    Imports `web.app:app` directly. When B-20 (app factory) lands, this
    fixture should be rewritten to call `create_app()` instead.
    """
    from web.app import app as flask_app

    flask_app.config["TESTING"] = True
    # CSRF tokens are not signed in test mode unless WTF_CSRF_ENABLED is True;
    # disable here so individual tests opt-in if they want to assert CSRF behavior.
    flask_app.config["WTF_CSRF_ENABLED"] = False
    with flask_app.test_client() as client:
        yield client


@pytest.fixture
def sample_dat_bytes():
    """Return bytes of a known-good empty DAT file (AE-C400)."""
    return (FIXTURES_DIR / "sample_ae_c400_empty.dat").read_bytes()


@pytest.fixture
def sample_dsbx_bytes():
    """Return bytes of a minimal valid DSBX file (ZIP-wrapped XML with <Project>)."""
    return (FIXTURES_DIR / "sample_minimal.dsbx").read_bytes()
