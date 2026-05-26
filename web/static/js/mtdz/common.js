// ── MTDZ Common — Shared helpers for all MTDZ pages ─────────────────────────
// Loaded before page-specific scripts on all MTDZ templates.
// No file: protocol fallback — vrf-tools is always served over HTTP.

const API = '';

function isMobile() {
  return window.innerWidth < 768;
}

// escHtml has moved to shared.js

function clearStoredSession() {
  try {
    ['session_id','file_type','days','systems','sensor_catalog','topology','filename']
      .forEach(function (k) { localStorage.removeItem(k); });
    sessionStorage.removeItem('mtdz_session_id');
    sessionStorage.removeItem('mtdz_file_name');
    sessionStorage.removeItem('mtdz_file_type');
    sessionStorage.removeItem('mtdz_days');
  } catch (_) { /* ignore quota / cross-origin errors */ }
}

function handleExpired() {
  clearStoredSession();
  var pages = window.MTDZ_PAGES || {};
  window.location.href = (pages.index || '/mtdz/') + '?expired=1';
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
