"""Flask extension instances shared across blueprints.

This module exists to avoid circular imports when blueprints need to
reference extension objects (e.g. CSRFProtect for @csrf.exempt) that
are initialized in app.py.
"""

from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect()
