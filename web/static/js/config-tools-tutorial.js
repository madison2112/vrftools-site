/**
 * config-tools-tutorial.js — DSBX→DAT walkthrough (Revision 3).
 *
 * Two parts:
 *   1. Client-only mock interaction handlers that mirror the real tool's
 *      gestures (drag-to-upload, double-click tag edit, native drag reorder,
 *      sort, save, phase toggle) with ZERO backend calls. They dispatch
 *      `mock:*` events the tutorial engine gates on.
 *   2. The STEPS array passed to window.startTutorial().
 *
 * The tutorial owns its page: finishing/exiting redirects to /config-tools.
 */
(function () {
  'use strict';

  // ── helpers ───────────────────────────────────────────────────────────────
  function $(sel, root) { return (root || document).querySelector(sel); }
  function tagText(card) {
    var t = card && card.querySelector('.group-tag');
    return t ? t.textContent.trim() : '';
  }
  function emptyCard() {
    var d = document.createElement('div');
    d.className = 'slot-empty-card';
    return d;
  }
  function fire(name, detail) {
    document.dispatchEvent(new CustomEvent(name, { detail: detail || {} }));
  }

  // ── looping demo animations (cleared on step exit) ──────────────────────────
  // Demos are chains of setTimeouts (type → fade → reset, cursor glides, etc.).
  // Leaving a step must cancel ALL of them, not just intervals — otherwise a
  // late callback (e.g. the rename fade-reset) clobbers state the next step set.
  var loopTimers = [];
  var pendingTimeouts = [];
  function startLoop(fn, ms) { fn(); loopTimers.push(setInterval(fn, ms)); }
  // Like startLoop, but the gap is measured from the END of each run: play the
  // demo, wait gapMs AFTER it signals completion, then replay. The demo must
  // invoke the onDone callback it's handed. Cancellable via stopLoops (it only
  // chains setTimeouts through later(), no interval).
  function loopDemo(demoFn, gapMs) {
    function run() {
      var done = false;
      demoFn(function () { if (done) return; done = true; later(run, gapMs); });
    }
    run();
  }
  function later(fn, ms) { var id = setTimeout(fn, ms); pendingTimeouts.push(id); return id; }
  function stopLoops() {
    loopTimers.forEach(clearInterval); loopTimers = [];
    pendingTimeouts.forEach(clearTimeout); pendingTimeouts = [];
    document.querySelectorAll('.tut-drag-ghost').forEach(function (g) { g.remove(); });
  }

  // ── animated demo cursor (oversized pointer / hand) ─────────────────────────
  // A single fixed element glided with CSS transforms. The "hotspot" is the
  // active point of each glyph (arrow tip / fingertip) so it lands on target.
  var ARROW_SVG =
    '<svg width="32" height="32" viewBox="0 0 28 28" aria-hidden="true">' +
    '<path d="M6 4 L6 23 L11 18 L14.4 25 L17.2 23.6 L13.9 17 L21 17 Z" ' +
    'fill="#fff" stroke="#1a1a1a" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  var HAND_SVG =
    '<svg width="38" height="38" viewBox="0 0 32 32" aria-hidden="true">' +
    '<path d="M12 15 V7.5 a2 2 0 0 1 4 0 V13 h1 a2 2 0 0 1 2 2 v1 a2 2 0 0 1 2 2 ' +
    'v1 a2 2 0 0 1 2 2 v2.5 a4 4 0 0 1-4 4 h-4.5 a4 4 0 0 1-3-1.4 L7.8 22.5 ' +
    'a2 2 0 0 1 3-2.6 l1.2 1.2 Z" ' +
    'fill="#fff" stroke="#1a1a1a" stroke-width="1.6" stroke-linejoin="round"/></svg>';
  var HOTSPOTS = { arrow: { x: 7, y: 5 }, hand: { x: 14, y: 7 } };

  var cursorEl = null, cursorGlyph = 'hand';
  function cursor() {
    if (!cursorEl || !document.body.contains(cursorEl)) {
      cursorEl = document.createElement('div');
      cursorEl.className = 'tut-cursor';
      cursorEl.innerHTML = HAND_SVG;
      cursorGlyph = 'hand';
      document.body.appendChild(cursorEl);
    }
    return cursorEl;
  }
  function setGlyph(name) {
    var c = cursor();
    if (cursorGlyph === name) return;
    cursorGlyph = name;
    c.innerHTML = (name === 'arrow') ? ARROW_SVG : HAND_SVG;
  }
  function hot() { return HOTSPOTS[cursorGlyph] || HOTSPOTS.hand; }
  function placeCursorAt(x, y) {
    var c = cursor(), h = hot();
    c.style.transition = 'none';
    c.style.transform = 'translate(' + (x - h.x) + 'px,' + (y - h.y) + 'px)';
    c.getBoundingClientRect(); // flush before the next transitioned move
  }
  function moveCursorTo(x, y, ms, cb) {
    var c = cursor(), h = hot();
    c.style.transition = 'transform ' + (ms / 1000) + 's ease';
    c.style.transform = 'translate(' + (x - h.x) + 'px,' + (y - h.y) + 'px)';
    if (cb) later(cb, ms);
  }
  function cursorClickPulse() {
    var c = cursor();
    c.classList.remove('clicking');
    void c.offsetWidth; // restart the animation
    c.classList.add('clicking');
  }
  function cursorGrab(on) { cursor().classList.toggle('grabbing', !!on); }
  function removeCursor() {
    if (cursorEl) { cursorEl.remove(); cursorEl = null; }
    cursorGlyph = 'hand';
  }

  // ── phase toggle (explicit block/none; stylesheet defaults dsbx to none) ────
  function showHubPhase() {
    var hub = $('#mock-hub'), dsbx = $('#mock-dsbx');
    if (hub) hub.style.display = 'block';
    if (dsbx) dsbx.style.display = 'none';
  }
  function showDsbxPhase() {
    var hub = $('#mock-hub'), dsbx = $('#mock-dsbx');
    if (hub) hub.style.display = 'none';
    if (dsbx) dsbx.style.display = 'block';
  }

  // ── drop zone + file chip (hub) ──────────────────────────────────────────────
  function initMockDropZone() {
    var zone = $('#mock-drop-zone');
    if (!zone) return;
    zone.addEventListener('click', loadDemoFile);
    zone.addEventListener('dragover', function (e) { e.preventDefault(); zone.classList.add('dragging'); });
    zone.addEventListener('dragleave', function () { zone.classList.remove('dragging'); });
    zone.addEventListener('drop', function (e) { e.preventDefault(); zone.classList.remove('dragging'); loadDemoFile(); });
  }
  function initFileChip() {
    var chip = $('#mock-file-chip');
    if (!chip) return;
    chip.addEventListener('dragstart', function (e) { e.dataTransfer.effectAllowed = 'copy'; e.dataTransfer.setData('text/plain', 'demo'); });
  }
  // Captured once at boot so we can restore the pristine "drop a file" state
  // when the user navigates back to the load step (treat it as not-yet-started).
  var dropZoneInitialHTML = null;
  function captureDropZoneInitial() {
    var zone = $('#mock-drop-zone');
    if (zone && dropZoneInitialHTML === null) dropZoneInitialHTML = zone.innerHTML;
  }
  function applyFileLoaded() {
    var zone = $('#mock-drop-zone');
    if (!zone) return;
    zone.dataset.loaded = '1';
    // Mirror the real resetZone() success state instead of a styled badge.
    zone.innerHTML =
      '<div class="icon" style="color:var(--green)">&#10003;</div>' +
      '<p><strong>VRFtools-Demo.dsbx</strong> uploaded</p>' +
      '<small>Click or drag &amp; drop to upload a different file</small>';
    var chip = $('#mock-file-chip');
    if (chip) chip.style.display = 'none';
    var card = $('.mock-tool-card[data-tool="dsbx-to-dat"]');
    if (card) card.classList.add('highlighted');
  }
  function loadDemoFile() {
    var zone = $('#mock-drop-zone');
    if (!zone || zone.dataset.loaded === '1') return;
    applyFileLoaded();
    fire('mock:fileloaded');
  }
  // Re-arm the load step: pristine drop zone, chip back, card un-highlighted.
  function resetFileUnloaded() {
    var zone = $('#mock-drop-zone');
    if (zone) {
      delete zone.dataset.loaded;
      if (dropZoneInitialHTML !== null) zone.innerHTML = dropZoneInitialHTML;
    }
    var chip = $('#mock-file-chip');
    if (chip) chip.style.display = '';
    var card = $('.mock-tool-card[data-tool="dsbx-to-dat"]');
    if (card) card.classList.remove('highlighted');
  }
  // Ensure the "file is loaded" outcome is in place (used on the open-converter
  // step, whose own action — clicking the green card — hasn't happened yet but
  // whose precondition, the loaded file, must be visible).
  function ensureFileLoaded() {
    var zone = $('#mock-drop-zone');
    if (zone && zone.dataset.loaded !== '1') applyFileLoaded();
  }

  // ── tool card (hub) ──────────────────────────────────────────────────────────
  function initMockToolCards() {
    document.querySelectorAll('.mock-tool-card').forEach(function (card) {
      card.addEventListener('click', function () {
        if (card.dataset.tool === 'dsbx-to-dat' && card.classList.contains('highlighted')) {
          fire('mock:opentool');
        }
      });
    });
  }

  // ── back link (dsbx) — visual only, no longer a tutorial step ────────────────
  function initMockBackLink() {
    var link = $('#mock-back-link');
    if (link) link.addEventListener('click', function (e) { e.preventDefault(); });
  }

  // ── save / share + download (dsbx) ───────────────────────────────────────────
  function initMockSave() {
    var btn = $('#mock-float-save');
    if (btn) btn.addEventListener('click', function () { fire('mock:save'); });
  }
  function initMockDownload() {
    var btn = $('#mock-btn-download');
    if (btn) btn.addEventListener('click', function () { fire('mock:download'); });
  }

  // ── double-click group-tag editing (dsbx) — port of main.js, no fetch ────────
  function initMockTagEdit() {
    document.addEventListener('dblclick', function (e) {
      var tagEl = e.target.closest('#mock-slots .group-tag');
      if (!tagEl || tagEl.querySelector('.group-tag-edit')) return;

      var currentText = tagEl.textContent.trim();
      var input = document.createElement('input');
      input.type = 'text';
      input.className = 'group-tag-edit';
      input.value = currentText;
      input.style.width = Math.max(currentText.length * 10 + 20, 80) + 'px';
      // Do NOT clear the tag text first. Production keeps it: the input is
      // position:absolute/inset:0 (style.css) and overlays the text, so the tag
      // keeps its height and you get a white red-bordered box "cut into" the
      // grey card. Clearing collapsed the tag to 0px and hid the editor.

      var done = false;
      function commit() {
        if (done) return;
        done = true;
        var newTag = input.value.trim();
        tagEl.textContent = newTag || currentText;
        input.remove();
        fire('mock:tagcommit', { tag: tagEl.textContent.trim() });
      }
      function cancel() { if (done) return; done = true; tagEl.textContent = currentText; input.remove(); }

      input.addEventListener('blur', commit);
      input.addEventListener('keydown', function (ke) {
        if (ke.key === 'Enter') { ke.preventDefault(); commit(); }
        if (ke.key === 'Escape') { ke.preventDefault(); cancel(); }
      });

      tagEl.appendChild(input);
      input.focus();
      // Caret at the END (not select-all): the lesson is appending "-4" to
      // "IDU". Selecting all meant the first keystroke wiped "IDU" and left "-4".
      input.setSelectionRange(input.value.length, input.value.length);
    });
  }

  // ── native drag reorder (dsbx) — node-swap variant of initSlotGrid ───────────
  var dragSrcSlot = null;
  function allSlots() { return [].slice.call(document.querySelectorAll('#mock-slots .slot-item')); }
  function bindDrag() {
    allSlots().forEach(function (slot) {
      if (slot.dataset.dragBound === '1') return; // slot-items persist across resets
      slot.dataset.dragBound = '1';
      slot.addEventListener('dragstart', function (e) {
        if (!slot.querySelector('.group-card')) return;
        dragSrcSlot = slot;
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', '');
      });
      slot.addEventListener('dragend', function () {
        allSlots().forEach(function (s) { s.classList.remove('drag-over'); });
        dragSrcSlot = null;
      });
      slot.addEventListener('dragover', function (e) { if (dragSrcSlot && dragSrcSlot !== slot) e.preventDefault(); });
      slot.addEventListener('dragenter', function (e) {
        if (!dragSrcSlot || dragSrcSlot === slot) return;
        e.preventDefault(); // allow the drop; no red over-highlight (matches the demo)
      });
      slot.addEventListener('drop', function (e) {
        e.preventDefault();
        slot.classList.remove('drag-over');
        if (!dragSrcSlot || dragSrcSlot === slot) return;
        var srcChild = dragSrcSlot.firstElementChild;
        var dstChild = slot.firstElementChild;
        dragSrcSlot.appendChild(dstChild);
        slot.appendChild(srcChild);
        dragSrcSlot = null;
        fire('mock:reorder');
      });
    });
  }

  // Re-home every card to its initial slot (by data-home), MOVING nodes so tag
  // edits and slot-item drag listeners are preserved. Resets order only.
  function resetGrid() {
    var container = $('#mock-slots');
    if (!container) return;
    var slots = allSlots();
    var cards = [].slice.call(container.querySelectorAll('.group-card'));
    slots.forEach(function (s) { s.innerHTML = ''; });
    cards.forEach(function (c) {
      var pos = parseInt(c.dataset.home, 10);
      if (slots[pos - 1]) slots[pos - 1].appendChild(c);
    });
    slots.forEach(function (s) { if (!s.firstElementChild) s.appendChild(emptyCard()); });
  }

  // ── sort by tag (dsbx) — FLIP animation, no fetch ────────────────────────────
  function initMockSort() {
    var btn = $('#mock-sort-btn');
    if (btn) btn.addEventListener('click', sortMock);
  }
  function sortMock() {
    var container = $('#mock-slots');
    if (!container) return;
    var slots = allSlots();
    var cards = slots.map(function (s) { return s.querySelector('.group-card'); }).filter(Boolean);

    var first = new Map();
    cards.forEach(function (c) { first.set(c, c.getBoundingClientRect()); });

    var sorted = cards.slice().sort(function (a, b) {
      return tagText(a).localeCompare(tagText(b), undefined, { numeric: true, sensitivity: 'base' });
    });
    slots.forEach(function (s, i) { s.innerHTML = ''; s.appendChild(sorted[i] || emptyCard()); });

    cards.forEach(function (c) {
      var f = first.get(c), l = c.getBoundingClientRect();
      var dx = f.left - l.left, dy = f.top - l.top;
      if (dx || dy) {
        c.style.transition = 'none';
        c.style.transform = 'translate(' + dx + 'px,' + dy + 'px)';
        requestAnimationFrame(function () { c.style.transition = 'transform .45s ease'; c.style.transform = ''; });
      }
    });
    fire('mock:sort');
  }

  // ── typing helper ─────────────────────────────────────────────────────────────
  function typeInto(input, text, opts, onDone) {
    opts = opts || {};
    var typeMs = opts.speed || 75;
    var delMs = opts.delSpeed || 45;
    input.focus();
    var clearFirst = opts.clear !== false;
    var step = function () {
      if (clearFirst && input.value.length) { input.value = input.value.slice(0, -1); later(step, delMs); }
      else {
        clearFirst = false;
        if (input.value.length < text.length) { input.value = text.slice(0, input.value.length + 1); later(step, typeMs); }
        else if (onDone) onDone();
      }
    };
    step();
  }

  // ── demos ──────────────────────────────────────────────────────────────────────

  // Step "Load file": loop a ghost of the file chip gliding onto the drop zone.
  function demoDropGhost() {
    var chip = $('#mock-file-chip'), zone = $('#mock-drop-zone');
    if (!chip || !zone || zone.dataset.loaded === '1' || chip.style.display === 'none') return;
    var cr = chip.getBoundingClientRect(), zr = zone.getBoundingClientRect();
    var ghost = chip.cloneNode(true);
    ghost.id = '';
    ghost.className = 'mock-file-chip tut-drag-ghost';
    ghost.style.position = 'fixed';
    ghost.style.left = cr.left + 'px';
    ghost.style.top = cr.top + 'px';
    ghost.style.margin = '0';
    document.body.appendChild(ghost);
    ghost.getBoundingClientRect();
    var dx = (zr.left + zr.width / 2) - (cr.left + cr.width / 2);
    var dy = (zr.top + zr.height / 2) - (cr.top + cr.height / 2);
    ghost.style.transition = 'transform 1s ease, opacity .3s ease .8s';
    ghost.style.transform = 'translate(' + dx + 'px,' + dy + 'px)';
    ghost.style.opacity = '0';
    later(function () { ghost.remove(); }, 1300);
  }

  // Step "Name controller": one self-contained cycle, looped. Show the default
  // name, backspace it, type the demo name, pause, then FADE back to the default
  // (rather than visibly backspacing the demo name, which reads as glitchy).
  var renameBusy = false;
  function demoRenameCycle() {
    var input = $('#mock-ctrl-name');
    if (!input || renameBusy) return;
    renameBusy = true;
    input.style.transition = '';
    input.style.opacity = '1';
    input.value = 'Centralized System - 1';
    typeInto(input, 'VRFtools Demo', { clear: true }, function () {
      later(function () {
        input.style.transition = 'opacity .45s ease';
        input.style.opacity = '0';
        later(function () {
          input.value = 'Centralized System - 1';
          input.style.opacity = '1';
          renameBusy = false;
        }, 480);
      }, 1000);
    });
  }
  function resetRename() {
    stopLoops();
    renameBusy = false;
    var input = $('#mock-ctrl-name');
    if (input) { input.style.transition = ''; input.style.opacity = '1'; input.value = 'Centralized System - 1'; }
  }
  // Once past the naming step, the controller keeps its new name for the rest
  // of the run (shown on the IP step and beyond).
  function showRenamedController() {
    stopLoops();
    renameBusy = false;
    var input = $('#mock-ctrl-name');
    if (input) { input.style.transition = ''; input.style.opacity = '1'; input.value = 'VRFtools Demo'; }
  }
  // Re-arm the fix-tag step: card back to the starting "IDU", fully opaque.
  function resetFixTag() {
    var card = $('#mock-card-idu4');
    var tagEl = card && card.querySelector('.group-tag');
    if (!tagEl) return;
    var stray = tagEl.querySelector('.group-tag-edit');
    if (stray) stray.remove();
    tagEl.textContent = 'IDU';
    card.style.transition = '';
    card.style.opacity = '1';
  }

  // Step "Fix tag": a plain pointer starts to the LEFT of the group cards and
  // glides (slowly) to the IDU tag, turning into a hand only once it's over the
  // card. It double-clicks just above the IDU text and is removed immediately
  // (no lingering "click and hold"); the editor then types "-4", commits in
  // place, and the card fades back to the starting state. Purely visual — it
  // never fires mock:tagcommit, so it can't satisfy the gate for the user.
  function demoFixTag(onDone) {
    var card = $('#mock-card-idu4');
    var tagEl = card && card.querySelector('.group-tag');
    var slots = $('#mock-slots');
    if (!card || !tagEl || tagEl.querySelector('.group-tag-edit')) { if (onDone) onDone(); return; }
    var gr = tagEl.getBoundingClientRect();       // the IDU text (for cursor start)
    var cr = card.getBoundingClientRect();        // the card (for the click point)
    var sr = slots ? slots.getBoundingClientRect() : { left: gr.left };
    // Aim the double-click at 1/8 across the card (from its left edge) and
    // vertically centred. Card-relative fractions keep it consistent at any size.
    var clickX = cr.left + cr.width / 8;
    var clickY = cr.top + cr.height / 2;

    setGlyph('arrow');                            // a pointer, not a hand, to start
    placeCursorAt(Math.max(20, sr.left - 60), clickY);
    moveCursorTo(clickX, clickY, 1100, function () {
      setGlyph('hand');                           // becomes a hand once over the card
      cursorClickPulse();
      later(cursorClickPulse, 170);               // second click = double-click on IDU
      later(removeCursor, 360);                   // remove right after the double-click
      later(function () {
        // Leave the "IDU" text in place — the absolute-positioned input
        // overlays it (see initMockTagEdit), giving the production "white box
        // cut into the card" look instead of a collapsed/invisible field.
        var input = document.createElement('input');
        input.type = 'text';
        input.className = 'group-tag-edit';
        input.value = 'IDU';
        input.style.width = '90px';
        tagEl.appendChild(input);
        input.focus();
        // Slow type — append "-4" to reach IDU-4 (caret already at end).
        input.setSelectionRange(input.value.length, input.value.length);
        typeInto(input, 'IDU-4', { clear: false, speed: 190 }, function () {
          later(function () {
            input.remove();
            tagEl.textContent = 'IDU-4';          // show the committed result
            // Pause, then fade the IDU-4 card out and restore the starting card
            // so the USER performs the real edit.
            later(function () {
              card.style.transition = 'opacity .45s ease';
              card.style.opacity = '0';
              later(function () {
                tagEl.textContent = 'IDU';
                card.style.opacity = '1';
                if (onDone) onDone();     // animation fully complete
              }, 470);
            }, 850);
          }, 420);
        });
      }, 460);
    });
  }

  // Step "Reorder": arrow cursor glides to the card, becomes a hand, grabs it,
  // drags a ghost up to the open top slot, releases. Purely visual.
  function demoDrag(onDone) {
    var card = $('#mock-card-idu1');
    var destSlot = $('#mock-slots .slot-item'); // top slot
    var tip = $('.tut-tooltip');
    if (!card || !destSlot) { if (onDone) onDone(); return; }
    var cr = card.getBoundingClientRect(), dr = destSlot.getBoundingClientRect();
    var tr = tip ? tip.getBoundingClientRect() : { right: window.innerWidth, top: cr.top };

    setGlyph('arrow');
    placeCursorAt(tr.right + 24, cr.top + 36);
    moveCursorTo(cr.left + cr.width / 2, cr.top + cr.height / 2, 700, function () {
      setGlyph('hand');           // turns into a hand over the card
      cursorGrab(true);
      var ghost = card.cloneNode(true);
      ghost.id = '';
      ghost.className = 'group-card tut-drag-ghost';
      ghost.style.position = 'fixed';
      ghost.style.left = cr.left + 'px';
      ghost.style.top = cr.top + 'px';
      ghost.style.width = cr.width + 'px';
      ghost.style.height = cr.height + 'px';
      ghost.style.margin = '0';
      document.body.appendChild(ghost);
      ghost.getBoundingClientRect();
      ghost.style.transition = 'transform .9s ease';
      ghost.style.transform = 'translate(' + (dr.left - cr.left) + 'px,' + (dr.top - cr.top) + 'px)';
      moveCursorTo(dr.left + cr.width / 2, dr.top + cr.height / 2, 900, function () {
        cursorGrab(false);          // release — no click pulse on drop
        later(function () { ghost.remove(); removeCursor(); if (onDone) onDone(); }, 350);
      });
    });
  }

  function endCursorDemo() { stopLoops(); removeCursor(); }
  // Leaving the fix-tag step: stop the demo and make sure the card is visible
  // again (a demo fade may have been mid-flight), but keep whatever tag is
  // showing — the user's committed IDU-4 must persist into later steps.
  function fixTagOnExit() {
    endCursorDemo();
    var card = $('#mock-card-idu4');
    if (card) { card.style.transition = ''; card.style.opacity = '1'; }
  }

  // ── steps (11) ────────────────────────────────────────────────────────────────
  // Each stateful step's onEnter re-arms its own precondition so navigating
  // Back always lands on a clean "not started yet" state (no locked gates).
  // Card-grid steps put the window to the RIGHT (arrow:'left') so the slot list
  // stays visible — early testers couldn't see IDU-1/-2/-3 when the window
  // covered them, so "add -4" wasn't obvious.
  var STEPS = [
    {
      target: null, arrow: null, mode: 'watch', onEnter: showHubPhase,
      title: 'Welcome',
      body: "Let's turn a DSB export into controller-ready DAT files — you'll do each step yourself. Click <strong>Next</strong> to start.",
    },
    {
      target: '#mock-drop-zone', arrow: 'up', mode: 'do',
      onEnter: function () { showHubPhase(); resetFileUnloaded(); }, onExit: stopLoops,
      title: 'Load your file',
      body: 'Drag the file onto the upload box. (You can also click the box to browse.)',
      demo: function () { startLoop(demoDropGhost, 2500); }, autoDemo: true,
      gateLabel: 'Waiting — drag the file in',
      hint: 'Drag the file card onto the upload box — or just click the box.',
      advanceOn: function (t, ctx) {
        document.addEventListener('mock:fileloaded', function () { ctx.done(); }, { once: true, signal: ctx.signal });
      },
    },
    {
      target: '.mock-tool-card[data-tool="dsbx-to-dat"]', arrow: 'down', mode: 'do',
      onEnter: function () { showHubPhase(); ensureFileLoaded(); },
      title: 'Open the converter',
      body: 'Your file matched the <strong>DSBX → DAT</strong> tool — its card turned green. Click it to open.',
      gateLabel: 'Waiting — click the green card',
      hint: 'Click the green DSBX → DAT card to open it.',
      advanceOn: function (t, ctx) {
        document.addEventListener('mock:opentool', function () { ctx.done(); }, { once: true, signal: ctx.signal });
      },
    },
    {
      target: '#mock-ctrl-name', arrow: 'left', mode: 'watch',
      onEnter: showDsbxPhase, onExit: resetRename, clickTargetAdvances: true,
      title: 'Name your controller',
      body: 'Controllers come in based on the Centralized System name in DSB. Click the field to rename it — like <strong>VRFtools Demo</strong> — or click <strong>Next</strong>.',
      demo: function () { startLoop(demoRenameCycle, 6000); }, autoDemo: true,
    },
    {
      target: '#mock-ctrl-ip', arrow: 'left', mode: 'watch',
      onEnter: function () { showDsbxPhase(); showRenamedController(); }, clickTargetAdvances: true,
      title: 'Set the IP address (optional)',
      body: 'Optionally preset the controller’s <strong>IP address</strong> here, or leave it for the <strong>Initial Settings Tool</strong> later. Click the field or <strong>Next</strong> to continue.',
    },
    {
      target: '#mock-card-idu4', arrow: 'left', mode: 'do',
      onEnter: function () { showDsbxPhase(); resetFixTag(); }, onExit: fixTagOnExit,
      title: 'Fix a group tag',
      body: 'Groups are tagged IDU-1, IDU-2, IDU-3 — this one came in as just <strong>IDU</strong>. Double-click it and add <strong>-4</strong> to make <strong>IDU-4</strong>, then press <strong>Enter</strong> (or click away). Optional.',
      // Auto-plays on entry, then replays 5s after each run finishes.
      demo: function () { loopDemo(demoFixTag, 5000); }, autoDemo: true, canSkipAction: true,
      gateLabel: 'Waiting — make it read IDU-4',
      hint: 'Double-click the IDU tag, add -4 so it reads IDU-4, then press Enter or click away.',
      advanceOn: function (t, ctx) {
        document.addEventListener('mock:tagcommit', function (e) {
          if (e.detail && e.detail.tag === 'IDU-4') ctx.done();
          else ctx.fail('Almost — it should read exactly <strong>IDU-4</strong> (capital letters, one dash). Double-click it and try again.');
        }, { signal: ctx.signal });
      },
    },
    {
      target: '#mock-card-idu1', arrow: 'left', mode: 'do',
      onEnter: function () { showDsbxPhase(); resetGrid(); }, onExit: endCursorDemo,
      title: 'Reorder by dragging',
      body: 'Groups load in slot order. Drag <strong>IDU-1</strong> up into the open slot at the top.',
      // Auto-plays on entry, then replays 5s after each run finishes.
      demo: function () { loopDemo(demoDrag, 5000); }, autoDemo: true,
      gateLabel: 'Waiting — drag IDU-1 to the top',
      hint: 'Press and hold IDU-1, drag it onto the open top slot, and release.',
      advanceOn: function (t, ctx) {
        document.addEventListener('mock:reorder', function () {
          var first = $('#mock-slots .slot-item .group-tag');
          if (first && first.textContent.trim() === 'IDU-1') ctx.done();
          else ctx.fail('Not quite — drag the <strong>IDU-1</strong> card into the open slot at the very top.');
        }, { signal: ctx.signal });
      },
    },
    {
      target: '#mock-sort-btn', arrow: 'left', mode: 'do', onEnter: showDsbxPhase,
      title: 'Sort by tag name',
      body: 'Or let the tool do it — click <strong>Sort by Tag Name</strong> to order every group automatically.',
      gateLabel: 'Waiting — click Sort by Tag Name',
      hint: 'Click the “Sort by Tag Name” button above the groups.',
      advanceOn: function (t, ctx) {
        document.addEventListener('mock:sort', function () { ctx.done(); }, { once: true, signal: ctx.signal });
      },
    },
    {
      target: '#mock-float-save', arrow: 'right', mode: 'do', onEnter: showDsbxPhase,
      title: 'Save or share',
      body: 'Real <strong>.dat</strong> files are often blocked by email, but <strong>.json</strong> isn’t. A saved .json reloads your session here, or lets someone else open and download it. Click <strong>Save Session / Share</strong>.',
      gateLabel: 'Waiting — click Save Session / Share',
      hint: 'Click the “Save Session / Share” button in the bottom-right corner.',
      advanceOn: function (t, ctx) {
        document.addEventListener('mock:save', function () { ctx.done(); }, { once: true, signal: ctx.signal });
      },
    },
    {
      target: '#mock-btn-download', arrow: 'down', mode: 'do', onEnter: showDsbxPhase,
      title: 'Download your DAT files',
      body: 'When you’re happy, click <strong>Download</strong> for ready-to-load DAT files — one per controller.',
      gateLabel: 'Waiting — click Download',
      hint: 'Click the Download button.',
      advanceOn: function (t, ctx) {
        document.addEventListener('mock:download', function () { ctx.done(); }, { once: true, signal: ctx.signal });
      },
    },
    {
      target: null, arrow: null, mode: 'watch', onEnter: showDsbxPhase,
      title: '🎉 You’ve got it!',
      body: 'That’s it — you loaded a file, named the controller, fixed a tag, reordered, sorted, and saved. Click <strong>Finish</strong> for the real tools, or <strong>Replay Tutorial</strong>.',
    },
  ];

  // ── boot ────────────────────────────────────────────────────────────────────
  captureDropZoneInitial();
  initMockDropZone();
  initFileChip();
  initMockToolCards();
  initMockBackLink();
  initMockSave();
  initMockDownload();
  initMockTagEdit();
  bindDrag();
  initMockSort();
  showHubPhase();

  if (typeof window.startTutorial === 'function') {
    window.startTutorial('dsbx-to-dat', STEPS, { exitUrl: '/config-tools' });
  }
})();
