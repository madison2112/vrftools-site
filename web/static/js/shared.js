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
