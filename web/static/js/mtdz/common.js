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

// focus-trap has moved to shared.js
