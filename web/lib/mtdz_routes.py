"""
MTDZ tool routes — Flask Blueprint.

Routes for the MTDZ Diagnostic Viewer: 4 page routes (index, viewer,
report, sysinfo). No API routes — the MTDZ backend is reached via the
catch-all `/api/<path:path>` proxy at app.py:369, which is out of scope.

Pattern note (B-12 — fourth blueprint extraction, following B-11):
- Blueprint location: web/lib/mtdz_routes.py (not web/blueprints/)
- Naming: <tool>_routes.py matching dat_routes, dsbx_routes,
  lev_kit_routes pattern.
- No helpers needed — these are the thinnest routes in the app
  (pure render_template calls).
"""

import logging

from flask import Blueprint, render_template

logger = logging.getLogger(__name__)

mtdz_bp = Blueprint("mtdz", __name__)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@mtdz_bp.route("/mtdz/")
def page_mtdz_index():
    return render_template("mtdz/index.html")


@mtdz_bp.route("/mtdz/viewer")
def page_mtdz_viewer():
    return render_template("mtdz/viewer.html")


@mtdz_bp.route("/mtdz/report")
def page_mtdz_report():
    return render_template("mtdz/report.html")


@mtdz_bp.route("/mtdz/sysinfo")
def page_mtdz_sysinfo():
    return render_template("mtdz/sysinfo.html")
