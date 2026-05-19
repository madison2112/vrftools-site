// Polls /status and shows sticky banners for:
//   1. Scheduled server restarts (existing)
//   2. Session expiry at 1:00 AM PST (new)
// Severity ramps as deadlines approach; banners disappear when signals clear.
// Silently no-ops on any error so a backend hiccup never breaks the page.
(function () {
  "use strict";

  var POLL_MS = 30 * 1000;

  // ── Shared helpers ──────────────────────────────────────────────────

  function ensureBanner(id) {
    var el = document.getElementById(id);
    if (!el) {
      el = document.createElement("div");
      el.id = id;
      document.body.insertBefore(el, document.body.firstChild);
    }
    return el;
  }

  function clearBanner(id) {
    var el = document.getElementById(id);
    if (el) {
      el.className = "";
      el.textContent = "";
      el.style.display = "none";
    }
  }

  function plural(n, word) {
    return n + " " + word + (n === 1 ? "" : "s");
  }

  // ── Restart banner (existing) ───────────────────────────────────────

  var RESTART_BANNER_ID = "restart-banner";

  function renderRestartBanner(minsLeft) {
    var el = ensureBanner(RESTART_BANNER_ID);
    el.style.display = "block";
    var rounded = Math.max(0, Math.ceil(minsLeft));
    var tier, msg;
    if (rounded <= 2) {
      tier = "restart-banner-critical";
      msg = "⚠ Server restart in " + plural(rounded, "minute") +
            " — save your work immediately.";
    } else if (rounded <= 6) {
      tier = "restart-banner-warning";
      msg = "Server restart in " + plural(rounded, "minute") +
            " — please save now.";
    } else {
      tier = "restart-banner-notice";
      msg = "Scheduled server restart in " + plural(rounded, "minute") +
            ". Please save your work before then.";
    }
    el.className = "restart-banner " + tier;
    el.textContent = msg;
  }

  // ── Session-expiry banner (new) ─────────────────────────────────────

  var SESSION_BANNER_ID = "session-expiry-banner";
  var SESSION_WARN_MINUTES = 30; // only show banner in last 30 min

  function renderSessionBanner(minsLeft) {
    var el = ensureBanner(SESSION_BANNER_ID);
    el.style.display = "block";
    var rounded = Math.max(0, Math.ceil(minsLeft));
    var tier, msg;
    if (rounded <= 5) {
      tier = "session-banner-critical";
      msg = "⏰ Session expires in " + plural(rounded, "minute") +
            " at 1:00 AM PST — generate your PDF now.";
    } else if (rounded <= 15) {
      tier = "session-banner-warning";
      msg = "Session expires in " + plural(rounded, "minute") +
            " at 1:00 AM PST — please finish your work soon.";
    } else {
      tier = "session-banner-notice";
      msg = "Session expires in " + plural(rounded, "minute") +
            " at 1:00 AM PST. All unsaved settings will be lost.";
    }
    el.className = "session-banner " + tier;
    el.textContent = msg;
  }

  // ── Polling ─────────────────────────────────────────────────────────

  function tick() {
    fetch("/status", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data) return;

        // ── Restart check ──
        if (data.restart_at) {
          var restartT = Date.parse(data.restart_at);
          if (!isNaN(restartT)) {
            var restartMins = (restartT - Date.now()) / 60000;
            if (restartMins > 0) {
              renderRestartBanner(restartMins);
            } else {
              clearBanner(RESTART_BANNER_ID);
            }
          } else {
            clearBanner(RESTART_BANNER_ID);
          }
        } else {
          clearBanner(RESTART_BANNER_ID);
        }

        // ── Session expiry check ──
        if (data.session_expiry_at) {
          var sessT = data.session_expiry_at;
          // session_expiry_at might be a float (Unix timestamp) or ISO string
          if (typeof sessT === "number") sessT = sessT * 1000;
          else sessT = Date.parse(sessT);
          if (!isNaN(sessT)) {
            var sessMins = (sessT - Date.now()) / 60000;
            if (sessMins > 0 && sessMins <= SESSION_WARN_MINUTES) {
              renderSessionBanner(sessMins);
            } else {
              clearBanner(SESSION_BANNER_ID);
            }
          } else {
            clearBanner(SESSION_BANNER_ID);
          }
        } else {
          clearBanner(SESSION_BANNER_ID);
        }
      })
      .catch(function () { /* swallow — never break the page */ });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", tick);
  } else {
    tick();
  }
  setInterval(tick, POLL_MS);
})();
