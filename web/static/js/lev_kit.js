/* LEV Kit Configurator -- frontend logic.
 *
 * Two start paths:
 *   A) Drop-zone upload of a .dsbx -> POST /api/upload/lev-kit
 *   B) "Add LEV Kits manually"     -> POST /api/session/lev-kit-blank
 * Both land in the same editor:
 *      Edit per-unit settings        -> POST /api/session/<sid>/lev-kit-update
 *      Generate PDF (per layout btn) -> GET  /api/download/lev-kit/<sid>?layout=...
 *
 * Refrigerant routing: each unit carries a controller_type
 * ("PAC-AH001" | "PAC-AH002"). The project-level Refrigerant Type radio
 * controls which controller-group block(s) are visible; the DSBX upload
 * handler auto-selects the radio based on the parser's controllers_found
 * summary. AH001 units have additional inputs (fan_controlled_by + extras
 * gated by it); when fan_controlled_by=BAS, the extras are disabled.
 */

(() => {
  'use strict';

  const $  = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  // Controller-type constants — keep these aligned with lev_kit_utils.CONTROLLER_AHxxx.
  const C_AH001 = 'PAC-AH001';
  const C_AH002 = 'PAC-AH002';

  // ---------------------------------------------------------------------------
  // DOM cache
  // ---------------------------------------------------------------------------

  function tablesFor(suffix) {
    return {
      basicTbody:   $(`#lk-basic-tbody-${suffix}`),
      datTbody:     $(`#lk-dat-tbody-${suffix}`),
      ratTbody:     $(`#lk-rat-tbody-${suffix}`),
      basicSection: $(`#lk-basic-section-${suffix}`),
      datSection:   $(`#lk-dat-section-${suffix}`),
      ratSection:   $(`#lk-rat-section-${suffix}`),
      addNew:       $(`#lk-basic-add-new-${suffix}`),
    };
  }

  const els = {
    upload: {
      step:        $('#lk-step-upload'),
      dropZone:    $('#lk-drop-zone'),
      file:        $('#lk-file-input'),
      error:       $('#lk-upload-error'),
      manualEntry: $('#lk-manual-entry'),
    },
    editor: {
      step:               $('#lk-step-editor'),
      projectName:        $('#lk-project-name'),
      reset:              $('#lk-reset'),
      voltage:            $('#lk-voltage'),
      generateHorizontal: $('#lk-generate-horizontal'),
      generateVertical:   $('#lk-generate-vertical'),
      generateError:      $('#lk-generate-error'),
    },
    groups: {
      ah002: $('#lk-sections-ah002'),
      ah001: $('#lk-sections-ah001'),
      wrap:  $('.lk-batch-tables'),
    },
    tables: {
      ah002: tablesFor('ah002'),
      ah001: tablesFor('ah001'),
    },
    refrigerantRadios: $$('input[name="lk-refrigerant"]'),
    warnings: {
      block:        $('#lk-warnings'),
      parserBlock:  $('#lk-parser-warnings-block'),
      parserList:   $('#lk-parser-warnings-list'),
    },
    rowTemplates: {
      ah002: {
        basic: $('#lk-basic-row-template-ah002'),
        dat:   $('#lk-dat-row-template-ah002'),
        rat:   $('#lk-rat-row-template-ah002'),
      },
      ah001: {
        basic: $('#lk-basic-row-template-ah001'),
        dat:   $('#lk-dat-row-template-ah001'),
        rat:   $('#lk-rat-row-template-ah001'),
      },
    },
  };

  let currentSession = null;
  let rowIdCounter   = 0;

  // ── Auto-save ──────────────────────────────────────────────────────────
  let _saveTimer   = null;
  let _saveStatus  = 'saved';    // 'saved' | 'saving' | 'error'

  function _saveIndicatorEl() {
    return $('#lk-save-status');
  }

  function _updateSaveIndicator() {
    const el = _saveIndicatorEl();
    if (!el) return;
    el.className = 'lk-save-status lk-save-' + _saveStatus;
    const labels = { saved: '✓ All changes saved', saving: '● Saving…', error: '⚠ Save failed — retrying' };
    el.textContent = labels[_saveStatus] || '';
  }

  function autoSave() {
    if (!currentSession || !currentSession.session_id) return;
    _saveStatus = 'saving';
    _updateSaveIndicator();
    clearTimeout(_saveTimer);
    _saveTimer = setTimeout(async () => {
      try {
        const payload = collectState();
        await apiUpdateSession(currentSession.session_id, payload);
        _saveStatus = 'saved';
      } catch (_err) {
        _saveStatus = 'error';
        // Retry once after a longer delay
        clearTimeout(_saveTimer);
        _saveTimer = setTimeout(() => autoSave(), 3000);
      }
      _updateSaveIndicator();
    }, 800);
  }

  // Apply saved overrides to dropdowns (called on editor entry after
  // fetching full session data from the new GET endpoint).
  function applyOverrides(overrides) {
    // overrides = { tag: { heat_pump: true, thermo_temp: 2, ... }, ... }
    if (!overrides || !Object.keys(overrides).length) return;
    const allBasicRows = [
      ...$$('tr[data-row-id]', els.tables.ah002.basicTbody),
      ...$$('tr[data-row-id]', els.tables.ah001.basicTbody),
    ];
    for (const basicRow of allBasicRows) {
      const tagInput = basicRow.querySelector('[data-field="tag"]');
      const tag = tagInput ? tagInput.value.trim() : '';
      if (!tag) continue;
      const ovr = overrides[tag];
      if (!ovr) continue;

      const rowId = basicRow.dataset.rowId;
      const rowsForUnit = [
        basicRow,
        findRowAcrossTables(rowId, 'datTbody'),
        findRowAcrossTables(rowId, 'ratTbody'),
      ].filter(Boolean);

      for (const row of rowsForUnit) {
        for (const el of $$('[data-field]', row)) {
          const k = el.dataset.field;
          if (!(k in ovr)) continue;
          if (el.type === 'checkbox') {
            el.checked = !!ovr[k];
          } else {
            el.value = String(ovr[k]);
          }
        }
      }

      applyEnableLock(rowId);
      applyAh001Gating(rowId);
    }
    updateModeSectionVisibility();
    _markEmptyTags();
  }

  // Mark all tag inputs that are empty with the lk-tag-empty warning class.
  function _markEmptyTags() {
    for (const input of $$('input[data-field="tag"]')) {
      input.classList.toggle('lk-tag-empty', !input.value.trim());
    }
  }

  function nextRowId() { return `r${++rowIdCounter}`; }

  function controllerKey(controller_type) {
    return controller_type === C_AH001 ? 'ah001' : 'ah002';
  }

  // ---------------------------------------------------------------------------
  // Field marshalling
  // ---------------------------------------------------------------------------

  // Integer fields share names across controllers; bool fields likewise.
  const INT_FIELDS  = new Set(['capacity', 'thermo_temp', 'dat_setpoint']);
  const BOOL_FIELDS = new Set([
    'heat_pump', 'temp_adjustment',
    'run_fan_defrost', 'electric_heat', 'use_defrost_error',
    'humidifier_installed', 'run_humidifier',
  ]);

  // Fields that only apply in one control mode; stripped at submit time so the
  // session payload stays focused. (AH001-specific fields not listed here ride
  // through unfiltered; the server tolerates unknown overrides.)
  const DAT_ONLY = new Set(['discharge_enable', 'discharge_setpoint',
                            'thermo_temp', 'dat_setpoint',
                            'run_fan_defrost']);
  const RAT_ONLY = new Set(['return_control', 'return_enable',
                            'temp_adjustment',
                            'electric_heat', 'use_defrost_error',
                            'humidifier_installed', 'run_humidifier']);

  function readField(el) {
    if (el.type === 'checkbox') return el.checked;
    const k = el.dataset.field;
    if (BOOL_FIELDS.has(k)) return el.value === 'true';
    if (INT_FIELDS.has(k))  return Number(el.value);
    return el.value;
  }

  // ---------------------------------------------------------------------------
  // API helpers
  // ---------------------------------------------------------------------------

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

  function apiBlankSession() {
    return apiCall('/api/session/lev-kit-blank', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    '{}',
    });
  }

  function apiUpdateSession(sid, payload) {
    return apiCall(`/api/session/${encodeURIComponent(sid)}/lev-kit-update`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify(payload),
    });
  }

  // ---------------------------------------------------------------------------
  // Inline error / warning display
  // ---------------------------------------------------------------------------

  function showInlineError(el, msg) {
    el.textContent = msg;
    el.style.display = '';
  }
  function clearInlineError(el) {
    el.textContent = '';
    el.style.display = 'none';
  }

  function renderWarnings(warnings) {
    const w = els.warnings;
    const have = warnings && warnings.length > 0;
    w.parserList.innerHTML = '';
    if (have) {
      for (const msg of warnings) {
        const li = document.createElement('li');
        li.textContent = msg;
        w.parserList.appendChild(li);
      }
    }
    w.parserBlock.style.display = have ? '' : 'none';
    w.block.style.display       = have ? '' : 'none';
  }

  // ---------------------------------------------------------------------------
  // Refrigerant selection — show/hide controller-group sections
  // ---------------------------------------------------------------------------

  function currentRefrigerant() {
    const r = els.refrigerantRadios.find(r => r.checked);
    return r ? r.value : 'ah002';
  }

  function setRefrigerant(value) {
    for (const r of els.refrigerantRadios) r.checked = (r.value === value);
    applyRefrigerantVisibility();
  }

  function applyRefrigerantVisibility() {
    const sel = currentRefrigerant();
    els.groups.ah002.style.display = (sel === 'ah001') ? 'none' : '';
    els.groups.ah001.style.display = (sel === 'ah002') ? 'none' : '';
    // Show per-group headings only in "both" mode
    els.groups.wrap.classList.toggle('lk-show-headings', sel === 'both');
  }

  // ---------------------------------------------------------------------------
  // Per-unit row rendering
  // ---------------------------------------------------------------------------

  function cloneRow(template, rowId, mode, tag, controller_type) {
    const frag = template.content.cloneNode(true);
    const tr = frag.querySelector('tr');
    tr.dataset.rowId          = rowId;
    tr.dataset.mode           = mode;
    tr.dataset.controllerType = controller_type;
    const tagDisplay = tr.querySelector('[data-display="tag"]');
    if (tagDisplay) tagDisplay.textContent = tag || '';
    return { frag, tr };
  }

  // Append a basic/DAT/RAT row triple for one unit, into the section group
  // that matches its controller_type.
  function appendUnitRows(unit) {
    const rowId = nextRowId();
    const mode  = unit.control_mode === 'return' ? 'return' : 'discharge';
    const ctrl  = unit.controller_type || C_AH002;
    const k     = controllerKey(ctrl);
    const tpls  = els.rowTemplates[k];
    const tbl   = els.tables[k];

    const basic = cloneRow(tpls.basic, rowId, mode, unit.tag, ctrl);
    const dat   = cloneRow(tpls.dat,   rowId, mode, unit.tag, ctrl);
    const rat   = cloneRow(tpls.rat,   rowId, mode, unit.tag, ctrl);

    const tagInput = basic.tr.querySelector('[data-field="tag"]');
    if (tagInput) tagInput.value = unit.tag || '';

    const capSelect = basic.tr.querySelector('[data-field="capacity"]');
    if (capSelect && unit.capacity_index != null) {
      capSelect.value = String(unit.capacity_index);
    }

    const modeSelect = basic.tr.querySelector('[data-field="control_mode"]');
    if (modeSelect) modeSelect.value = mode;

    tbl.basicTbody.appendChild(basic.frag);
    tbl.datTbody.appendChild(dat.frag);
    tbl.ratTbody.appendChild(rat.frag);

    return {
      rowId,
      controllerKey: k,
      basicTr: $(`tr[data-row-id="${rowId}"]`, tbl.basicTbody),
      datTr:   $(`tr[data-row-id="${rowId}"]`, tbl.datTbody),
      ratTr:   $(`tr[data-row-id="${rowId}"]`, tbl.ratTbody),
    };
  }

  function addBasicRow({ controller_type, cloneFromLast = false } = {}) {
    const ctrl = controller_type || C_AH002;
    const k    = controllerKey(ctrl);
    const tbl  = els.tables[k];

    let capacity     = 0;
    let controlMode  = 'discharge';
    let heatPump     = 'true';

    if (cloneFromLast) {
      const lastBasic = tbl.basicTbody.querySelector('tr:last-child');
      if (lastBasic) {
        const lastCap  = lastBasic.querySelector('[data-field="capacity"]');
        const lastMode = lastBasic.querySelector('[data-field="control_mode"]');
        const lastHP   = lastBasic.querySelector('[data-field="heat_pump"]');
        if (lastCap)  capacity    = Number(lastCap.value) || 0;
        if (lastMode) controlMode = lastMode.value;
        if (lastHP)   heatPump    = lastHP.value;
      }
    }

    const rows = appendUnitRows({
      tag: '',
      capacity_index:  capacity,
      control_mode:    controlMode,
      controller_type: ctrl,
    });

    const hpSelect = rows.basicTr.querySelector('[data-field="heat_pump"]');
    if (hpSelect) hpSelect.value = heatPump;

    applyEnableLock(rows.rowId);
    applyAh001Gating(rows.rowId);
    updateModeSectionVisibility();
    return rows;
  }

  // v3.2 UX rule: when DAT enable = central, setpoint locks to central too.
  function applyEnableLock(rowId) {
    const datRow = findRowAcrossTables(rowId, 'datTbody');
    if (!datRow) return;
    const enable = datRow.querySelector('[data-field="discharge_enable"]');
    const setpt  = datRow.querySelector('[data-field="discharge_setpoint"]');
    if (!enable || !setpt) return;
    if (enable.value === 'central') {
      setpt.value    = 'central';
      setpt.disabled = true;
    } else {
      setpt.disabled = false;
    }
  }

  // Gating logic for AH001 extras:
  //   - When fan_controlled_by = BAS, disable run_fan_defrost (DAT) and
  //     electric_heat / humidifier_installed and their dependents (RAT).
  //   - When electric_heat = No, disable use_defrost_error.
  //   - When humidifier_installed = No, disable run_humidifier.
  function applyAh001Gating(rowId) {
    const basicRow = findRowAcrossTables(rowId, 'basicTbody');
    if (!basicRow || basicRow.dataset.controllerType !== C_AH001) return;
    const fanSel = basicRow.querySelector('[data-field="fan_controlled_by"]');
    const fanIsLev = !fanSel || fanSel.value === 'lev';

    const datRow = findRowAcrossTables(rowId, 'datTbody');
    if (datRow) {
      const runFan = datRow.querySelector('[data-field="run_fan_defrost"]');
      if (runFan) {
        runFan.disabled = !fanIsLev;
        if (!fanIsLev) runFan.value = 'false';
      }
    }

    const ratRow = findRowAcrossTables(rowId, 'ratTbody');
    if (ratRow) {
      const elecSel = ratRow.querySelector('[data-field="electric_heat"]');
      const elecOn  = elecSel && elecSel.value === 'true';
      const humSel  = ratRow.querySelector('[data-field="humidifier_installed"]');
      const humOn   = humSel && humSel.value === 'true';

      if (elecSel) {
        elecSel.disabled = !fanIsLev;
        if (!fanIsLev) elecSel.value = 'false';
      }
      const useDefrost = ratRow.querySelector('[data-field="use_defrost_error"]');
      if (useDefrost) {
        useDefrost.disabled = !fanIsLev || !elecOn;
        if (useDefrost.disabled) useDefrost.value = 'false';
      }
      if (humSel) {
        humSel.disabled = !fanIsLev;
        if (!fanIsLev) humSel.value = 'false';
      }
      const runHum = ratRow.querySelector('[data-field="run_humidifier"]');
      if (runHum) {
        runHum.disabled = !fanIsLev || !humOn;
        if (runHum.disabled) runHum.value = 'false';
      }
    }
  }

  // Rows for a single unit always live in the same controller-group tables;
  // search both groups so callers don't have to know which one.
  function findRowAcrossTables(rowId, tbodyKey) {
    return (
      $(`tr[data-row-id="${rowId}"]`, els.tables.ah002[tbodyKey]) ||
      $(`tr[data-row-id="${rowId}"]`, els.tables.ah001[tbodyKey])
    );
  }

  function updateModeSectionVisibility() {
    for (const key of ['ah002', 'ah001']) {
      const tbl = els.tables[key];
      const hasDAT = tbl.datTbody.querySelector('tr[data-mode="discharge"]') != null;
      const hasRAT = tbl.ratTbody.querySelector('tr[data-mode="return"]')    != null;
      tbl.datSection.style.display = hasDAT ? '' : 'none';
      tbl.ratSection.style.display = hasRAT ? '' : 'none';
    }
  }

  // ---------------------------------------------------------------------------
  // State assembly for the update endpoint
  // ---------------------------------------------------------------------------

  function collectState() {
    // Iterate basic rows from both controller groups in document order so the
    // payload preserves the user-visible ordering (AH002 group first).
    const allBasicRows = [
      ...$$('tr[data-row-id]', els.tables.ah002.basicTbody),
      ...$$('tr[data-row-id]', els.tables.ah001.basicTbody),
    ];
    const units = allBasicRows.map(basicRow => {
      const rowId = basicRow.dataset.rowId;
      const ctrl  = basicRow.dataset.controllerType || C_AH002;
      const isDAT = basicRow.dataset.mode === 'discharge';
      const ovr   = { controller_type: ctrl };

      const datRow = findRowAcrossTables(rowId, 'datTbody');
      const ratRow = findRowAcrossTables(rowId, 'ratTbody');
      const rowsForUnit = [basicRow, datRow, ratRow].filter(Boolean);

      for (const row of rowsForUnit) {
        for (const el of $$('[data-field]', row)) {
          const k = el.dataset.field;
          if (DAT_ONLY.has(k) && !isDAT) continue;
          if (RAT_ONLY.has(k) &&  isDAT) continue;
          ovr[k] = readField(el);
        }
      }
      return ovr;
    });
    return {
      project_name:          els.editor.projectName.value,
      voltage:               els.editor.voltage.value,
      refrigerant_selection: currentRefrigerant(),
      units:                 units,
    };
  }

  // ---------------------------------------------------------------------------
  // Editor entry / reset
  // ---------------------------------------------------------------------------

  function clearEditorTables() {
    for (const key of ['ah002', 'ah001']) {
      els.tables[key].basicTbody.innerHTML = '';
      els.tables[key].datTbody.innerHTML   = '';
      els.tables[key].ratTbody.innerHTML   = '';
    }
  }

  function enterEditor(data) {
    clearEditorTables();
    els.editor.projectName.value = data.project_name || '';
    setRefrigerant(data.refrigerant_selection || 'ah002');

    for (const unit of data.units || []) {
      const rows = appendUnitRows(unit);
      applyEnableLock(rows.rowId);
      applyAh001Gating(rows.rowId);
    }
    updateModeSectionVisibility();
    _markEmptyTags();

    // Set voltage to 208V default; session restore below may override it.
    els.editor.voltage.value = '208';

    // Restore saved overrides from the server session (e.g. on page reload).
    const sid = currentSession && currentSession.session_id;
    if (sid) {
      _updateSaveIndicator();
      fetch('/api/session/' + encodeURIComponent(sid))
        .then(r => r.ok ? r.json() : null)
        .then(full => {
          if (full && full.overrides) applyOverrides(full.overrides);
          if (full && full.voltage) els.editor.voltage.value = full.voltage;
          if (full && full.project_name) els.editor.projectName.value = full.project_name;
          _saveStatus = 'saved';
          _updateSaveIndicator();
        })
        .catch(() => {
          _saveStatus = 'error';
          _updateSaveIndicator();
        });
    }

    renderWarnings(data.warnings);
    clearInlineError(els.editor.generateError);
    els.upload.step.style.display = 'none';
    els.editor.step.style.display = '';
  }

  // Re-render the drop zone's inner markup back to the initial state and
  // re-bind setupDropZone(). Needed because main.js's resetZone() overwrites
  // zone.innerHTML on success and discards the captured <input> reference's
  // DOM attachment, so a fresh setup is required for click-to-browse to work
  // again after reset.
  function resetUploadDropZone() {
    const zone = els.upload.dropZone;
    if (!zone) return;
    zone.classList.remove('uploading', 'dragging');
    zone.style.borderColor = '';
    zone.style.color = '';
    zone.innerHTML = `
      <div class="icon">&#128196;</div>
      <p>Drag &amp; drop your <strong>.dsbx</strong> file here, or click to browse</p>
      <small>DSB project export &mdash; maximum 5 MB</small>
      <input type="file" id="lk-file-input" accept=".dsbx" style="display:none">`;
    els.upload.file = $('#lk-file-input');
    setupDropZone('lk-drop-zone', 'lk-file-input',
                  '/api/upload/lev-kit', onUploadSuccess);
  }

  function handleReset() {
    currentSession = null;
    clearTimeout(_saveTimer);
    _saveTimer = null;
    _saveStatus = 'saved';
    clearInlineError(els.upload.error);
    clearInlineError(els.editor.generateError);
    clearEditorTables();
    els.editor.projectName.value = '';
    setRefrigerant('ah002');
    els.editor.step.style.display = 'none';
    els.upload.step.style.display = '';
    resetUploadDropZone();
    _updateSaveIndicator();
  }

  // ---------------------------------------------------------------------------
  // Event handlers -- start paths
  // ---------------------------------------------------------------------------

  function onUploadSuccess(data) {
    currentSession = {
      session_id:   data.session_id,
      project_name: data.project_name,
      units:        data.units,
    };
    enterEditor(data);
  }

  async function startManualEditor() {
    clearInlineError(els.upload.error);
    els.upload.manualEntry.disabled = true;
    try {
      const data = await apiBlankSession();
      currentSession = {
        session_id:   data.session_id,
        project_name: data.project_name || '',
        units:        [],
      };
      enterEditor(data);
      // Default manual entry adds one AH002 row; user can switch refrigerant
      // and use the AH001 group's Add New button to add R-410A units.
      addBasicRow({ controller_type: C_AH002, cloneFromLast: false });
    } catch (err) {
      showInlineError(els.upload.error, err.message);
    } finally {
      els.upload.manualEntry.disabled = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Event handlers -- editor
  // ---------------------------------------------------------------------------

  function handleUnitsChange(e) {
    const t = e.target;
    if (!t.matches('[data-field]')) return;
    const row = t.closest('tr[data-row-id]');
    if (!row) return;
    const rowId = row.dataset.rowId;

    if (t.dataset.field === 'control_mode') {
      const mode = t.value;
      // The unit's three rows always live in the same controller group, so
      // updating data-mode across them is enough — no cross-group lookup.
      for (const r of [
        findRowAcrossTables(rowId, 'basicTbody'),
        findRowAcrossTables(rowId, 'datTbody'),
        findRowAcrossTables(rowId, 'ratTbody'),
      ]) {
        if (r) r.dataset.mode = mode;
      }
      updateModeSectionVisibility();
    } else if (t.dataset.field === 'discharge_enable') {
      applyEnableLock(rowId);
    } else if (t.dataset.field === 'tag') {
      syncTagDisplay(rowId, t.value);
      // Toggle empty-tag warning
      t.classList.toggle('lk-tag-empty', !t.value.trim());
    } else if (
      t.dataset.field === 'fan_controlled_by' ||
      t.dataset.field === 'electric_heat' ||
      t.dataset.field === 'humidifier_installed'
    ) {
      applyAh001Gating(rowId);
    }

    // Debounced auto-save on every field change
    autoSave();
  }

  function syncTagDisplay(rowId, newTag) {
    for (const r of [
      findRowAcrossTables(rowId, 'datTbody'),
      findRowAcrossTables(rowId, 'ratTbody'),
    ]) {
      if (!r) continue;
      const display = r.querySelector('[data-display="tag"]');
      if (display) display.textContent = newTag;
    }
  }

  function handleAddNew(controller_type) {
    return () => addBasicRow({ controller_type, cloneFromLast: true });
  }

  function onRefrigerantChange() {
    applyRefrigerantVisibility();
  }

  async function generatePdf(layout) {
    if (!currentSession) return;
    clearInlineError(els.editor.generateError);
    const buttons = [els.editor.generateHorizontal, els.editor.generateVertical];
    for (const b of buttons) b.disabled = true;
    const payload = collectState();
    try {
      await apiUpdateSession(currentSession.session_id, payload);
    } catch (err) {
      showInlineError(els.editor.generateError, err.message);
      for (const b of buttons) b.disabled = false;
      return;
    }
    const layoutParam = encodeURIComponent(layout);
    window.location.href =
      `/api/download/lev-kit/${encodeURIComponent(currentSession.session_id)}?layout=${layoutParam}`;
    setTimeout(() => { for (const b of buttons) b.disabled = false; }, 1500);
  }

  // ---------------------------------------------------------------------------
  // Bootstrap
  // ---------------------------------------------------------------------------

  function init() {
    setupDropZone('lk-drop-zone', 'lk-file-input',
                  '/api/upload/lev-kit', onUploadSuccess);
    els.upload.manualEntry.addEventListener('click', startManualEditor);
    els.editor.reset.addEventListener('click', handleReset);
    els.editor.step.addEventListener('change', handleUnitsChange);
    els.tables.ah002.addNew.addEventListener('click', handleAddNew(C_AH002));
    els.tables.ah001.addNew.addEventListener('click', handleAddNew(C_AH001));
    for (const r of els.refrigerantRadios) {
      r.addEventListener('change', onRefrigerantChange);
    }
    els.editor.generateHorizontal.addEventListener('click', () => generatePdf('horizontal'));
    els.editor.generateVertical.addEventListener('click',   () => generatePdf('vertical'));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
