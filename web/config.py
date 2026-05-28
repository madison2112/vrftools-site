"""Per-environment configuration classes for the VRFTools Flask application.

Loaded by `create_app()` in `web/app.py` via Flask's `app.config.from_object()`.
"""

import os

_DEV_INSECURE_SECRET_KEY = "dev-only-insecure-key"


class Config:
    """Base configuration with shared defaults."""

    SECRET_KEY: str = os.environ.get("SECRET_KEY") or _DEV_INSECURE_SECRET_KEY
    APP_ENV: str = os.environ.get("APP_ENV", "test")
    MTDZ_BACKEND_URL: str = os.environ.get(
        "MTDZ_BACKEND_URL", "http://mtdz-backend:8000"
    )
    RESTART_SIGNAL_FILE: str = os.environ.get(
        "RESTART_SIGNAL_FILE", "/app/signals/restart.json"
    )


class ProductionConfig(Config):
    """Production configuration. Inherits all base defaults."""


class DevelopmentConfig(Config):
    """Development configuration. Can enable debug features if needed."""


class TestingConfig(Config):
    """Test configuration — deterministic secrets, no CSRF by default."""

    TESTING: bool = True
    WTF_CSRF_ENABLED: bool = False
    SECRET_KEY: str = "testing-session-secret"


CONFIG_BY_NAME = {
    "production": ProductionConfig,
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "default": ProductionConfig,
}
