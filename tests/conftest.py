"""Shared pytest fixtures for the vrf-tools test suite."""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


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
