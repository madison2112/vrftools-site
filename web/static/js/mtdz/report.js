
function csrfToken() {
  return document.querySelector('meta[name="csrf-token"]').content;
}

const sessionId = localStorage.getItem('session_id');
const days      = JSON.parse(localStorage.getItem('days') || '[]');

const _rp = window.MTDZ_PAGES || {};
const _PAGE_INDEX  = _rp.index  || 'index.html';
const _PAGE_VIEWER = _rp.viewer || 'viewer.html';

if (!sessionId) { window.location.href = _PAGE_INDEX; }

const errorEl       = document.getElementById('error-msg');
const daySelectCard = document.getElementById('day-select-card');
const dayCheckboxes = document.getElementById('day-checkboxes');
const btnCheckAll   = document.getElementById('btn-check-all');
const btnUncheckAll = document.getElementById('btn-uncheck-all');
const form          = document.getElementById('job-form');
const btnGenerate     = document.getElementById('btn-generate');
const btnExport       = document.getElementById('btn-export-graphs');
const actionStatusRow = document.getElementById('action-status-row');
const actionStatusTxt = document.getElementById('action-status-text');

function showProgress(msg) {
  actionStatusRow.style.display = 'flex';
  actionStatusTxt.textContent = msg;
  errorEl.classList.remove('visible');
}
function hideProgress() {
  actionStatusRow.style.display = 'none';
  actionStatusTxt.textContent = '';
}
const linkViewer    = document.getElementById('link-viewer');
const dsbFileInput  = document.getElementById('dsbFileInput');
const dsbStatusEl   = document.getElementById('dsbStatus');
const systemModal   = document.getElementById('systemPickerModal');

linkViewer.href = _PAGE_VIEWER;

// Pre-fill date
document.getElementById('report-date').value = new Date().toISOString().slice(0, 10);

// ── Day checkboxes (MTLZ only) ────────────────────────────────────────────────
if (days.length > 1) {
  daySelectCard.style.display = '';
  days.forEach(day => {
    const label = document.createElement('label');
    label.className = 'day-check-label';
    const cb = document.createElement('input');
    cb.type = 'checkbox';
    cb.value = day;
    cb.checked = true;
    label.appendChild(cb);
    label.appendChild(document.createTextNode(day));
    dayCheckboxes.appendChild(label);
  });
}

btnCheckAll.addEventListener('click', () => {
  dayCheckboxes.querySelectorAll('input').forEach(cb => cb.checked = true);
});
btnUncheckAll.addEventListener('click', () => {
  dayCheckboxes.querySelectorAll('input').forEach(cb => cb.checked = false);
});

// ── Helpers ───────────────────────────────────────────────────────────────────

function getSelectedDays() {
  return days.length > 1
    ? [...dayCheckboxes.querySelectorAll('input:checked')].map(cb => cb.value)
    : days;
}

function showDsbStatus(msg, type /* 'success'|'warning'|'error'|'' */) {
  dsbStatusEl.textContent = msg;
  dsbStatusEl.className = 'dsb-status-text' + (type ? ' ' + type : '');
}

// ── Equipment Table ───────────────────────────────────────────────────────────

function buildEquipmentTable(topology) {
  const container = document.getElementById('equipmentTableContainer');
  if (!topology || !topology.systems || topology.systems.length === 0) {
    container.innerHTML = '';
    return;
  }

  const systems = topology.systems;

  const table = document.createElement('table');
  table.className = 'equipment-table';

  const thead = document.createElement('thead');
  thead.innerHTML = `<tr>
    <th>Type</th>
    <th>Address</th>
    <th>Tag</th>
    <th>Model</th>
    <th>Serial</th>
  </tr>`;
  table.appendChild(thead);

  const tbody = document.createElement('tbody');

  function addSysNameRow(idx) {
    const tr = document.createElement('tr');
    tr.className = 'system-name-row';
    tr.innerHTML = `
      <td colspan="2" class="sys-name-label">System</td>
      <td colspan="3"><input type="text" class="system-name-input" data-system-idx="${idx}" placeholder="System ${idx + 1}"></td>
    `;
    tbody.appendChild(tr);
  }

  function addRow(type, addr, tagPlaceholder, model, serial) {
    const mnet = String(addr);
    const tr = document.createElement('tr');
    tr.innerHTML = `
      <td>${type}</td>
      <td>${addr}</td>
      <td><input type="text" data-mnet="${mnet}" data-field="tag" placeholder="${escHtml(tagPlaceholder)}"></td>
      <td><input type="text" data-mnet="${mnet}" data-field="model" placeholder="${escHtml(model)}"></td>
      <td><input type="text" data-mnet="${mnet}" data-field="serial" placeholder="${escHtml(serial) || 'Serial'}"></td>
    `;
    tbody.appendChild(tr);
  }

  systems.forEach((system, sysIdx) => {
    addSysNameRow(sysIdx);

    // Infrastructure units first
    const oc = system.oc || {};
    if (oc.address != null) {
      addRow('OC', oc.address, `OC-${oc.address}`, oc.model || '', oc.serial || '');
    }
    const os = system.os;
    if (os && os.address != null) {
      addRow('OS', os.address, `OS-${os.address}`, os.model || '', os.serial || '');
    }
    const bc = system.bc;
    if (bc && bc.address != null) {
      addRow('BC', bc.address, `BC-${bc.address}`, bc.model || '', bc.serial || '');
    }
    for (const bs of (system.bss || [])) {
      if (bs.address != null) {
        addRow('BS', bs.address, `BS-${bs.address}`, bs.model || '', bs.serial || '');
      }
    }

    // ICs — all ICs including those on Sub BCs, sorted by address
    const allIcs = [...(system.ics || [])];
    for (const bs of (system.bss || [])) {
      allIcs.push(...(bs.ics || []));
    }
    allIcs.sort((a, b) => (a.address ?? a.mnet ?? 0) - (b.address ?? b.mnet ?? 0));

    allIcs.forEach(ic => {
      const addr = ic.address != null ? ic.address : ic.mnet;
      const icTag = `IC-${String(addr).padStart(2, '0')}`;
      addRow('IC', addr, icTag, ic.model || '', ic.serial || '');
    });
  });

  table.appendChild(tbody);
  container.innerHTML = '';
  container.appendChild(table);

  // Persist all edits to localStorage
  container.addEventListener('input', saveEquipmentToStorage);
}

function saveEquipmentToStorage() {
  if (!sessionId) return;
  const container = document.getElementById('equipmentTableContainer');
  const units = {};
  container.querySelectorAll('input[data-mnet]').forEach(input => {
    const mnet = input.dataset.mnet;
    const field = input.dataset.field;
    if (!units[mnet]) units[mnet] = {};
    units[mnet][field] = input.value;
  });
  const sysNames = [];
  container.querySelectorAll('.system-name-input').forEach(input => {
    sysNames[parseInt(input.dataset.systemIdx)] = input.value;
  });
  try {
    localStorage.setItem(`equip_${sessionId}`, JSON.stringify({ units, sysNames }));
  } catch (_) {}
}

function restoreEquipmentFromStorage() {
  if (!sessionId) return;
  try {
    const raw = localStorage.getItem(`equip_${sessionId}`);
    if (!raw) return;
    const saved = JSON.parse(raw);
    const container = document.getElementById('equipmentTableContainer');
    if (saved.units) {
      Object.entries(saved.units).forEach(([mnet, fields]) => {
        Object.entries(fields).forEach(([field, val]) => {
          if (!val) return;
          const input = container.querySelector(`input[data-mnet="${mnet}"][data-field="${field}"]`);
          if (input) input.value = val;
        });
      });
    }
    if (saved.sysNames) {
      saved.sysNames.forEach((name, idx) => {
        if (!name) return;
        const input = container.querySelector(`.system-name-input[data-system-idx="${idx}"]`);
        if (input) input.value = name;
      });
    }
  } catch (_) {}
}

function collectEquipmentData() {
  const result = {};
  const container = document.getElementById('equipmentTableContainer');
  const inputs = container.querySelectorAll('input[data-mnet]');

  const byMnet = {};
  inputs.forEach(input => {
    const mnet = input.dataset.mnet;
    const field = input.dataset.field;
    if (!byMnet[mnet]) byMnet[mnet] = { tag: '', model: '', serial: '' };
    // Use typed value; fall back to placeholder for tag/model (auto-generated defaults)
    const val = input.value.trim();
    if (val) {
      byMnet[mnet][field] = val;
    } else if (field === 'tag' || field === 'model') {
      byMnet[mnet][field] = input.placeholder || '';
    }
  });

  Object.entries(byMnet).forEach(([mnet, data]) => {
    if (data.tag || data.model || data.serial) {
      result[mnet] = data;
    }
  });

  // Attach system names so backend can use them for section headers / folder names
  const sysNames = [];
  container.querySelectorAll('.system-name-input').forEach(input => {
    const idx = parseInt(input.dataset.systemIdx);
    sysNames[idx] = input.value.trim() || input.placeholder;
  });
  result.__system_names = sysNames;

  return result;
}

// ── DSB Upload ────────────────────────────────────────────────────────────────

// Holds DSB data for re-use in picker modal
let _lastDsbData = null;

dsbFileInput.addEventListener('change', async () => {
  const file = dsbFileInput.files[0];
  if (!file) return;
  await handleDsbUpload(file);
  // Reset so the same file can be re-uploaded if needed
  dsbFileInput.value = '';
});

async function handleDsbUpload(file) {
  showDsbStatus('Processing…', '');

  try {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('session_id', sessionId);

    const resp = await fetch(`${API}/api/dsb`, { method: 'POST', headers: Object.assign({ 'X-CSRFToken': csrfToken() }, proxyKeyHeader()), body: formData });

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || resp.statusText);
    }

    const data = await resp.json();
    const { match_result, dsb_data } = data;
    _lastDsbData = dsb_data;

    if (match_result.status === 'exact' || match_result.status === 'partial') {
      fillEquipmentFromDsb(dsb_data, match_result.matches[0].group_index);
      const pct = Math.round(match_result.matches[0].score * 100);
      const msg = match_result.status === 'exact'
        ? 'DSB matched successfully'
        : `Partial match (${pct}% overlap)`;
      showDsbStatus(msg, match_result.status === 'exact' ? 'success' : 'warning');
    } else {
      showDsbStatus('', '');
      showSystemPickerModal(dsb_data, match_result);
    }
  } catch (e) {
    showDsbStatus(`DSB upload failed: ${e.message}`, 'error');
  }
}

function fillEquipmentFromDsb(dsb_data, group_index) {
  const group = dsb_data.groups[group_index];
  if (!group) return;

  const container = document.getElementById('equipmentTableContainer');

  group.systems.forEach(dsbSys => {
    const fillUnit = (unit) => {
      if (!unit) return;
      const mnet = String(unit.mnet);
      const tagInput    = container.querySelector(`input[data-mnet="${mnet}"][data-field="tag"]`);
      const modelInput  = container.querySelector(`input[data-mnet="${mnet}"][data-field="model"]`);
      const serialInput = container.querySelector(`input[data-mnet="${mnet}"][data-field="serial"]`);

      if (tagInput   && unit.tag)   tagInput.value   = unit.tag;
      if (modelInput && unit.model) modelInput.value = unit.model;
      if (serialInput && unit.serial) serialInput.value = unit.serial;
    };

    fillUnit(dsbSys.oc);
    fillUnit(dsbSys.os);
    fillUnit(dsbSys.bc);
    (dsbSys.ics || []).forEach(ic => fillUnit(ic));

    // Update system name input for whichever MTDZ system shares the same OC address
    const ocAddr = dsbSys.oc?.mnet;
    if (ocAddr != null && dsbSys.name) {
      const topology = JSON.parse(localStorage.getItem('topology') || '{}');
      (topology.systems || []).forEach((sys, idx) => {
        if ((sys.oc?.address) === ocAddr) {
          const nameInput = container.querySelector(`.system-name-input[data-system-idx="${idx}"]`);
          if (nameInput) nameInput.value = dsbSys.name;
        }
      });
    }
  });

  saveEquipmentToStorage();
}

// ── System Picker Modal ───────────────────────────────────────────────────────

function openSystemPickerModal() {
  systemModal.style.display = 'flex';
  trapFocus(systemModal);
}

function closeSystemPickerModal(msg) {
  // Remove focus trap handler so it doesn't accumulate
  if (systemModal._trapHandler) {
    systemModal.removeEventListener('keydown', systemModal._trapHandler);
    delete systemModal._trapHandler;
  }
  systemModal.style.display = 'none';
  releaseFocus();
  if (msg !== undefined) showDsbStatus(msg, '');
}

// Escape key to close system picker (trapped by the modal's keydown handler)
systemModal.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') {
    closeSystemPickerModal('DSB upload cancelled');
  }
});

function showSystemPickerModal(dsb_data, match_result) {
  var titleEl    = document.getElementById('systemPickerTitle');
  var subtitleEl = document.getElementById('systemPickerSubtitle');
  var optionsEl  = document.getElementById('systemPickerOptions');

  if (match_result.status === 'none') {
    titleEl.textContent    = 'No matching system found — please select manually';
    subtitleEl.textContent = 'Choose which centralized system from the DSB file to use:';
  } else {
    titleEl.textContent    = 'Multiple matching systems found — please select one';
    subtitleEl.textContent = 'The DSB file contains several possible matches:';
  }

  optionsEl.innerHTML = '';

  // Which entries to show — ambiguous: use matches list; none: show all groups
  var entries = (match_result.status === 'ambiguous' && match_result.matches.length > 0)
    ? match_result.matches.map(function (m) { return { group_index: m.group_index, score: m.score, missing: m.missing_in_dsb, extra: m.extra_in_dsb }; })
    : dsb_data.groups.map(function (g, i) { return { group_index: i, score: null, missing: [], extra: [] }; });

  entries.forEach(function (entry) {
    var group = dsb_data.groups[entry.group_index];
    if (!group) return;

    var systemNames = (group.systems || []).map(function (s) { return s.name; }).filter(Boolean).join(', ');
    var card = document.createElement('div');
    card.className = 'system-picker-option';
    card.setAttribute('tabindex', '0');
    card.setAttribute('role', 'option');

    var html = '<strong>' + escHtml(group.name || ('Group ' + (entry.group_index + 1))) + '</strong>';
    if (systemNames) {
      html += '<div class="picker-systems">' + escHtml(systemNames) + '</div>';
    }

    if (entry.score != null) {
      html += '<div class="deviation-detail">Match score: ' + Math.round(entry.score * 100) + '%';
      if (entry.missing && entry.missing.length > 0) {
        html += ' &bull; Missing in DSB: ' + entry.missing.join(', ');
      }
      if (entry.extra && entry.extra.length > 0) {
        html += ' &bull; Extra in DSB: ' + entry.extra.join(', ');
      }
      html += '</div>';
    }

    card.innerHTML = html;

    function selectOption() {
      fillEquipmentFromDsb(dsb_data, entry.group_index);
      closeSystemPickerModal('Applied: ' + (group.name || 'selected group'));
    }

    card.addEventListener('click', selectOption);
    card.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        selectOption();
      }
    });

    optionsEl.appendChild(card);
  });

  openSystemPickerModal();
}

document.getElementById('systemPickerCancel').addEventListener('click', function () {
  closeSystemPickerModal('DSB upload cancelled');
});

// Close modal on overlay click (outside the box)
systemModal.addEventListener('click', function (e) {
  if (e.target === systemModal) {
    closeSystemPickerModal('DSB upload cancelled');
  }
});

// ── Changelog Modal ───────────────────────────────────────────────────────────

(function() {
  var changelogModal = document.getElementById('changelogModal');

  function openChangelogModal() {
    changelogModal.style.display = 'flex';
    trapFocus(changelogModal);
  }

  function closeChangelogModal() {
    // Remove focus trap handler so it doesn't accumulate
    if (changelogModal._trapHandler) {
      changelogModal.removeEventListener('keydown', changelogModal._trapHandler);
      delete changelogModal._trapHandler;
    }
    changelogModal.style.display = 'none';
    releaseFocus();
  }

  // Escape key to close changelog
  changelogModal.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') {
      closeChangelogModal();
    }
  });

  document.getElementById('btn-changelog').addEventListener('click', openChangelogModal);
  document.getElementById('changelogClose').addEventListener('click', closeChangelogModal);
  document.getElementById('changelogCloseBtm').addEventListener('click', closeChangelogModal);
  changelogModal.addEventListener('click', function (e) {
    if (e.target === changelogModal) closeChangelogModal();
  });
})();

// ── Report generation ─────────────────────────────────────────────────────────

form.addEventListener('submit', async e => {
  e.preventDefault();
  errorEl.classList.remove('visible');

  const selectedDays = getSelectedDays();

  if (selectedDays.length === 0) {
    errorEl.textContent = 'Please select at least one day.';
    errorEl.classList.add('visible');
    return;
  }

  const dataTypeEl = document.querySelector('input[name="data-type"]:checked');
  const jobInfo = {
    job_name:   document.getElementById('site-name').value.trim(),
    technician: document.getElementById('technician').value.trim() || '',
    date:       document.getElementById('report-date').value || selectedDays[0],
    data_types: dataTypeEl ? [dataTypeEl.value] : [],
    notes:      document.getElementById('notes').value.trim(),
  };

  const equipment_data = collectEquipmentData();

  btnGenerate.disabled = true;
  btnExport.disabled = true;
  showProgress('Generating report…');

  try {
    const resp = await fetch(`${API}/api/report`, {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() }, proxyKeyHeader()),
      body: JSON.stringify({ session_id: sessionId, days: selectedDays, job_info: jobInfo, equipment_data }),
    });

    if (!resp.ok) {
      if (resp.status === 404) {
        handleExpired();
        return;
      }
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || resp.statusText);
    }

    if (typeof umami !== 'undefined') {
      umami.track('report-generated', { days: selectedDays.length, data_type: jobInfo.data_types[0] || 'unspecified' });
    }

    const blob = await resp.blob();
    const contentDisp = resp.headers.get('Content-Disposition') || '';
    const match = contentDisp.match(/filename="([^"]+)"/);
    const filename = match
      ? match[1]
      : (selectedDays.length > 1 ? 'VRF_Reports.zip' : `VRF_Report_${selectedDays[0]}.docx`);

    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    errorEl.textContent = `Report generation failed: ${e.message}`;
    errorEl.classList.add('visible');
  } finally {
    btnGenerate.disabled = false;
    btnExport.disabled = false;
    hideProgress();
  }
});

// ── Export Graph Images ───────────────────────────────────────────────────────

btnExport.addEventListener('click', async () => {
  errorEl.classList.remove('visible');

  const selectedDays = getSelectedDays();
  if (selectedDays.length === 0) {
    errorEl.textContent = 'Please select at least one day.';
    errorEl.classList.add('visible');
    return;
  }

  const equipment_data = collectEquipmentData();
  const site_name = document.getElementById('site-name').value.trim();

  btnExport.disabled = true;
  btnGenerate.disabled = true;
  showProgress('Exporting graph images…');

  try {
    const resp = await fetch(`${API}/api/graphs/export`, {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken() }, proxyKeyHeader()),
      body: JSON.stringify({ session_id: sessionId, days: selectedDays, equipment_data, site_name }),
    });

    if (!resp.ok) {
      if (resp.status === 404) {
        handleExpired();
        return;
      }
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || resp.statusText);
    }

    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${site_name || 'graphs'}_export.zip`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    errorEl.textContent = `Export failed: ${e.message}`;
    errorEl.classList.add('visible');
  } finally {
    btnExport.disabled = false;
    btnGenerate.disabled = false;
    hideProgress();
  }
});

// ── Initialise equipment table ────────────────────────────────────────────────

(function initEquipmentTable() {
  try {
    const raw = localStorage.getItem('topology');
    if (!raw) return;
    const topology = JSON.parse(raw);
    if (topology && topology.systems && topology.systems.length > 0) {
      buildEquipmentTable(topology);
      restoreEquipmentFromStorage();
    }
  } catch (_) {
    // Malformed data — silently skip
  }
})();
