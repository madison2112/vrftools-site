# VRFTools Architecture

> Forward-looking design contract for the vrf-tools refactor.
> This document describes the END-STATE architecture (post-refactor).
> Items marked "current behaviour, changed by <step>" describe transitional states
> that must be corrected before the corresponding refactor card is closed.

---

## 1. Layer Model

Three layers, strict dependency direction: Presentation -> Routing -> Domain.
No layer may import from a layer above it.

```
Presentation   web/templates/   web/static/js/   web/static/css/
    |               Jinja2 + vanilla JS, calls Routing via fetch()
    v
Routing        web/lib/<tool>_routes.py  (Flask Blueprints)
    |               HTTP in / JSON out; no business logic
    v
Domain         web/lib/<module>.py
                   Pure Python; no Flask, no HTTP, no global mutable state.
                   Importable from tests, CLI scripts, or any other context.
```

### 1.1 Domain Layer

Files: `web/lib/dat_utils.py`, `web/lib/dsbx_utils.py`, `web/lib/zipcrypto.py`,
`web/lib/lev_kit_utils.py`, `web/lib/json_utils.py`, `web/lib/sessions.py`

Rules:
- No `from flask import ...` anywhere in a domain module.
- No `abort()`, no `request`, no `g`, no `current_app`.
- No file I/O except inside designated I/O helpers (`generate_dat_bytes`,
  `render_submittal_pdf`, `sessions.create/get/update/delete`).
- No hardcoded absolute paths. Use `REPO_ROOT` resolved via env var or
  `__file__` traversal. See DL-25 and the VRFTOOLS_ROOT env var pattern.
- No global mutable state. Module-level constants (dicts, lists) are fine;
  module-level variables that are written at runtime are not.
- Functions accept bytes/primitives/dataclasses; they return bytes/primitives/dicts.

### 1.2 Routing Layer

Files: `web/lib/agent_routes.py` (exists), future `web/lib/dat_routes.py`,
`web/lib/dsbx_routes.py`, `web/lib/lev_kit_routes.py`, `web/lib/config_hub_routes.py`,
`web/lib/proxy_routes.py`.

Current behaviour: logic lives in `web/app.py` as a 1355-line monolith.
Changed by B-09 through B-12 (Blueprint extraction phase).

Rules:
- Each blueprint is a Flask `Blueprint` registered in `web/app.py` (or the
  `create_app()` factory after B-20).
- Route handlers do exactly: validate the HTTP request, call one or more domain
  functions, format the response. That is all.
- No file parsing, no XML manipulation, no crypto, no PDF rendering in a route
  handler. These belong in the domain layer.
- File I/O (reading uploaded bytes, sending file responses) is allowed in route
  handlers because it is inherently HTTP-context work. Domain functions receive
  the bytes already read; they do not open files from paths.
- Hardcoded paths are forbidden. If a route needs a path, it reads an env var
  or delegates to a domain function that handles path resolution.

### 1.3 Presentation Layer

Files: `web/templates/*.html` (Jinja2), `web/static/js/*.js`, `web/static/css/*.css`

Rules:
- Templates extend either `base.html` (config-tools family) or `site_base.html`
  (marketing/site family). Never inline raw styles or scripts beyond a few lines.
- JS communicates with the backend exclusively through Flask routes via `fetch()`.
  No direct storage access, no backend URLs hardcoded in JS (use the `API`
  constant from `shared.js` after HC-04).
- All HTML escaping for dynamic content goes through `escHtml()` from `shared.js`.
  Inline escaping functions are forbidden after HC-04.
- No global mutable JS variables. Wrap file-scoped state in IIFEs or, for new
  code, ES module pattern (`<script type="module">`).
- CSS custom properties (colours, breakpoints) live in `base.css` after HC-03.
  Do not redeclare `:root` variables that already exist in `base.css`.

---

## 2. Public API Contract — Domain Modules

Stability guarantee: public function signatures (names, parameter order, return
type shape) must not change without a deprecation cycle. Callers may depend on
these. Private functions (underscore-prefixed) are implementation details;
callers must not import them.

---

### 2.1 `web/lib/zipcrypto.py`

Canonical ZipCrypto (PKWARE traditional encryption) implementation for DAT files.
This is the ONLY place in the codebase where ZipCrypto is implemented.

Public API:

```python
PASSWORD: bytes
# = b"MELCO" by default; overridable via VRFTOOLS_DAT_PASSWORD env var (DL-23)

def build_dat_bytes(
    entries: list[tuple[str, bytes | None, bool]]
) -> bytes:
    """
    Build a ZipCrypto-encrypted DAT archive and return raw bytes.

    entries: list of (name, data, encrypt)
      name    - ZIP entry name (e.g. "1", "NetworkSetting.xml", "IMG/")
      data    - raw bytes to store, or None for a directory entry
      encrypt - True to apply ZipCrypto; False for plain compression
    Returns: bytes of the complete ZIP archive
    """
```

Private (do not import): `_make_crc_table`, `_crc32_byte`, `_init_keys`,
`_update_keys`, `_stream_byte`, `_encrypt`, `_dos_time`, `_lfh`, `_cde`.

---

### 2.2 `web/lib/dat_utils.py`

DAT file parsing, generation, conversion, splitting, and rearrangement.

Public API:

```python
NEEDS_IMG:     frozenset[str]   # controller types that include an IMG/ entry
NEEDS_NETWORK: frozenset[str]   # controller types that include NetworkSetting.xml
OPPOSITE:      dict[str, str]   # AE-200 <-> AE-C400A, EW-50 <-> EW-C50 mapping
DATA_LISTS:    frozenset[str]   # ControlGroup child tags that carry group data
REPO_ROOT:     str              # absolute path to repo root (env-overridable)
TEMPLATES_DIR: str              # absolute path to templates/ directory

# After DL-07, these will be derived from CONTROLLER_REGISTRY in this module
# (currently duplicated in dsbx_utils.py — see Anti-Duplication Rules).

def detect_controller_type(dat_bytes: bytes) -> str:
    """Returns one of: "AE-200", "AE-C400A", "EW-50", "EW-C50"."""

def parse_dat_controllers(
    dat_bytes: bytes
) -> list[dict[str, str | bytes]]:
    """
    Returns list of controller dicts:
      {"entry": str, "name": str, "controller_type": str, "xml_bytes": bytes}
    """

def extract_groups_from_xml(xml_bytes: bytes) -> list[dict]:
    """
    Returns list of group card dicts:
      {"slot": int, "tag": str, "mnet_addresses": list[str],
       "unit_types": list[str], "icon": int}
    """

def generate_dat_bytes(xml_bytes: bytes, controller_type: str) -> bytes:
    """Wrap XML in a properly structured, encrypted DAT ZIP."""

def convert_dat_bytes(dat_bytes: bytes) -> list[dict[str, str | bytes]]:
    """
    Convert each controller to its opposite family type.
    Returns list of {"name": str, "controller": str, "data": bytes}
    """

def split_dat_bytes(dat_bytes: bytes) -> list[dict[str, str | bytes]]:
    """
    Split a multi-controller DAT into individual DATs.
    Raises ValueError if only one controller present.
    Returns list of {"name": str, "controller": str, "data": bytes}
    """

def apply_rearrangement(xml_bytes: bytes, new_order: list[int]) -> bytes:
    """
    Rewrite ControlGroup XML with remapped group slot numbers.
    new_order: list of old slot numbers in their desired new positions.
    """

def rearrange_dat_bytes(dat_bytes: bytes, new_order: list[int]) -> bytes:
    """Single-controller DAT: apply group rearrangement and return new DAT."""

def rearrange_and_repackage_dat_bytes(
    dat_bytes: bytes, orders: dict[int, list[int]]
) -> bytes:
    """Apply per-controller rearrangements and return a single multi-controller DAT."""

def rearrange_and_split_dat_bytes(
    dat_bytes: bytes, orders: dict[int, list[int]]
) -> list[dict[str, str | bytes]]:
    """Apply rearrangements, split into individual per-controller DATs."""

def rearrange_and_convert_dat_bytes(
    dat_bytes: bytes, orders: dict[int, list[int]]
) -> list[dict[str, str | bytes]]:
    """Apply rearrangements, split, and convert each to its opposite family."""

def sort_groups_by_tag(cards: list[dict]) -> list[int]:
    """Return new_order list with IC/AIC groups sorted by tag (natural sort)."""

def apply_group_names(
    xml_bytes: bytes, tag_map: dict[int, str]
) -> bytes:
    """Apply edited group tag names to ControlGroup XML. tag_map: {slot: new_name}"""
```

Public utility: `safe_filename` (imported by `app.py` and `web/lib/dat_routes.py`).

Private (do not import): `_open_dat`, `_check_warnings`.

Note: `_check_warnings` is used by DAT, DSBX, and Config Hub route handlers
(in `dat_routes.py` and `app.py`). Because it is genuinely shared across
multiple Blueprints, it remains in `dat_utils.py` until B-10 (DSBX Blueprint),
at which point it should be promoted to a public name and a shared location
(`route_helpers.py` or a new `warnings.py`). Originally scoped to B-09 but
deferred — see PR #12 review notes.

---

### 2.3 `web/lib/dsbx_utils.py`

DSBX file parsing and DAT XML generation from DSBX project data.

Public API:

```python
FAMILY_MAP: dict[str, dict[str, str]]
# Maps target_family -> {"AE": controller, "EW": controller}
# NOTE: Currently duplicated from dat_utils.py. After DL-07, this module will
# import FAMILY_MAP from dat_utils and not define its own copy.

def load_mapping() -> dict:
    """Load the dsbx_dat_mapping.json icon rules and default icon."""

def parse_dsbx_bytes(data: bytes) -> ET.Element:
    """Unzip a .dsbx and return the root XML element."""

def get_groupof50_list(dsb_root: ET.Element) -> list[ET.Element]:
    """
    Return list of <Groupof50> elements.
    Raises ValueError if no <Project> element found.
    """

def build_control_group(
    groupof50: ET.Element, mapping: dict
) -> ET.Element:
    """Build the <ControlGroup> XML element from a Groupof50 DSB block."""

def extract_group_cards(
    groupof50: ET.Element, mapping: dict
) -> list[dict]:
    """
    Return group card dicts for the frontend rearrangement UI.
    {"slot": int, "tag": str, "mnet_addresses": list[str],
     "unit_types": list[str], "icon": int}
    """

def dsbx_to_dat_bytes(
    dsbx_data: bytes,
    target_family: str = "AE-C400A"
) -> list[dict[str, str | bytes]]:
    """
    Convert a .dsbx to one or more .dat files.
    target_family: "AE-C400A" or "AE-200"
    Returns list of {"name": str, "controller": str, "data": bytes}
    """

def lookup_icon(
    model_number: str, rules: list[dict], default_icon: int
) -> int:
    """Match a model number string against icon rules; return icon int."""
```

Private (do not import): `_text`, `_valid_mnet`, `_build_indices`.

---

### 2.4 `web/lib/lev_kit_utils.py`

LEV Kit DIP switch computation and submittal PDF rendering.

Public API (constants):

```python
CONTROLLER_AH001: str   # = "PAC-AH001"
CONTROLLER_AH002: str   # = "PAC-AH002"
REFRIGERANT_LABEL: dict[str, str]
CAPACITY_OPTIONS: list[dict]          # AH002 capacity lookup table
CAPACITY_OPTIONS_AH001: list[dict]    # AH001 capacity lookup table
THERMO_OPTIONS: list[dict]            # AH002 thermo-off options
THERMO_OPTIONS_AH001: list[dict]      # AH001 thermo-off options
HEATING_SETPOINT_OPTIONS: list[dict]  # AH002 DAT setpoint options
DAT_SETPOINT_OPTIONS_AH001: list[dict]# AH001 DAT setpoint options
DEFAULT_SWITCHES: dict[str, list[int]]
DEFAULT_SWITCHES_AH001: dict[str, list[int]]
SWITCH_BANKS: list[tuple[str, int]]
SWITCH_BANKS_AH001: list[tuple[str, int]]
```

Public API (dataclass):

```python
@dataclass
class ParsedUnit:
    tag: str
    mnet: int | None
    btuh: int
    capacity_index: int
    capacity_label: str
    lev_assembly: str
    control_mode: str           # "discharge" | "return"
    raw_application_option: str
    controller_type: str        # CONTROLLER_AH001 or CONTROLLER_AH002

    def to_dict(self) -> dict: ...
```

Public API (functions):

```python
def generate_switch_positions(config: dict) -> dict:
    """
    Compute DIP switch positions for one unit.
    Dispatches on config["controller_type"] (defaults to AH002).
    Returns {"switches": {"SW1": [0|1, ...], ...}, "cnrm_connected": bool}

    After DL-09, also accepts a SwitchConfig dataclass directly.
    """

def parse_dsbx(file_bytes: bytes) -> dict:
    """
    Parse a .dsbx file and extract LEV Kits.
    Returns {
      "project_name": str,
      "units": [ParsedUnit.to_dict(), ...],
      "controllers_found": {CONTROLLER_AH001: int, CONTROLLER_AH002: int},
      "skipped_r410a": [],
      "warnings": [str, ...]
    }
    """

def build_unit_record(parsed: dict, **overrides) -> dict:
    """
    Combine a parsed unit dict (from parse_dsbx) with user-supplied overrides
    into the canonical record consumed by render_submittal_pdf().
    """

def thermistor_wiring(control_mode: str) -> tuple[str, str]:
    """Return (TH21_Air_label, TH24_Air_label) for the given control mode."""

def control_mode_display(unit: dict) -> str:
    """Human-readable control mode column value for PDF."""

def compute_footnotes(
    units: list[dict]
) -> tuple[list[str], dict[str, list[int]]]:
    """
    Build the numbered Notes section and per-unit footnote references.
    Returns (footnote_lines, {unit_tag: [footnote_number, ...]})
    """

def render_submittal_pdf(
    units: list[dict],
    project_name: str,
    voltage: str = "208",
    layout: str = "horizontal",
    refrigerant_selection: str = "ah002",
) -> bytes:
    """Render the LEV Kit submittal PDF; returns raw PDF bytes."""
```

Private (do not import): `_capacity_by_value`, `_thermo_by_value`,
`_generate_switch_positions_ah002`, `_generate_switch_positions_ah001`,
`_capacity_index_for_btuh`, `_control_mode_from_application`, `_unit_note_texts`,
`_enable_text`, `_setpoint_text`, `_BTUH_RE`.

Note: `DipSwitchBank` and `SingleRowSwitchBank` are currently inner classes
defined as closures inside `render_submittal_pdf`. They will be extracted to
`web/lib/pdf_flowables.py` as part of DL-20. Until then, do not import them
directly.

---

### 2.5 `web/lib/json_utils.py`

HMAC-signed JSON export/import for portable session sharing.

Public API:

```python
def export_session_json(
    export_blocks: list[dict],
    session_data: dict,
    tool: str,
    secret: bytes,
) -> bytes:
    """
    Build a signed, portable JSON payload from canonical export blocks.
    Returns UTF-8-encoded JSON bytes with embedded HMAC.
    """

def import_session_json(raw: bytes, secret: bytes) -> dict:
    """
    Parse and validate a signed JSON export.
    Raises ValueError if the HMAC is missing or does not match.
    Returns the payload dict (with "hmac" key restored).
    """
```

Private (do not import): `_canonical`, `_compute_hmac`.

---

### 2.6 `web/lib/sessions.py`

File-based session store. Provides CRUD for server-side session data.

Current behaviour: uses pickle serialisation and lacks file locking.
Changed by B-14 (add fcntl file locking) and B-15 (migrate to JSON).
Long-term target B-21: Redis-backed implementation behind same interface.

Public API:

```python
SESSION_DIR: str   # = "/tmp/ccct-sessions" by default

def create(data: dict) -> str:
    """
    Create a new session with the given data dict.
    Returns a UUID string (the session ID).
    Adds an "expires" key (next 1 AM PST) automatically.
    """

def get(sid: str) -> dict | None:
    """
    Retrieve a session by ID.
    Returns None if the session does not exist or has expired.
    Expired sessions are deleted on read.
    """

def update(sid: str, patch: dict) -> bool:
    """
    Merge patch into an existing session and refresh the expiry.
    Returns False if the session does not exist or has expired.
    """

def delete(sid: str) -> None:
    """Delete a session. No-op if it does not exist."""
```

Private (do not import): `_next_1am_pst`, `_expiry`, `_session_path`,
`_cleanup_loop`.

---

### 2.7 `web/lib/agent_routes.py`

Flask Blueprint for the Hermes agent API. This module straddles the Routing and
Domain distinction — it is a Blueprint (routing layer) that also provides a
reusable auth decorator.

Public API:

```python
agent_bp: Blueprint
# Registered in app.py as app.register_blueprint(agent_bp).
# URL prefix: /agent

def require_agent_key(f) -> Callable:
    """
    Decorator: validates X-Agent-Key header against AGENT_API_KEY env var.
    Returns 401 if wrong, 503 if AGENT_API_KEY is not configured.
    Apply to any route that should be agent-only.
    """

# Routes exposed by agent_bp:
# GET  /agent/status   — unauthenticated liveness probe
# POST /agent/ping     — authenticated round-trip echo (requires X-Agent-Key)
```

Note: currently uses `!=` for key comparison (B-01 violation). After B-01,
the comparison uses `hmac.compare_digest()`.

---

## 3. Anti-Duplication Rules

These rules are enforced at code review. A PR that violates them must not be
merged, regardless of whether the tests pass.

### 3.1 ZipCrypto — ONE implementation

`web/lib/zipcrypto.py` is the single canonical ZipCrypto implementation.

Rule: Any new code that produces a `.dat` file MUST call
`from web.lib.zipcrypto import build_dat_bytes` (or from the relative path
`from .zipcrypto import build_dat_bytes` within `web/lib/`).

Forbidden: inline implementations of `_make_crc_table`, `_init_keys`,
`_stream_byte`, or `write_zipcrypto` anywhere outside `zipcrypto.py`.

Context: the original repo had ZipCrypto duplicated in 4 CLI scripts
(`convert_dat.py`, `split_dat.py`, `generate_dat.py`, `dsbx_to_dat.py`).
These are eliminated by DL-01 through DL-05.

### 3.2 Controller Registry — ONE source of truth

After DL-07, the controller-family metadata lives exclusively in `dat_utils.py`:

```python
CONTROLLER_REGISTRY: dict  # per-controller metadata
OPPOSITE:     dict[str, str]      # derived from registry
NEEDS_IMG:    frozenset[str]      # derived from registry
NEEDS_NETWORK: frozenset[str]     # derived from registry
FAMILY_MAP:   dict[str, dict]     # derived from registry
```

Current behaviour: `FAMILY_MAP`, `NEEDS_IMG`, `NEEDS_NETWORK` are duplicated
in `dsbx_utils.py`. After DL-07, `dsbx_utils.py` imports them from `dat_utils`.

Rule: Adding a new controller type means editing `dat_utils.CONTROLLER_REGISTRY`
only. No other file should define these constants independently.

### 3.3 File-format Parsers — ONE canonical implementation

| Parser | Canonical location | Forbidden duplication |
|--------|-------------------|----------------------|
| DAT parsing | `dat_utils.parse_dat_controllers()` | Inline `pyzipper.AESZipFile` + XML parse in routes or CLI |
| DSBX parsing | `dsbx_utils.parse_dsbx_bytes()` | Inline `zipfile.ZipFile` + ET.fromstring in routes or CLI |
| LEV Kit DSBX | `lev_kit_utils.parse_dsbx()` | Separate from `dsbx_utils` — LEV Kit parses LEV-specific XML |

### 3.4 Shared JS Utilities — `web/static/js/shared.js`

After HC-04, `web/static/js/shared.js` is the single source for:

- `escHtml(str)` — HTML escaping
- `apiCall(url, options)` — standardised fetch wrapper with error handling
- `MTDZ_API` / `API` — base URL constant

Both `base.html` and `site_base.html` load `shared.js` before any
page-specific script.

Current behaviour: `escHtml` is defined in `main.js` AND inline in
`site_index.html`; the MTDZ `const API` is duplicated across 5 JS files.

Rule after HC-04: `grep -r "function escHtml" web/static/js/` must return
exactly one result (in `shared.js`). CI enforces this.

### 3.5 CSS Foundation — `web/static/css/base.css`

After HC-03, `web/static/css/base.css` defines all shared tokens:

- `:root` CSS custom properties (colours, spacing, breakpoints)
- Universal reset (`*, *::before, *::after { box-sizing }`)
- Shared components: `.card`, `.btn`, `.btn-primary`, `.btn-outline`,
  `.drop-zone`, `.alert` variants, `.breadcrumb`, `header`, `footer`,
  `.info-popup`, `.info-popup-overlay`

`style.css` and `site.css` retain only page-family-specific styles.

Current behaviour: these rules are duplicated across `style.css` and `site.css`.

---

## 4. Adding a New Tool — Concrete Recipe

This walkthrough shows exactly what to create when adding a new VRFTools feature.
Hypothetical example: a "DSBX Inspector" tool that displays DSBX file contents
in a tree view. It consumes `dsbx_utils` — no new domain module needed.

### Step 1: Create `web/lib/dsbx_inspector_routes.py`

```python
"""
DSBX Inspector — route handlers.
Translates HTTP into dsbx_utils calls. No business logic here.
"""
from flask import Blueprint, jsonify, abort
from flask import request as flask_request

from .dsbx_utils import parse_dsbx_bytes, get_groupof50_list, extract_group_cards, load_mapping
from . import sessions

dsbx_inspector_bp = Blueprint("dsbx_inspector", __name__)


@dsbx_inspector_bp.route("/dsbx-inspector")
def page_dsbx_inspector():
    from flask import render_template
    return render_template("dsbx_inspector.html")


@dsbx_inspector_bp.route("/api/dsbx-inspector/upload", methods=["POST"])
def api_dsbx_inspector_upload():
    f = flask_request.files.get("file")
    if not f:
        abort(400, "No file provided.")
    data = f.read()
    if len(data) > 5 * 1024 * 1024:
        abort(413, "File exceeds 5 MB limit.")

    # Domain call: parse the DSBX — pure logic, no Flask inside dsbx_utils
    try:
        root = parse_dsbx_bytes(data)
        mapping = load_mapping()
        groups_per_block = [
            extract_group_cards(g50, mapping)
            for g50 in get_groupof50_list(root)
        ]
    except (ValueError, KeyError) as exc:
        abort(400, f"Could not parse .dsbx file: {exc}")

    sid = sessions.create({
        "type": "dsbx_inspector",
        "dsbx_data": data,
        "blocks": [{"groups": g} for g in groups_per_block],
    })
    return jsonify({"session_id": sid, "blocks": groups_per_block})
```

### Step 2: Register blueprint in `web/app.py`

```python
from lib.dsbx_inspector_routes import dsbx_inspector_bp

app.register_blueprint(dsbx_inspector_bp)
```

After B-20 (app factory), this goes inside `create_app()`:

```python
def create_app(config_name="default"):
    app = Flask(__name__)
    # ...
    from lib.dsbx_inspector_routes import dsbx_inspector_bp
    app.register_blueprint(dsbx_inspector_bp)
    return app
```

### Step 3: Create `web/templates/dsbx_inspector.html`

```html
{% extends "base.html" %}
{% block title %}DSBX Inspector{% endblock %}

{% block content %}
<div class="page-title">DSBX Inspector</div>
<div class="drop-zone" id="dsbx-drop-zone" role="button" tabindex="0"
     aria-label="Upload a .dsbx file to inspect">
  <p>Drop a <code>.dsbx</code> file here or click to browse</p>
  <input type="file" id="dsbx-file-input" accept=".dsbx" style="display:none">
</div>
<div id="dsbx-error" class="alert alert-error" role="alert" style="display:none"></div>
<div id="dsbx-results" style="display:none"></div>
{% endblock %}

{% block scripts %}
<script src="{{ url_for('static', filename='js/dsbx_inspector.js') }}"></script>
{% endblock %}
```

Notes:
- Extends `base.html` (config-tools family) — use `site_base.html` for site pages.
- Error container uses `role="alert"` for accessibility (HC-01 pattern).
- Page-specific script block loads after `shared.js` (already in `base.html`).

### Step 4: Create `web/static/js/dsbx_inspector.js`

```javascript
// dsbx_inspector.js — DSBX Inspector page logic
// Uses shared.js utilities: escHtml(), apiCall()
// No inline escaping, no bare fetch() calls.

(function () {
  "use strict";

  const dropZone  = document.getElementById("dsbx-drop-zone");
  const fileInput = document.getElementById("dsbx-file-input");
  const errorDiv  = document.getElementById("dsbx-error");
  const results   = document.getElementById("dsbx-results");

  function showError(msg) {
    errorDiv.textContent = msg;
    errorDiv.style.display = "block";
  }

  async function uploadFile(file) {
    errorDiv.style.display = "none";
    const form = new FormData();
    form.append("file", file);

    // apiCall() from shared.js — no bare fetch(), consistent error handling
    let data;
    try {
      data = await apiCall("/api/dsbx-inspector/upload", {
        method: "POST",
        body: form,
      });
    } catch (err) {
      showError(err.message || "Upload failed.");
      return;
    }

    // Render results using escHtml() from shared.js — no XSS
    let html = "";
    data.blocks.forEach((block, bi) => {
      html += `<h3>Block ${bi + 1}</h3><ul>`;
      block.forEach(g => {
        html += `<li>${escHtml(g.tag)} — slot ${g.slot}</li>`;
      });
      html += "</ul>";
    });
    results.innerHTML = html;
    results.style.display = "block";
  }

  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("keydown", e => {
    if (e.key === "Enter" || e.key === " ") fileInput.click();
  });
  fileInput.addEventListener("change", e => {
    if (e.target.files[0]) uploadFile(e.target.files[0]);
  });
  dropZone.addEventListener("dragover", e => e.preventDefault());
  dropZone.addEventListener("drop", e => {
    e.preventDefault();
    if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
  });
})();
```

### Step 5: Add `tests/test_dsbx_inspector_routes.py`

```python
"""Integration tests for the DSBX Inspector blueprint."""
import io
import zipfile
import pytest

# conftest.py adds web/ to sys.path and provides app_client fixture
from web.app import create_app  # after B-20; before that: from web.app import app


@pytest.fixture
def client():
    # After B-20: app = create_app("testing")
    from web.app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _make_dsbx(xml_content: str) -> bytes:
    """Wrap XML bytes in a .dsbx archive (zip with 'xml' entry)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("xml", xml_content.encode("utf-8"))
    return buf.getvalue()


MINIMAL_DSBX_XML = """<?xml version="1.0"?>
<DSBXProject><Project><Groupof50><Name>Test</Name></Groupof50></Project></DSBXProject>
"""


def test_upload_valid_dsbx(client):
    data = _make_dsbx(MINIMAL_DSBX_XML)
    resp = client.post(
        "/api/dsbx-inspector/upload",
        data={"file": (io.BytesIO(data), "test.dsbx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 200
    body = resp.get_json()
    assert "session_id" in body
    assert "blocks" in body


def test_upload_no_file(client):
    resp = client.post("/api/dsbx-inspector/upload")
    assert resp.status_code == 400


def test_upload_oversized_file(client):
    large = _make_dsbx("x" * (6 * 1024 * 1024))
    resp = client.post(
        "/api/dsbx-inspector/upload",
        data={"file": (io.BytesIO(large), "big.dsbx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 413


def test_page_renders(client):
    resp = client.get("/dsbx-inspector")
    assert resp.status_code == 200
    assert b"DSBX Inspector" in resp.data
```

### Step 6: No new domain module needed

The DSBX Inspector reuses `dsbx_utils.parse_dsbx_bytes`, `dsbx_utils.extract_group_cards`,
and `sessions`. A new domain module is only justified when:

- The logic genuinely cannot be expressed using existing modules, AND
- It contains business logic that should be testable without HTTP context, AND
- At least two callers will use it (route handler + test, at minimum).

If you only need to combine existing domain functions with a new URL and template,
create a routes file and template only.

---

## 5. Forbidden Patterns

The following patterns are automatically grounds for a PR rejection:

### 5.1 Inline ZipCrypto

Rejected: Any file outside `web/lib/zipcrypto.py` defining `_make_crc_table`,
`_init_keys`, `_update_keys`, `_stream_byte`, or a `write_zipcrypto` function.
Use `from .zipcrypto import build_dat_bytes` instead.

### 5.2 Inline Parsers

Rejected: A route handler (or any non-domain file) calling
`pyzipper.AESZipFile` or `ET.fromstring` directly on uploaded bytes without
going through a domain function. Route handlers receive bytes and pass them
to `parse_dat_controllers()` or `parse_dsbx_bytes()` — that is all.

### 5.3 Copy-Pasted Controller Registry

Rejected: Defining `OPPOSITE`, `FAMILY_MAP`, `NEEDS_IMG`, or `NEEDS_NETWORK`
in any file other than `dat_utils.py` after DL-07. If `dsbx_utils.py` still has
its own copy of these constants, that is a known pre-DL-07 violation, not a new one.

### 5.4 File I/O in Route Handlers

Rejected:
```python
# BAD — file I/O in a route handler
@app.route("/api/something", methods=["POST"])
def api_something():
    with open("/some/path/file.xml") as f:
        data = f.read()
    # ...
```

Allowed: reading uploaded file bytes from `request.files`, writing response bytes
via `send_file`. The actual file path resolution belongs in the domain layer
(use `dat_utils.TEMPLATES_DIR` or `REPO_ROOT` env var).

### 5.5 Hardcoded Paths

Rejected:
```python
path = "/app/templates/AE-C400A.xml"         # hardcoded absolute path
path = "../../templates/AE-C400A.xml"        # relative path that breaks in tests
```

Required pattern:
```python
import os
REPO_ROOT = os.environ.get(
    "VRFTOOLS_ROOT",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
)
path = os.path.join(REPO_ROOT, "templates", "AE-C400A.xml")
```

### 5.6 Untyped Dict Configs in New Domain APIs

Rejected in new code:
```python
def new_compute(config: dict) -> dict:  # "config" with magic string keys
```

Required pattern — use a dataclass (see `SwitchConfig` precedent from DL-09):
```python
from dataclasses import dataclass

@dataclass
class MyConfig:
    capacity: int
    control_mode: str
    heat_pump: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "MyConfig":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

def new_compute(config: MyConfig) -> dict: ...
```

This rule applies to NEW domain APIs. Existing callers using `dict` continue
to work via `from_dict()` for backward compatibility.

### 5.7 Direct Storage Access from JS

Rejected: JS code calling a database URL, a Redis endpoint, or directly reading
session files. All data access goes through Flask routes.

### 5.8 Global Mutable State in JS

Rejected:
```javascript
// BAD — module-level mutable state leaks between pages if JS is cached
let currentSession = null;
window._graphData = {};
```

Required: wrap state in an IIFE closure or, for new code, use ES modules:
```javascript
// GOOD — state is private to the IIFE
(function () {
  "use strict";
  let currentSession = null;
  // ...
})();
```

---

## 6. Test Contract

### 6.1 Test file naming

| Module | Required test file |
|--------|-------------------|
| `web/lib/zipcrypto.py` | `tests/test_zipcrypto.py` |
| `web/lib/dat_utils.py` | `tests/test_dat_utils.py` |
| `web/lib/dsbx_utils.py` | `tests/test_dsbx_utils.py` |
| `web/lib/lev_kit_utils.py` | `tests/test_lev_kit_utils.py` |
| `web/lib/json_utils.py` | `tests/test_json_utils.py` |
| `web/lib/sessions.py` | `tests/test_sessions.py` |
| New `web/lib/<name>_routes.py` | `tests/test_<name>_routes.py` |

These test files must exist before a corresponding module or blueprint is
considered "covered". A PR adding a new domain function must include its test.

### 6.2 What each test file covers

Domain module tests (e.g. `test_dat_utils.py`) test the public API in isolation:
- Pass in bytes/primitives, assert on the returned bytes/dicts.
- No Flask, no HTTP, no network.
- Use `tmp_path` fixture for any disk writes.

Blueprint route tests (e.g. `test_dsbx_inspector_routes.py`) use Flask's test client:
- Test the full HTTP round-trip: upload file -> get response.
- Cover success path, 400 (bad input), 413 (oversized), 404 (missing session).
- Do NOT test internal domain logic; that belongs in the domain module test.

### 6.3 Test infrastructure

`tests/conftest.py` must:
- Add `web/lib/` to `sys.path` so domain modules are importable.
- Provide fixture paths for sample DAT/DSBX/JSON files (from `templates/`
  and `Empty Configs/`).
- Provide a `secret_bytes` fixture (`b"test-secret"`) for `json_utils` tests.
- Provide an `app_client` fixture using `create_app("testing")` after B-20;
  until then, `from web.app import app; app.config["TESTING"] = True`.

`pyproject.toml` must define:
```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
addopts = "-v"
```

Running `pytest` from the repo root must discover and run all tests with zero
special setup (no env vars, no Docker, no external services).

### 6.4 Merge gate

No PR adding a new domain module or route blueprint may be merged until:
1. The corresponding `tests/test_<module>.py` file exists.
2. Every public function in the new module has at least one test.
3. `pytest` exits 0 locally.

---

## 7. Directory Reference

```
vrf-tools/
  web/
    app.py                  Flask entry point (monolith -> blueprints in B-09 to B-12)
    lib/
      zipcrypto.py          ZipCrypto — canonical, single implementation
      dat_utils.py          DAT parsing, conversion, splitting, rearrangement
      dsbx_utils.py         DSBX parsing and DAT XML generation
      lev_kit_utils.py      LEV Kit DIP switch computation + PDF rendering
      json_utils.py         HMAC-signed JSON export/import
      sessions.py           File-based session store (-> Redis in B-21)
      agent_routes.py       Hermes agent Blueprint (already a Blueprint)
      dat_routes.py         DAT tool Blueprint (B-09, landed at 3f6424a)
      route_helpers.py      Shared HTTP-context wrappers (B-09, landed at 3f6424a)
      dsbx_routes.py        DSBX tool Blueprint (B-10, landed at 8d01d27)
      lev_kit_routes.py     LEV Kit Blueprint (B-11, current)
      config_hub_routes.py  (future — B-12)
      proxy_routes.py       (future — B-12)
    templates/
      base.html             config-tools base template (loads shared.js, base.css)
      site_base.html        site/marketing base template
      *.html                page templates (extend one of the two bases)
      mtdz/                 MTDZ sub-app templates
    static/
      css/
        base.css            (future — HC-03) shared CSS variables + components
        style.css           config-tools-specific styles
        site.css            site-specific styles
        lev_kit.css         LEV Kit batch page styles
        lev_kit_single.css  LEV Kit wizard page styles
        mtdz.css            MTDZ sub-app styles
      js/
        shared.js           (future — HC-04) escHtml, apiCall, shared constants
        main.js             config-tools shared JS (slot grid, upload helpers)
        lev_kit.js          LEV Kit batch page IIFE
        lev_kit_single.js   LEV Kit wizard IIFE
        contact.js          Contact form handler
        mtdz/
          common.js         (future — MF-02) shared MTDZ utilities
          hub.js, viewer.js, report.js, sysinfo.js
  tests/
    conftest.py             shared fixtures and sys.path setup
    fixtures/               sample DAT, DSBX, JSON files for tests
    test_zipcrypto.py
    test_dat_utils.py
    test_dsbx_utils.py
    test_lev_kit_utils.py
    test_json_utils.py
    test_sessions.py
    test_agent_routes.py
  templates/                DAT XML templates (used by domain layer, not deployed as HTML)
  docs/
    ARCHITECTURE.md         this document
  pyproject.toml            pytest configuration
  CLAUDE.md                 agent guidance
```

---

## 8. Refactor Phase Map

This document describes the end state. The following phases get there:

| Phase | Cards | Key changes |
|-------|-------|-------------|
| P0 | P0-01 to P0-06 | Repo setup, this doc, tooling baseline |
| Domain | DL-01 to DL-08 | ZipCrypto deduplication, controller registry, safe_filename |
| Domain | DL-09 to DL-14 | Type annotations, SwitchConfig, DSBX validation |
| Domain | DL-15 to DL-19 | Unit tests for all domain modules |
| Domain | DL-20 to DL-25 | PDF decomposition, logging, REPO_ROOT robustness |
| Backend | B-01 to B-08 | Security fixes, error handling, logging |
| Backend | B-09 to B-13 | Blueprint extraction (dat, dsbx, lev_kit, hub, proxy) |
| Backend | B-14 to B-15 | Session file locking, JSON migration |
| Backend | B-16 to B-19 | Tests, request logging |
| Backend | B-20 to B-22 | App factory, Redis sessions, CSRF |
| Frontend | LF/MF/HC steps | CSS foundation, shared JS, responsive, accessibility |

---

*Architecture document. Maintained alongside the code — update this file when
module boundaries change. Last updated: 2026-05-19.*
