// Polls /status and shows a sticky banner when a server restart is scheduled.
// Banner severity ramps as the deadline approaches; disappears when the
// signal clears (post-restart). Silently no-ops on any error so a backend
// hiccup never breaks the page.
(function () {
  "use strict";

  var POLL_MS = 30 * 1000;
  var BANNER_ID = "restart-banner";

  function ensureBanner() {
    var el = document.getElementById(BANNER_ID);
    if (!el) {
      el = document.createElement("div");
      el.id = BANNER_ID;
      document.body.insertBefore(el, document.body.firstChild);
    }
    return el;
  }

  function clearBanner() {
    var el = document.getElementById(BANNER_ID);
    if (el) {
      el.className = "";
      el.textContent = "";
      el.style.display = "none";
    }
  }

  function renderBanner(minsLeft) {
    var el = ensureBanner();
    el.style.display = "block";
    var rounded = Math.max(0, Math.ceil(minsLeft));
    var tier, msg;
    if (rounded <= 2) {
      tier = "restart-banner-critical";
      msg = "⚠ Server restart in " + rounded + " minute" +
            (rounded === 1 ? "" : "s") + " — save your work immediately.";
    } else if (rounded <= 6) {
      tier = "restart-banner-warning";
      msg = "Server restart in " + rounded + " minutes — please save now.";
    } else {
      tier = "restart-banner-notice";
      msg = "Scheduled server restart in " + rounded +
            " minutes. Please save your work before then.";
    }
    el.className = "restart-banner " + tier;
    el.textContent = msg;
  }

  function tick() {
    fetch("/status", { cache: "no-store" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (!data || !data.restart_at) { clearBanner(); return; }
        var t = Date.parse(data.restart_at);
        if (isNaN(t)) { clearBanner(); return; }
        var minsLeft = (t - Date.now()) / 60000;
        if (minsLeft <= 0) { clearBanner(); return; }
        renderBanner(minsLeft);
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
