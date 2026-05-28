"""Central Controller Config Tools — Flask web application.

App factory: `create_app(config_name)` replaces the old module-level Flask
construction.  Per-environment config classes live in `web/config.py`.
"""

import logging
import os
import time
import uuid

from flask import Flask, g, request

from config import CONFIG_BY_NAME
from extensions import csrf
from lib.agent_routes import agent_bp
from lib.dat_routes import dat_bp
from lib.dsbx_routes import dsbx_bp
from lib.lev_kit_routes import lev_kit_bp
from lib.main_routes import main_bp
from lib.mtdz_routes import mtdz_bp

logger = logging.getLogger(__name__)


class _RequestIdFilter(logging.Filter):
    """Inject ``request_id`` onto every log record so format strings that
    reference ``%(request_id)s`` never raise ``KeyError`` — even when the
    record is emitted outside a Flask request context (startup, cron, …)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "request_id"):
            record.request_id = "-"
        return True


def create_app(config_name: str | None = None) -> Flask:
    """Build and return a fully configured Flask application instance.

    Args:
        config_name: One of ``"production"``, ``"development"``,
            ``"testing"``, or ``"default"``.  If *None*, reads the
            ``APP_CONFIG`` environment variable, falling back to
            ``"default"`` (ProductionConfig).

    Returns:
        A Flask application ready to serve or test.

    Raises:
        RuntimeError: If ``APP_ENV`` is ``"prod"`` and ``SECRET_KEY``
            is unset or still the dev-only insecure fallback (HC-02 guard).
    """
    if config_name is None:
        config_name = os.environ.get("APP_CONFIG", "default")

    app = Flask(__name__)
    app.config.from_object(CONFIG_BY_NAME[config_name])

    # ------------------------------------------------------------------
    # HC-02 — SECRET_KEY production guard (must survive the B-20 refactor)
    # ------------------------------------------------------------------
    if app.config["APP_ENV"] == "prod" and app.config["SECRET_KEY"] in (
        None,
        "",
        "dev-only-insecure-key",
    ):
        raise RuntimeError(
            "SECRET_KEY must be set to a non-default value in production"
        )

    # ------------------------------------------------------------------
    # B-19 — Structured request-ID logging
    # ------------------------------------------------------------------
    # Configure root logger (skip if gunicorn already did it).
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
        )
    logging.getLogger().addFilter(_RequestIdFilter())
    request_logger = logging.getLogger("vrftools.request")

    @app.before_request
    def _log_request_start() -> None:
        g.request_id = uuid.uuid4().hex[:12]
        g.request_started_at = time.monotonic()
        level = logging.DEBUG if request.path == "/status" else logging.INFO
        request_logger.log(
            level,
            "→ %s %s",
            request.method,
            request.path,
            extra={"request_id": g.request_id},
        )

    @app.after_request
    def _log_request_end(response):
        elapsed_ms = (
            time.monotonic() - getattr(g, "request_started_at", time.monotonic())
        ) * 1000.0
        level = logging.DEBUG if request.path == "/status" else logging.INFO
        request_logger.log(
            level,
            "← %s %s → %d (%.1fms)",
            request.method,
            request.path,
            response.status_code,
            elapsed_ms,
            extra={"request_id": getattr(g, "request_id", "?")},
        )
        response.headers["X-Request-ID"] = getattr(g, "request_id", "")
        return response

    @app.teardown_request
    def _log_request_exception(exc: BaseException | None) -> None:
        if exc is not None:
            request_logger.warning(
                "✗ %s %s raised %s: %s",
                request.method,
                request.path,
                exc.__class__.__name__,
                exc,
                extra={"request_id": getattr(g, "request_id", "?")},
                exc_info=True,
            )

    # --- end B-19 -------------------------------------------------------

    csrf.init_app(app)

    # Register blueprints.  main_bp carries the /api/<path:path> catch-all
    # proxy_mtdz route — it MUST be registered last so it doesn't shadow
    # more-specific API routes in other blueprints (e.g. dat_bp's
    # /api/upload/dat, dsbx_bp's /api/upload/dsbx).
    app.register_blueprint(agent_bp)
    app.register_blueprint(dat_bp)
    app.register_blueprint(dsbx_bp)
    app.register_blueprint(lev_kit_bp)
    app.register_blueprint(mtdz_bp)
    app.register_blueprint(main_bp)

    @app.context_processor
    def inject_globals():
        return {"codetest": True, "app_env": app.config["APP_ENV"]}

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000, debug=False)
