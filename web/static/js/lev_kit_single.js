'use strict';

(function () {

  const C_AH001 = 'PAC-AH001';
  const C_AH002 = 'PAC-AH002';

  // ─── CONFIG DATA (fetched from /api/lev-kit/config-data on load) ───────────
  let _configData = null;

  // ─── STATE ─────────────────────────────────────────────────────────────────
  const state = {
    controllerType:        C_AH002,
    capacity:              0,
    capacityLabel:         '',
    inputVoltage:          '208',
    heatPump:              true,
    controlMode:           'discharge',
    dischargeEnableType:   'bas',
    dischargeSetpointType: 'bas',
    thermoTemp:            2,
    datSetpoint:           2,
    returnControl:         'rat',
    returnEnableMethod:    'central',
    tempAdjustment:        false,
    // AH001-only extras
    fanControlledBy:       'bas',
    runFanDefrost:         false,
    electricHeat:          false,
    useDefrostError:       false,
    humidifierInstalled:   false,
    runHumidifier:         false,
  };

  // ─── SECTION NAV ───────────────────────────────────────────────────────────
  // Step 0 no longer exists — each controller has its own dedicated page.
  const ALL_SECTIONS = [
    'lks-step-1', 'lks-step-2',
    'lks-step-3-dat', 'lks-step-3-rat',
    'lks-step-4-dat', 'lks-step-4-rat',
    'lks-results',
  ];

  function showSection(id) {
    ALL_SECTIONS.forEach(sid => document.getElementById(sid).classList.add('lks-hidden'));
    document.getElementById(id).classList.remove('lks-hidden');
  }

  // ─── CHOICE BUTTONS ────────────────────────────────────────────────────────
  function setChoice(groupId, rawValue) {
    document.getElementById(groupId).querySelectorAll('.lks-choice').forEach(btn => {
      const pressed = btn.dataset.value === String(rawValue);
      btn.classList.toggle('lks-active', pressed);
      btn.setAttribute('aria-pressed', pressed ? 'true' : 'false');
    });
  }

  const BOOL_FIELDS = new Set([
    'heatPump', 'tempAdjustment',
    'runFanDefrost', 'electricHeat', 'useDefrostError',
    'humidifierInstalled', 'runHumidifier',
  ]);
  const INT_FIELDS = new Set(['thermoTemp', 'datSetpoint', 'capacity']);

  function parseValue(field, raw) {
    if (BOOL_FIELDS.has(field)) return raw === 'true';
    if (INT_FIELDS.has(field))  return parseInt(raw, 10);
    return raw;
  }

  function bindChoiceGroup(groupId, field, afterChange) {
    const groupEl = document.getElementById(groupId);
    if (groupEl) {
      groupEl.querySelectorAll('.lks-choice').forEach(btn => btn.setAttribute('role', 'radio'));
    }
    groupEl.addEventListener('click', e => {
      const btn = e.target.closest('.lks-choice');
      if (!btn || btn.disabled) return;
      state[field] = parseValue(field, btn.dataset.value);
      setChoice(groupId, btn.dataset.value);
      if (afterChange) afterChange();
    });
  }

  // ─── AH001 VISIBILITY / GATING ─────────────────────────────────────────────
  function applyControllerVisibility() {
    const isAh001 = state.controllerType === C_AH001;
    document.querySelectorAll('.lks-ah001-only').forEach(el => {
      el.classList.toggle('lks-hidden', !isAh001);
    });
    const lbl = document.getElementById('lks-voltage-230-label');
    if (lbl) lbl.textContent = '230V';
  }

  function applyFanGating() {
    const isAh001 = state.controllerType === C_AH001;
    if (!isAh001) return;
    const fanIsLev = state.fanControlledBy === 'lev';
    document.querySelectorAll('.lks-ah001-only[data-fan-gated="true"]').forEach(el => {
      el.classList.toggle('lks-hidden', !fanIsLev);
    });
    if (!fanIsLev) {
      state.runFanDefrost      = false;
      state.electricHeat       = false;
      state.useDefrostError    = false;
      state.humidifierInstalled = false;
      state.runHumidifier      = false;
      setChoice('lks-run-fan-defrost-group', 'false');
      setChoice('lks-electric-heat-group', 'false');
      setChoice('lks-use-defrost-error-group', 'false');
      setChoice('lks-humidifier-installed-group', 'false');
      setChoice('lks-run-humidifier-group', 'false');
    }
    applyDependentSubgroupVisibility();
  }

  function applyDependentSubgroupVisibility() {
    document.getElementById('lks-use-defrost-error-wrap')
            .classList.toggle('lks-hidden', !state.electricHeat);
    document.getElementById('lks-run-humidifier-wrap')
            .classList.toggle('lks-hidden', !state.humidifierInstalled);
  }

  // ─── DIP BANK RENDERER (two-row banks: SW1/SW2/SW3/SW4) ────────────────────
  function renderDipBank(label, positions, values) {
    const wrapper = document.createElement('div');
    wrapper.className = 'lks-bank-wrapper';

    const lbl = document.createElement('div');
    lbl.className = 'lks-bank-label';
    lbl.textContent = label;
    wrapper.appendChild(lbl);

    const row = document.createElement('div');
    row.className = 'lks-bank-row';

    const onoff = document.createElement('div');
    onoff.className = 'lks-bank-onoff';
    onoff.innerHTML = '<span>ON</span><span>OFF</span>';
    row.appendChild(onoff);

    for (let i = 0; i < positions; i++) {
      const col = document.createElement('div');
      col.className = 'lks-switch-col';

      const frame = document.createElement('div');
      frame.className = 'lks-switch-frame' + (i > 0 ? ' lks-not-first' : '');

      const onCell = document.createElement('div');
      onCell.className = values[i] === 1 ? 'lks-cell-on' : 'lks-cell-off';

      const offCell = document.createElement('div');
      offCell.className = values[i] === 0 ? 'lks-cell-on' : 'lks-cell-off';

      frame.appendChild(onCell);
      frame.appendChild(offCell);
      col.appendChild(frame);

      const posNum = document.createElement('div');
      posNum.className = 'lks-pos-num';
      posNum.textContent = i + 1;
      col.appendChild(posNum);

      row.appendChild(col);
    }

    wrapper.appendChild(row);
    return wrapper;
  }

  // ─── SINGLE-ROW BANK RENDERER (SWA, SW5) ──────────────────────────────────
  function renderSingleRowBank(label, cellLabels, values) {
    const maxChars = Math.max(...cellLabels.map(s => s.length));
    const cellInnerW = Math.max(12, maxChars * 5.5 + 2);
    const firstFrameW = cellInnerW + 4 + 4;
    const otherFrameW = cellInnerW + 4 + 2;

    const wrapper = document.createElement('div');
    wrapper.className = 'lks-bank-wrapper';

    const lbl = document.createElement('div');
    lbl.className = 'lks-bank-label';
    lbl.textContent = label;
    wrapper.appendChild(lbl);

    const row = document.createElement('div');
    row.className = 'lks-bank-row lks-bank-single-row';

    const onoff = document.createElement('div');
    onoff.className = 'lks-bank-onoff';
    onoff.innerHTML = '<span>&nbsp;</span><span>&nbsp;</span>';
    row.appendChild(onoff);

    for (let i = 0; i < cellLabels.length; i++) {
      const colW = (i === 0 ? firstFrameW : otherFrameW);

      const col = document.createElement('div');
      col.className = 'lks-switch-col';
      col.style.width = colW + 'px';
      col.style.flex  = `0 0 ${colW}px`;

      const frame = document.createElement('div');
      frame.className = 'lks-switch-frame' + (i > 0 ? ' lks-not-first' : '');

      const cell = document.createElement('div');
      cell.className = 'lks-cell-single ' + (values[i] === 1 ? 'lks-cell-on' : 'lks-cell-off');
      cell.style.width = cellInnerW + 'px';

      frame.appendChild(cell);
      col.appendChild(frame);

      const posLabel = document.createElement('div');
      posLabel.className = 'lks-pos-label';
      posLabel.textContent = cellLabels[i];
      posLabel.style.width = colW + 'px';

      col.appendChild(posLabel);

      row.appendChild(col);
    }

    wrapper.appendChild(row);
    return wrapper;
  }

  // ─── RESULTS ───────────────────────────────────────────────────────────────
  const BANK_ORDER_AH002 = [
    ['SW1', 10], ['SW2', 6], ['SW3', 10], ['SW4', 6], ['SW21', 8], ['SW22', 4],
  ];

  const AH001_SWA_LABELS = ['3', '2', '1'];
  const AH001_SW5_LABELS = ['230V', '208V'];

  function renderResultsInto(container, sw) {
    container.innerHTML = '';
    if (state.controllerType === C_AH001) {
      for (const [name, positions] of [['SW1', 10], ['SW2', 6], ['SW3', 10], ['SW4', 10]]) {
        container.appendChild(renderDipBank(name, positions, sw[name]));
      }
      // labels are visual-ordered left-to-right [3, 2, 1]. Reverse values so
      // pos1 (SWA[0]) maps to the rightmost cell, matching the physical switch.
      container.appendChild(renderSingleRowBank('SWA', AH001_SWA_LABELS, [...sw.SWA].reverse()));
      const sw5_bit = sw.SW5[0];
      container.appendChild(renderSingleRowBank('SW5', AH001_SW5_LABELS,
                                                [sw5_bit === 1 ? 1 : 0,
                                                 sw5_bit === 1 ? 0 : 1]));
    } else {
      BANK_ORDER_AH002.forEach(([name, positions]) => {
        container.appendChild(renderDipBank(name, positions, sw[name]));
      });
    }
  }

  // ─── SUMMARY TABLE ─────────────────────────────────────────────────────────
  function getActiveButtonText(groupId) {
    const btn = document.querySelector('#' + groupId + ' .lks-choice.lks-active');
    return btn ? btn.textContent.trim() : '—';
  }

  function buildSummaryRows() {
    const rows = [];

    rows.push({ label: 'LEV Kit Size',    value: state.capacityLabel || '—' });
    rows.push({ label: 'Input Voltage',   value: state.inputVoltage + 'V' });
    rows.push({ label: 'System Type',     value: state.heatPump ? 'Heat Pump' : 'Cooling Only' });
    rows.push({ label: 'Control Mode',    value: state.controlMode === 'discharge'
                                            ? 'Discharge Air Temp (DAT)' : 'Return Air Temp (RAT)' });

    if (state.controllerType === C_AH001) {
      rows.push({ label: 'Fan Controlled By', value: state.fanControlledBy === 'lev' ? 'LEV Kit' : 'BAS' });
    }

    if (state.controlMode === 'discharge') {
      rows.push({ label: 'Enable Method',   value: state.dischargeEnableType === 'bas'
                                               ? 'BAS (Dry Contact)' : 'Mitsubishi Controls' });
      rows.push({ label: 'Setpoint Source', value: state.dischargeSetpointType === 'bas'
                                               ? 'BAS (0-10V Signal)' : 'Mitsubishi Controls' });
      if (state.controllerType === C_AH001 && state.fanControlledBy === 'lev') {
        rows.push({ label: 'Run Fan During Defrost', value: state.runFanDefrost ? 'Yes' : 'No' });
      }
      rows.push({ label: 'Thermo-Off Temp',        value: getActiveButtonText('lks-thermo-group') });
      rows.push({ label: 'Heating Setpoint Limit', value: getActiveButtonText('lks-setpoint-group') });
    } else {
      rows.push({ label: 'Temperature Sensor', value: state.returnControl === 'rat'
                                                ? 'Return Air Sensor' : 'Room Temp Sensor' });
      rows.push({ label: 'Enable Method',      value: state.returnEnableMethod === 'bas'
                                                ? 'BAS (Dry Contact)' : 'Mitsubishi Controls' });
      if (state.controllerType === C_AH001 && state.fanControlledBy === 'lev') {
        rows.push({ label: 'Electric Heat Installed', value: state.electricHeat ? 'Yes' : 'No' });
        if (state.electricHeat) {
          rows.push({ label: 'Use During Defrost & Error', value: state.useDefrostError ? 'Yes' : 'No' });
        }
        rows.push({ label: 'Humidifier Installed', value: state.humidifierInstalled ? 'Yes' : 'No' });
        if (state.humidifierInstalled) {
          rows.push({ label: 'Run in Heating Thermo-OFF', value: state.runHumidifier ? 'Yes' : 'No' });
        }
      }
      rows.push({ label: 'Stratification Offset', value: state.tempAdjustment
                                                  ? '7°F below return' : 'None' });
    }

    return rows;
  }

  function renderSummaryTable(container, ctrlLabel, rows) {
    container.innerHTML = '';
    const tbl = document.createElement('table');
    tbl.className = 'lks-summary-tbl';

    // Controller header row
    const hdrRow = document.createElement('tr');
    hdrRow.className = 'lks-sumrow-hdr';
    const hdrTd = document.createElement('td');
    hdrTd.colSpan = 2;
    hdrTd.textContent = ctrlLabel;
    hdrRow.appendChild(hdrTd);
    tbl.appendChild(hdrRow);

    rows.forEach(r => {
      const tr = document.createElement('tr');
      const tdL = document.createElement('td');
      tdL.className = 'lks-sum-label';
      tdL.textContent = r.label;
      const tdV = document.createElement('td');
      tdV.className = 'lks-sum-value';
      tdV.textContent = r.value;
      tr.appendChild(tdL);
      tr.appendChild(tdV);
      tbl.appendChild(tr);
    });

    container.appendChild(tbl);
  }

  async function showResults() {
    const payload = { ...state };
    if (state.controllerType === C_AH002) {
      delete payload.fanControlledBy;
      delete payload.runFanDefrost;
      delete payload.electricHeat;
      delete payload.useDefrostError;
      delete payload.humidifierInstalled;
      delete payload.runHumidifier;
    }
    const resp = await fetch('/api/lev-kit/compute-switches', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const { switches, cnrmConnected } = await resp.json();

    renderResultsInto(document.getElementById('lks-banks-container'), switches);
    renderResultsInto(document.getElementById('lks-capture-banks'),   switches);

    const cnrmText = 'CNRM Jumper: ' + (cnrmConnected ? 'Connected' : 'Disconnected');
    document.getElementById('lks-cnrm-text').textContent    = cnrmText;
    document.getElementById('lks-capture-cnrm').textContent = cnrmText;

    const ctrlLabel = state.controllerType === C_AH001 ? 'PAC-AH001 (R-410A)' : 'PAC-AH002 (R-32)';
    const rows = buildSummaryRows();
    renderSummaryTable(document.getElementById('lks-summary-display'),  ctrlLabel, rows);
    renderSummaryTable(document.getElementById('lks-capture-summary'),  ctrlLabel, rows);
  }

  // ─── DOWNLOAD / COPY ───────────────────────────────────────────────────────
  function downloadFilename() {
    const ctrl = state.controllerType === C_AH001 ? 'PAC-AH001' : 'PAC-AH002';
    return `${ctrl}_Config_` + new Date().toISOString().split('T')[0] + '.png';
  }

  async function download() {
    const canvas = await html2canvas(document.getElementById('lks-capture-target'), {
      backgroundColor: '#ffffff', scale: 2, logging: false,
    });
    canvas.toBlob(blob => {
      const a = document.createElement('a');
      a.download = downloadFilename();
      a.href = URL.createObjectURL(blob);
      a.click();
      URL.revokeObjectURL(a.href);
    });
  }

  async function copyToClipboard() {
    const canvas = await html2canvas(document.getElementById('lks-capture-target'), {
      backgroundColor: '#ffffff', scale: 2, logging: false,
    });
    canvas.toBlob(async blob => {
      try {
        await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })]);
      } catch (_) {
        // Clipboard API unavailable in this context
      }
    });
  }

  // ─── SETPOINT LOCK ─────────────────────────────────────────────────────────
  function applySetpointLock() {
    const locked = state.dischargeEnableType === 'central';
    const setpointGroup = document.getElementById('lks-discharge-setpoint-group');
    const lockNote = document.getElementById('lks-setpoint-lock-note');
    if (locked) {
      state.dischargeSetpointType = 'central';
      setChoice('lks-discharge-setpoint-group', 'central');
      setpointGroup.querySelectorAll('.lks-choice').forEach(btn => {
        btn.disabled = btn.dataset.value !== 'central';
      });
      lockNote.classList.remove('lks-hidden');
    } else {
      setpointGroup.querySelectorAll('.lks-choice').forEach(btn => { btn.disabled = false; });
      lockNote.classList.add('lks-hidden');
    }
  }

  // ─── CONTROLLER-AWARE POPULATION ───────────────────────────────────────────
  function populateControllerDependentOptions() {
    const ctrl = state.controllerType;
    const subtree = (_configData.controllers && _configData.controllers[ctrl]) || {};

    const capacityOptions = subtree.capacityOptions || _configData.capacityOptions;
    const capSelect = document.getElementById('lks-capacity');
    capSelect.innerHTML = '';
    capacityOptions.forEach(opt => {
      const el = document.createElement('option');
      el.value = opt.value;
      el.textContent = opt.label;
      capSelect.appendChild(el);
    });

    const thermoGroup = document.getElementById('lks-thermo-group');
    thermoGroup.innerHTML = '';
    const thermoOptions = subtree.thermoOptions || _configData.thermoOptions;
    thermoOptions.forEach((opt, idx) => {
      if (idx === 0) state.thermoTemp = opt.value;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'lks-choice' + (opt.value === state.thermoTemp ? ' lks-active' : '');
      btn.dataset.field = 'thermoTemp';
      btn.dataset.value = opt.value;
      btn.textContent = opt.label;
      thermoGroup.appendChild(btn);
    });

    const setpointGroup = document.getElementById('lks-setpoint-group');
    setpointGroup.innerHTML = '';
    const setpointOptions = subtree.heatingSetpointOptions || _configData.heatingSetpointOptions;
    setpointOptions.forEach((opt, idx) => {
      if (idx === 0) state.datSetpoint = opt.value;
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'lks-choice' + (opt.value === state.datSetpoint ? ' lks-active' : '');
      btn.dataset.field = 'datSetpoint';
      btn.dataset.value = opt.value;
      btn.textContent = opt.label;
      setpointGroup.appendChild(btn);
    });

    state.capacity = 0;
    state.capacityLabel = '';
    capSelect.value = '0';
    document.getElementById('lks-next-1').disabled = true;
  }

  // ─── INIT ──────────────────────────────────────────────────────────────────
  function init() {
    const isMobile = () => /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);

    // Step 1
    const capSelect = document.getElementById('lks-capacity');
    capSelect.addEventListener('change', () => {
      state.capacity = parseInt(capSelect.value, 10);
      state.capacityLabel = capSelect.options[capSelect.selectedIndex].text;
      document.getElementById('lks-next-1').disabled = state.capacity === 0;
    });
    document.querySelectorAll('input[name="lks-voltage"]').forEach(radio => {
      radio.addEventListener('change', () => { state.inputVoltage = radio.value; });
    });
    // Back from step 1 returns to the controller landing page (no step-0 on these pages).
    document.getElementById('lks-back-1').addEventListener('click', () => {
      window.location.href = '/lev-kit-single';
    });
    document.getElementById('lks-next-1').addEventListener('click', () => showSection('lks-step-2'));

    // Step 2
    bindChoiceGroup('lks-heat-pump-group', 'heatPump');
    bindChoiceGroup('lks-mode-group', 'controlMode');
    bindChoiceGroup('lks-fan-group', 'fanControlledBy', applyFanGating);
    document.getElementById('lks-back-2').addEventListener('click', () => showSection('lks-step-1'));
    document.getElementById('lks-next-2').addEventListener('click', () => {
      showSection(state.controlMode === 'discharge' ? 'lks-step-3-dat' : 'lks-step-3-rat');
    });

    // Step 3-DAT
    bindChoiceGroup('lks-discharge-enable-group', 'dischargeEnableType', applySetpointLock);
    bindChoiceGroup('lks-discharge-setpoint-group', 'dischargeSetpointType');
    bindChoiceGroup('lks-run-fan-defrost-group', 'runFanDefrost');
    document.getElementById('lks-back-3dat').addEventListener('click', () => showSection('lks-step-2'));
    document.getElementById('lks-next-3dat').addEventListener('click', () => showSection('lks-step-4-dat'));

    // Step 3-RAT
    bindChoiceGroup('lks-return-control-group', 'returnControl');
    bindChoiceGroup('lks-return-enable-group', 'returnEnableMethod');
    bindChoiceGroup('lks-electric-heat-group', 'electricHeat', applyDependentSubgroupVisibility);
    bindChoiceGroup('lks-use-defrost-error-group', 'useDefrostError');
    bindChoiceGroup('lks-humidifier-installed-group', 'humidifierInstalled', applyDependentSubgroupVisibility);
    bindChoiceGroup('lks-run-humidifier-group', 'runHumidifier');
    document.getElementById('lks-back-3rat').addEventListener('click', () => showSection('lks-step-2'));
    document.getElementById('lks-next-3rat').addEventListener('click', () => showSection('lks-step-4-rat'));

    // Step 4-DAT
    bindChoiceGroup('lks-thermo-group', 'thermoTemp');
    bindChoiceGroup('lks-setpoint-group', 'datSetpoint');
    document.getElementById('lks-back-4dat').addEventListener('click', () => showSection('lks-step-3-dat'));
    document.getElementById('lks-next-4dat').addEventListener('click', async () => {
      await showResults();
      showSection('lks-results');
    });

    // Step 4-RAT
    bindChoiceGroup('lks-temp-adjust-group', 'tempAdjustment');
    document.getElementById('lks-back-4rat').addEventListener('click', () => showSection('lks-step-3-rat'));
    document.getElementById('lks-next-4rat').addEventListener('click', async () => {
      await showResults();
      showSection('lks-results');
    });

    // Results
    document.getElementById('lks-back-results').addEventListener('click', () => {
      showSection(state.controlMode === 'discharge' ? 'lks-step-4-dat' : 'lks-step-4-rat');
    });
    document.getElementById('lks-download').addEventListener('click', download);

    const copyBtn = document.getElementById('lks-copy');
    if (isMobile()) {
      copyBtn.classList.add('lks-hidden');
    } else {
      copyBtn.classList.remove('lks-hidden');
      copyBtn.addEventListener('click', copyToClipboard);
    }

    // Controller type is baked into the page via window.LKS_CONTROLLER.
    // Set state, populate options, and show step 1 immediately.
    state.controllerType = window.LKS_CONTROLLER || C_AH002;
    populateControllerDependentOptions();
    applyControllerVisibility();
    applyFanGating();
    showSection('lks-step-1');
  }

  document.addEventListener('DOMContentLoaded', async () => {
    const resp = await fetch('/api/lev-kit/config-data');
    _configData = await resp.json();
    init();
  });

})();
