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

    # Contact-form SMTP. Credentials come from environment at container-run
    # time — never commit them. The endpoint at /api/contact returns a 503
    # JSON error if MAIL_USERNAME / MAIL_PASSWORD are unset.
    MAIL_SMTP_HOST: str = os.environ.get("MAIL_SMTP_HOST", "smtp.hostinger.com")
    MAIL_SMTP_PORT: int = int(os.environ.get("MAIL_SMTP_PORT", "465"))
    MAIL_USERNAME: str = os.environ.get("MAIL_USERNAME", "")
    MAIL_PASSWORD: str = os.environ.get("MAIL_PASSWORD", "")
    MAIL_FROM: str = os.environ.get("MAIL_FROM", "support@vrftools.com")
    MAIL_TO: str = os.environ.get("MAIL_TO", "support@vrftools.com")
    MAIL_TIMEOUT: int = int(os.environ.get("MAIL_TIMEOUT", "15"))


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
