"""HC-08: visual regression for all user-facing routes.

Compares rendered screenshots against committed baselines.
Update baselines via ``make visual-baseline`` after intentional UI changes.

Baseline mode (``VISUAL_BASELINE=1``): save screenshots to ``tests/baselines/``.
Test mode (default): compare screenshots against committed baselines, fail on
pixel differences exceeding the threshold.
"""

import os
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

BASELINE_DIR = Path(__file__).parent / "baselines"

# ---------------------------------------------------------------------------
# Route definitions — every user-facing page the app serves
# ---------------------------------------------------------------------------

ROUTES: list[tuple[str, str]] = [
    ("/", "landing"),
    ("/config-tools", "config-tools"),
    ("/contact", "contact"),
    ("/docs", "docs"),
    ("/lev-kit-configurator", "lev-kit-configurator"),
    ("/lev-kit-batch", "lev-kit-batch"),
    ("/lev-kit-single/ah001", "lev-kit-single-ah001"),
    ("/lev-kit-single/ah002", "lev-kit-single-ah002"),
    ("/mtdz/", "mtdz-index"),
    ("/mtdz/viewer", "mtdz-viewer"),
    ("/mtdz/report", "mtdz-report"),
    ("/mtdz/sysinfo", "mtdz-sysinfo"),
]

# ---------------------------------------------------------------------------
# Pixel-diff threshold — absolute pixel count, not ratio.  Subpixel font
# rendering can cause tiny diffs even on identical content.  Start at 100
# and tune upward only if CI flakes from font-rendering noise.
# ---------------------------------------------------------------------------

PIXEL_DIFF_THRESHOLD = 100


def _block_external_hosts(request) -> bool:
    """Return True when the request should be blocked (non-localhost URL).

    Blocks analytics, CDN embeds, and any other external resource that
    would introduce nondeterministic timing into screenshots.
    """
    url = request.url
    # Allow only localhost and 127.0.0.1
    return not (
        url.startswith("http://127.0.0.1")
        or url.startswith("http://localhost")
        or url.startswith("about:")
    )


# ---------------------------------------------------------------------------
# Parametrized visual regression
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path,slug", ROUTES)
def test_route_visual_baseline(live_server: str, path: str, slug: str, tmp_path: Path):
    """Take a screenshot of *path* and compare against the baseline."""
    baseline = BASELINE_DIR / f"{slug}.png"
    in_baseline_mode = os.environ.get("VISUAL_BASELINE") == "1"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 800})
        page = context.new_page()

        # Block external hosts (analytics, CDNs, etc.) for deterministic
        # screenshots — these add variable latency that can cause flaky diffs.
        page.route("**/*", lambda route: (
            route.abort() if _block_external_hosts(route.request)
            else route.continue_()
        ))

        page.goto(f"{live_server}{path}", wait_until="networkidle")
        page.wait_for_timeout(300)  # let any CSS transitions settle

        if in_baseline_mode:
            page.screenshot(path=str(baseline), full_page=True)
            browser.close()
            return

        actual = tmp_path / f"{slug}.png"
        page.screenshot(path=str(actual), full_page=True)
        browser.close()

    # --- Compare against baseline (test mode) ---
    if not baseline.exists():
        pytest.skip(f"no baseline for {slug} — run `make visual-baseline` first")

    from PIL import Image, ImageChops

    img_expected = Image.open(baseline)
    img_actual = Image.open(actual)

    if img_expected.size != img_actual.size:
        pytest.fail(
            f"{slug}: size mismatch — screenshot {img_actual.size} "
            f"vs baseline {img_expected.size}"
        )

    diff = ImageChops.difference(img_expected, img_actual)
    bbox = diff.getbbox()
    if bbox is not None:
        # Count non-zero pixels in the diff (ignore fully transparent / black).
        nonzero = sum(
            1 for px in diff.getdata()
            if px != (0, 0, 0, 0) and px != (0, 0, 0)
        )
        if nonzero > PIXEL_DIFF_THRESHOLD:
            # Save diff artifact for CI upload
            diff_path = tmp_path / f"{slug}.diff.png"
            diff.save(diff_path)
            pytest.fail(
                f"{slug}: {nonzero} pixels differ from baseline "
                f"(threshold {PIXEL_DIFF_THRESHOLD}). "
                f"If intentional, run `make visual-baseline`."
            )
