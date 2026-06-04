/**
 * tutorial-engine.js — generic guided-tour overlay with interaction gating.
 *
 * Tool-agnostic. Drive it with:
 *     window.startTutorial(toolId, steps)
 *
 * It renders a spotlight + tooltip over a target element and supports two
 * kinds of steps:
 *   - mode:'watch' — explain (optionally play a `demo`), advance via "Next".
 *   - mode:'do'    — the user must perform a real action on the (mock) UI.
 *                    The Next button is replaced by a locked gate; the step
 *                    `advanceOn(target, ctx)` wires up listeners and calls
 *                    ctx.done() to pass or ctx.fail(hint) to nudge.
 *
 * No backend calls. Depends only on shared.js for trapFocus/releaseFocus
 * (used on non-'do' steps so the spotlighted control stays reachable).
 *
 * Step schema:
 *   { target, title, body, arrow:'up'|'down'|'left'|'right'|null,
 *     mode:'watch'|'do', demo:fn(targetEl), autoDemo:Bool, showMe:Bool,
 *     advanceOn:fn(targetEl,{done,fail,signal}), gateLabel, hint,
 *     canSkipAction:Bool, onEnter:fn, onExit:fn }
 */
(function () {
  'use strict';

  var SEEN_PREFIX = 'vrftools_tutorial_seen_';  // any interaction → suppress first-visit prompt
  var DONE_PREFIX = 'vrftools_tutorial_done_';  // reached the end → green "completed" banner

  function el(tag, cls, html) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  function Tutorial(toolId, steps, opts) {
    this.toolId = toolId;
    this.steps = steps;
    this.opts = opts || {};
    this.exitUrl = this.opts.exitUrl || null;
    this.i = 0;
    this.overlay = null;
    this.spotlight = null;
    this.tooltip = null;
    this.activeStep = null;   // the step whose overlay is currently mounted
    this.abort = null;        // AbortController for the active 'do' step
    this._onResize = this._reposition.bind(this);
    this._onKey = this._handleKey.bind(this);
  }

  Tutorial.prototype.start = function () {
    document.addEventListener('keydown', this._onKey, true);
    window.addEventListener('resize', this._onResize);
    window.addEventListener('scroll', this._onResize, true);
    this._render();
  };

  Tutorial.prototype.go = function (n) {
    if (n < 0 || n >= this.steps.length) return;
    this.i = n;
    this._render();
  };

  Tutorial.prototype._advance = function () {
    if (this.i >= this.steps.length - 1) { this.complete(); return; }
    this.go(this.i + 1);
  };

  // Tear down whatever is currently mounted (listeners, onExit, DOM).
  Tutorial.prototype._teardownActive = function () {
    if (this.abort) { this.abort.abort(); this.abort = null; }
    if (this.activeStep && typeof this.activeStep.onExit === 'function') {
      try { this.activeStep.onExit(); } catch (e) {}
    }
    if (this.overlay) { this.overlay.remove(); this.overlay = null; }
    this.activeStep = null;
  };

  // Leave the tutorial (it owns its page, so leaving = navigating back to the
  // hub). Always set the seen-flag so the first-visit prompt won't nag again.
  // Only set the *done* flag — which drives the green "completed" banner — when
  // the user actually reached the end (completed === true). There is never a
  // state where the page is shown without the window.
  Tutorial.prototype._leave = function (completed) {
    this._teardownActive();
    document.removeEventListener('keydown', this._onKey, true);
    window.removeEventListener('resize', this._onResize);
    window.removeEventListener('scroll', this._onResize, true);
    try {
      localStorage.setItem(SEEN_PREFIX + this.toolId, '1');
      if (completed) localStorage.setItem(DONE_PREFIX + this.toolId, '1');
    } catch (e) {}
    if (typeof window.releaseFocus === 'function') window.releaseFocus();
    if (this.exitUrl) window.location.href = this.exitUrl;
  };
  Tutorial.prototype.exit = function () { this._leave(false); };     // Exit Tutorial / Esc
  Tutorial.prototype.complete = function () { this._leave(true); };  // Finish

  // Restart from the top without leaving the page (used by "Replay Tutorial").
  Tutorial.prototype.replay = function () {
    this.go(0);
  };

  Tutorial.prototype._handleKey = function (e) {
    if (e.key === 'Escape') { e.preventDefault(); this.exit(); }
  };

  Tutorial.prototype._render = function () {
    this._teardownActive();

    var self = this;
    var step = this.steps[this.i];
    var isDo = step.mode === 'do';
    var isLast = this.i === this.steps.length - 1;

    // Run onEnter (e.g. mock phase toggle) BEFORE measuring the target so the
    // spotlight reads the correct element in the now-visible phase.
    if (typeof step.onEnter === 'function') { try { step.onEnter(); } catch (e) {} }

    var overlay = el('div', 'tut-overlay');
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.setAttribute('aria-label', 'Tutorial step ' + (this.i + 1) + ' of ' + this.steps.length);

    var spotlight = el('div', 'tut-spotlight');
    overlay.appendChild(spotlight);

    var tooltip = el('div', 'tut-tooltip');

    var dots = el('div', 'tut-step-dots');
    for (var d = 0; d < this.steps.length; d++) {
      var st = (d === this.i) ? ' active' : (d < this.i ? ' done' : '');
      dots.appendChild(el('span', 'tut-dot' + st));
    }
    tooltip.appendChild(dots);

    tooltip.appendChild(el('div', 'tut-count', 'Step ' + (this.i + 1) + ' of ' + this.steps.length));
    tooltip.appendChild(el('h3', 'tut-title', step.title || ''));
    tooltip.appendChild(el('div', 'tut-body', step.body || ''));

    this.hintEl = el('div', 'tut-hint');
    this.hintEl.style.display = 'none';
    tooltip.appendChild(this.hintEl);


    if (step.showMe && typeof step.demo === 'function') {
      var showBtn = el('button', 'tut-showme', '&#9654;&#65039; Show me how');
      showBtn.type = 'button';
      showBtn.addEventListener('click', function () { self._runDemo(); });
      tooltip.appendChild(showBtn);
    }

    // Two-row layout: the step's primary control(s) on top, then a nav row with
    // Back pinned bottom-left and Exit/Replay bottom-right. (A single wrapping
    // row left Skip below Back and stacked the gate/Back/Exit awkwardly.)
    var actions = el('div', 'tut-actions');
    var mainRow = el('div', 'tut-actions-main');
    var navRow = el('div', 'tut-actions-nav');

    // Main row carries only the do-step "waiting" gate (+ optional Skip). On
    // watch steps it stays empty and is omitted, so the nav row sits tight.
    if (isDo) {
      this.gateEl = el('span', 'tut-gate', step.gateLabel || 'Try it to continue');
      // Clicks on the gate (and anywhere else off the real control) are handled
      // by the page-wide "wait pulse" listener wired below — see _bindWaitPulse.
      mainRow.appendChild(this.gateEl);
      if (step.canSkipAction) {
        var skipOne = el('button', 'tut-btn tut-btn-skipone', 'Skip &rarr;');
        skipOne.type = 'button';
        skipOne.addEventListener('click', function () { self._advance(); });
        mainRow.appendChild(skipOne);
      }
    }

    // Nav row is a 3-column grid — Back (left) · Next/Finish (centre) ·
    // Exit/Replay (right) — so the primary button is anchored dead-centre
    // between the two regardless of their widths or whether Back is present.
    if (this.i > 0) {
      var back = el('button', 'tut-btn tut-btn-back', '&larr; Back');
      back.type = 'button';
      back.addEventListener('click', function () { self.go(self.i - 1); });
      navRow.appendChild(back);
    }

    if (!isDo) {
      var next = el('button', 'tut-btn tut-btn-next', isLast ? 'Finish &#10003;' : 'Next &rarr;');
      next.type = 'button';
      next.addEventListener('click', function () { isLast ? self.complete() : self._advance(); });
      navRow.appendChild(next);
    }

    // Skip-position button: "Exit Tutorial" everywhere, except on the final
    // step where it becomes "Replay Tutorial" (restart instead of leave).
    var skip = el('button', 'tut-btn tut-btn-skip', isLast ? 'Replay Tutorial' : 'Exit Tutorial');
    skip.type = 'button';
    skip.addEventListener('click', function () { isLast ? self.replay() : self.exit(); });
    navRow.appendChild(skip);

    if (mainRow.children.length) actions.appendChild(mainRow);
    actions.appendChild(navRow);
    tooltip.appendChild(actions);
    overlay.appendChild(tooltip);
    document.body.appendChild(overlay);

    this.overlay = overlay;
    this.spotlight = spotlight;
    this.tooltip = tooltip;
    this.activeStep = step;

    this._reposition();

    // Wire up the gate for 'do' steps.
    if (isDo && typeof step.advanceOn === 'function') {
      this.abort = new AbortController();
      var ctx = {
        signal: this.abort.signal,
        done: function () { self._gatePass(); },
        fail: function (msg) { self._showHint(msg || step.hint); },
      };
      var target = step.target ? document.querySelector(step.target) : null;
      try { step.advanceOn(target, ctx); } catch (e) {}
    }

    // While a 'do' step is waiting, a click anywhere on the page that isn't the
    // real control or a deliberate nav button (Back / Exit / Skip / Show-me)
    // nudges attention back by pulsing the target's ring + surfacing the hint.
    // Testers repeatedly clicked the waiting line or empty space expecting
    // something to happen, so every "wrong" click now gives feedback.
    if (isDo) this._bindWaitPulse(step);

    if (step.autoDemo && typeof step.demo === 'function') {
      // Defer so the overlay has painted before the demo animates.
      setTimeout(function () { self._runDemo(); }, 250);
    }

    // Watch steps may opt to advance when the user clicks the highlighted
    // target itself (used for the controller-name step: the field is a
    // read-only animation, so clicking where it plays acts like "Next").
    if (!isDo && step.clickTargetAdvances) {
      var ctgt = step.target ? document.querySelector(step.target) : null;
      if (ctgt) {
        this.abort = this.abort || new AbortController();
        ctgt.style.cursor = 'pointer';
        ctgt.addEventListener('click', function () { self._advance(); }, { signal: this.abort.signal });
      }
    }

    // Trap focus only on non-'do' steps; 'do' steps need the underlying
    // control (e.g. a tag-edit input) to receive focus.
    if (!isDo && typeof window.trapFocus === 'function') {
      window.trapFocus(tooltip);
    }
  };

  Tutorial.prototype._runDemo = function () {
    var step = this.steps[this.i];
    if (typeof step.demo !== 'function') return;
    var target = step.target ? document.querySelector(step.target) : null;
    try { step.demo(target); } catch (e) {}
  };

  Tutorial.prototype._gatePass = function () {
    var self = this;
    var step = this.steps[this.i];
    if (this.abort) { this.abort.abort(); this.abort = null; }
    if (this.gateEl) { this.gateEl.classList.add('passed'); this.gateEl.innerHTML = '&#10003; Done'; }
    if (this.hintEl) this.hintEl.style.display = 'none';
    // No green "affirm" box — the gate flipping to "✓ Done" is confirmation
    // enough. Hold briefly so that Done state is visible, then advance.
    setTimeout(function () { self._advance(); }, 650);
  };

  // Wire a page-wide click listener for the active 'do' step. Shares the step's
  // AbortController, so it's removed automatically on gate-pass or teardown.
  Tutorial.prototype._bindWaitPulse = function (step) {
    var self = this;
    this.abort = this.abort || new AbortController();
    var targetEl = step.target ? document.querySelector(step.target) : null;
    document.addEventListener('click', function (e) {
      var t = e.target;
      // Let real navigation and the actual control do their job, unpestered.
      if (t.closest && t.closest('.tut-btn-back, .tut-btn-skip, .tut-btn-skipone, .tut-showme')) return;
      if (targetEl && targetEl.contains(t)) return;
      self._pulseSpotlight();
      self._showHint(step.hint);
    }, { signal: this.abort.signal, capture: true });
  };

  Tutorial.prototype._pulseSpotlight = function () {
    var spot = this.spotlight;
    if (!spot || spot.style.display === 'none') return;
    spot.classList.remove('tut-spotlight-pulse');
    void spot.offsetWidth; // restart the animation
    spot.classList.add('tut-spotlight-pulse');
  };

  Tutorial.prototype._showHint = function (msg) {
    if (!msg || !this.hintEl) return;
    this.hintEl.innerHTML = '&#128161; ' + msg;
    this.hintEl.style.display = '';
    // Re-anchor now that the tooltip grew taller. The per-arrow formulas keep
    // the correct edge fixed (e.g. 'down' pins the bottom and expands upward),
    // so the buttons don't get pushed off — without this the box stayed
    // top-anchored and slid down over its own controls.
    this._reposition();
  };

  Tutorial.prototype._reposition = function () {
    if (!this.overlay) return;
    var step = this.steps[this.i];
    var spot = this.spotlight;
    var tip = this.tooltip;
    var target = step.target ? document.querySelector(step.target) : null;

    var ARROWS = ['tut-arrow-up', 'tut-arrow-down', 'tut-arrow-left', 'tut-arrow-right'];

    if (!target) {
      spot.style.display = 'none';
      tip.classList.add('tut-centered');
      ARROWS.forEach(function (c) { tip.classList.remove(c); });
      tip.style.top = '50%';
      tip.style.left = '50%';
      tip.style.transform = 'translate(-50%, -50%)';
      return;
    }

    spot.style.display = '';
    tip.classList.remove('tut-centered');
    tip.style.transform = '';

    var r = target.getBoundingClientRect();
    var pad = 6;
    spot.style.top = (r.top - pad) + 'px';
    spot.style.left = (r.left - pad) + 'px';
    spot.style.width = (r.width + pad * 2) + 'px';
    spot.style.height = (r.height + pad * 2) + 'px';

    var arrow = step.arrow || 'up';
    ARROWS.forEach(function (c) { tip.classList.remove(c); });
    var gap = 28;
    var tw = tip.offsetWidth;
    var th = tip.offsetHeight;
    var vw = window.innerWidth;
    var vh = window.innerHeight;
    var top, left;

    if (arrow === 'up') {
      tip.classList.add('tut-arrow-up');
      top = r.bottom + gap;
      left = r.left + r.width / 2 - tw / 2;
    } else if (arrow === 'down') {
      tip.classList.add('tut-arrow-down');
      top = r.top - gap - th;
      left = r.left + r.width / 2 - tw / 2;
    } else if (arrow === 'left') {
      tip.classList.add('tut-arrow-left');
      top = r.top + r.height / 2 - th / 2;
      left = r.right + gap;
    } else {
      tip.classList.add('tut-arrow-right');
      top = r.top + r.height / 2 - th / 2;
      left = r.left - gap - tw;
    }

    left = Math.max(12, Math.min(left, vw - tw - 12));
    top = Math.max(12, Math.min(top, vh - th - 12));

    // Safety: never let the tooltip cover its own target (would block the
    // user's click/drag). If the clamped position overlaps the target, move
    // the tooltip below it — or above if there isn't room below.
    var overlaps = !(left + tw < r.left || left > r.right || top + th < r.top || top > r.bottom);
    if (overlaps) {
      // Re-point the arrow to match the side we relocate to, so it never ends
      // up pointing away from its target after the clamp.
      ARROWS.forEach(function (c) { tip.classList.remove(c); });
      if (r.bottom + gap + th <= vh - 12) {
        top = r.bottom + gap;
        tip.classList.add('tut-arrow-up');
      } else {
        top = Math.max(12, r.top - gap - th);
        tip.classList.add('tut-arrow-down');
      }
      left = Math.max(12, Math.min(r.left + r.width / 2 - tw / 2, vw - tw - 12));
    }

    tip.style.top = top + 'px';
    tip.style.left = left + 'px';
  };

  window.startTutorial = function (toolId, steps, opts) {
    var t = new Tutorial(toolId, steps, opts);
    t.start();
    return t;
  };
})();
