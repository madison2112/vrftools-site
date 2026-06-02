// ── VRFTools Shared Utilities ────────────────────────────────────────────────
// Loaded on every page via base.html / site_base.html, before per-page scripts.
// Keep this file small — only genuinely shared helpers live here.

/**
 * Escape HTML special characters.
 *   escHtml('<b>hello</b>')  →  '&lt;b&gt;hello&lt;/b&gt;'
 */
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

/**
 * Minimal fetch wrapper.  Callers pass any headers (CSRF, Content-Type, …)
 * in `init`; this handles JSON unwrap and error surfacing.
 *
 *   const data = await apiCall('/api/session/lev-kit-blank', {
 *     method: 'POST',
 *     headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() },
 *     body: '{}',
 *   });
 */
async function apiCall(url, init) {
  let resp;
  try {
    resp = await fetch(url, init);
  } catch (e) {
    throw new Error('Network error: ' + e.message);
  }
  let body = null;
  try { body = await resp.json(); } catch (e) { /* non-JSON response */ }
  if (!resp.ok) {
    throw new Error((body && body.error) || `Request failed (${resp.status})`);
  }
  return body || {};
}

// ── Focus Trap ────────────────────────────────────────────────────────────────

(function() {
  var _trapPreviousFocus = null;

  window.trapFocus = function(modalEl) {
    _trapPreviousFocus = document.activeElement;

    var FOCUSABLE = 'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';
    var focusable = modalEl.querySelectorAll(FOCUSABLE);
    var first = focusable[0];
    var last  = focusable[focusable.length - 1];

    function handleKeyDown(e) {
      if (e.key !== 'Tab') return;
      if (e.shiftKey) {
        if (document.activeElement === first || !modalEl.contains(document.activeElement)) {
          e.preventDefault();
          last && last.focus();
        }
      } else {
        if (document.activeElement === last || !modalEl.contains(document.activeElement)) {
          e.preventDefault();
          first && first.focus();
        }
      }
    }

    modalEl.addEventListener('keydown', handleKeyDown);
    modalEl._trapHandler = handleKeyDown;

    if (first) first.focus();
  };

  window.releaseFocus = function() {
    if (_trapPreviousFocus && typeof _trapPreviousFocus.focus === 'function') {
      _trapPreviousFocus.focus();
    }
    _trapPreviousFocus = null;
  };
})();

// ── Download countdown + Ko-Fi support note ──────────────────────────────
// Shows a 10s circular countdown with an instant "download now" link and a
// "buy me a beer" support note. The actual download (triggerFn) fires when the
// circle reaches zero or the user clicks "download now". Used by every tool's
// download button. Because downloads are served as attachments, firing does not
// navigate away, so the thank-you note stays visible.
(function () {
  var KOFI_URL = 'https://ko-fi.com/tylermadison';

  window.startDownloadCountdown = function (triggerFn, triggerBtn, opts) {
    opts = opts || {};
    var seconds = opts.seconds || 10;

    var anchor = (triggerBtn && triggerBtn.closest('.btn-row')) || triggerBtn;
    if (!anchor || !anchor.parentNode) { triggerFn(); return; }

    var existing = document.getElementById('dl-countdown-panel');
    if (existing) existing.remove();

    var panel = document.createElement('div');
    panel.id = 'dl-countdown-panel';
    panel.className = 'dl-countdown';
    panel.setAttribute('role', 'status');
    panel.innerHTML =
      '<div class="dl-countdown-timer" aria-hidden="true">' +
        '<svg class="dl-countdown-ring" viewBox="0 0 40 40">' +
          '<circle class="dl-ring-track" cx="20" cy="20" r="16"></circle>' +
          '<circle class="dl-ring-progress" cx="20" cy="20" r="16"></circle>' +
        '</svg>' +
        '<span class="dl-countdown-num">' + seconds + '</span>' +
      '</div>' +
      '<div class="dl-countdown-text">' +
        '<div class="dl-countdown-status">Your download will start in ' +
          '<span class="dl-secs">' + seconds + '</span>s. ' +
          '<a href="#" class="dl-now-link">Download now</a>.</div>' +
        '<div class="dl-kofi">If you find these tools helpful, please consider supporting ' +
          'future development or <a href="' + KOFI_URL + '" target="_blank" rel="noopener">buy me a beer</a>.</div>' +
      '</div>';
    anchor.parentNode.insertBefore(panel, anchor.nextSibling);

    var ring = panel.querySelector('.dl-ring-progress');
    var circumference = 2 * Math.PI * 16;
    ring.style.strokeDasharray = String(circumference);
    ring.style.strokeDashoffset = '0';

    var numEl = panel.querySelector('.dl-countdown-num');
    var secsEl = panel.querySelector('.dl-secs');
    var statusEl = panel.querySelector('.dl-countdown-status');

    var fired = false;
    var start = Date.now();

    function fire() {
      if (fired) return;
      fired = true;
      clearInterval(iv);
      numEl.textContent = '0';
      secsEl.textContent = '0';
      ring.style.strokeDashoffset = String(circumference);
      statusEl.innerHTML = 'Download started — check your downloads folder.';
      try { triggerFn(); } catch (err) { /* swallow; nav errors are non-fatal */ }
    }

    var iv = setInterval(function () {
      var elapsed = (Date.now() - start) / 1000;
      var remaining = Math.max(0, seconds - elapsed);
      var shown = Math.ceil(remaining);
      numEl.textContent = String(shown);
      secsEl.textContent = String(shown);
      ring.style.strokeDashoffset = String(circumference * (1 - remaining / seconds));
      if (remaining <= 0) fire();
    }, 100);

    panel.querySelector('.dl-now-link').addEventListener('click', function (e) {
      e.preventDefault();
      fire();
    });
  };
})();
