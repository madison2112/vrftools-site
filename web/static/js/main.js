/**
 * Shared JS for Central Controller Config Tools.
 * Depends on SortableJS (loaded from CDN in base.html).
 */

// ---------------------------------------------------------------------------
// Drop zone setup
// ---------------------------------------------------------------------------

function setupDropZone(zoneId, inputId, uploadUrl, onSuccess) {
  const zone  = document.getElementById(zoneId);
  const input = document.getElementById(inputId);
  if (!zone || !input) return;

  zone.addEventListener('click', () => input.click());
  input.addEventListener('change', () => {
    if (input.files[0]) uploadFile(input.files[0], uploadUrl, zone, onSuccess);
  });

  zone.addEventListener('dragover',  e => { e.preventDefault(); zone.classList.add('dragging'); });
  zone.addEventListener('dragleave', ()  => zone.classList.remove('dragging'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragging');
    const f = e.dataTransfer.files[0];
    if (f) uploadFile(f, uploadUrl, zone, onSuccess);
  });
}

function uploadFile(file, url, zone, onSuccess) {
  const errEl = zone.closest('.card')?.querySelector('[id$="-error"]');

  if (file.size > 5 * 1024 * 1024) {
    if (errEl) showError(errEl.id, 'File exceeds the 5 MB limit.');
    return;
  }

  zone.classList.add('uploading');
  zone.innerHTML = `<div class="icon"><span class="spinner"></span></div><p>Uploading…</p>`;
  if (errEl) hideError(errEl.id);

  const fd = new FormData();
  fd.append('file', file);

  fetch(url, { method: 'POST', body: fd })
    .then(r => r.json().then(d => ({ ok: r.ok, data: d })))
    .then(({ ok, data }) => {
      zone.classList.remove('uploading');
      if (!ok) {
        resetZone(zone, file.name);
        if (errEl) showError(errEl.id, data.error || 'Upload failed.');
        return;
      }
      resetZone(zone, file.name, true);
      onSuccess(data);
    })
    .catch(() => {
      zone.classList.remove('uploading');
      resetZone(zone, file.name);
      if (errEl) showError(errEl.id, 'Network error — please try again.');
    });
}

function resetZone(zone, filename, success = false) {
  const accept = zone.dataset.accept || '.dat';
  zone.style.borderColor = '';
  zone.style.color       = '';

  if (success) {
    zone.innerHTML = `
      <div class="icon" style="color:var(--green)">&#10003;</div>
      <p><strong>${escHtml(filename)}</strong> uploaded</p>
      <small>Click or drag &amp; drop to upload a different file</small>`;
  } else {
    zone.innerHTML = `
      <div class="icon">&#128196;</div>
      <p>Drag &amp; drop your <strong>${accept}</strong> file here, or click to browse</p>
      <small>Maximum 5 MB</small>`;
  }
}


// ---------------------------------------------------------------------------
// Slot grid renderer (50 fixed slots, two-column layout)
// ---------------------------------------------------------------------------

/**
 * Render the two-column slot grid and return HTML string.
 * Slot numbers are static labels in a separate column; only the cards are sortable.
 * groups: [{slot, tag, mnet_addresses, unit_types, icon}, ...]
 * listIdPrefix: used to generate column element IDs
 * blockIdx: which Groupof50 block this belongs to
 */
function renderGroupGrid(groups, listIdPrefix, blockIdx) {
  const bySlot = {};
  groups.forEach(g => { bySlot[g.slot] = g; });

  const makeItem = (slotNum) => {
    const g = bySlot[slotNum];
    if (!g) {
      return `<div class="slot-item" data-original-slot=""><div class="slot-empty-card"></div></div>`;
    }
    const mnets = (g.mnet_addresses || []).join(', ');
    const types = (g.unit_types || []).join(', ');
    return `<div class="slot-item" data-original-slot="${g.slot}">
      <div class="group-card">
        <span class="group-tag">${escHtml(g.tag || '(unnamed)')}</span>
        <span class="group-mnets">${escHtml(mnets)}</span>
        <span class="group-types">${escHtml(types)}</span>
      </div>
    </div>`;
  };

  const makeLabels = (start, end) => {
    let html = '';
    for (let i = start; i <= end; i++) html += `<div class="slot-label">${i}</div>`;
    return `<div class="slot-label-col" aria-hidden="true">${html}</div>`;
  };

  let col1 = '', col2 = '';
  for (let i = 1;  i <= 25; i++) col1 += makeItem(i);
  for (let i = 26; i <= 50; i++) col2 += makeItem(i);

  return `<div class="slots-grid">
    <div class="slots-half">
      ${makeLabels(1, 25)}
      <div class="slots-col" id="${listIdPrefix}-col1" data-block="${blockIdx}">${col1}</div>
    </div>
    <div class="slots-half">
      ${makeLabels(26, 50)}
      <div class="slots-col" id="${listIdPrefix}-col2" data-block="${blockIdx}">${col2}</div>
    </div>
  </div>`;
}

/**
 * Initialise SortableJS on both columns with cross-column drag enabled.
 */
function initSlotGrid(listIdPrefix, blockIdx) {
  const col1 = document.getElementById(`${listIdPrefix}-col1`);
  const col2 = document.getElementById(`${listIdPrefix}-col2`);
  if (!col1 || !col2 || typeof Sortable === 'undefined') return;

  const opts = {
    group:       `slots-block-${blockIdx}`,
    animation:   120,
    ghostClass:  'sortable-ghost',
    chosenClass: 'sortable-chosen',
    draggable:   '.slot-item',
    onEnd() {
      rebalanceColumns(col1, col2);
      _persistSlotOrder(blockIdx, col1, col2);
    },
  };

  Sortable.create(col1, opts);
  Sortable.create(col2, opts);

  // Sort button
  document.querySelectorAll(`.sort-btn[data-idx="${blockIdx}"]`).forEach(btn => {
    btn.addEventListener('click', () => _sortByTag(blockIdx, listIdPrefix, col1, col2));
  });
}

/** Keep each column at exactly 25 items by moving overflow to the other column. */
function rebalanceColumns(col1, col2) {
  while (col1.children.length > 25) {
    col2.insertBefore(col1.lastElementChild, col2.firstElementChild);
  }
  while (col2.children.length > 25) {
    col1.appendChild(col2.firstElementChild);
  }
}

function _persistSlotOrder(blockIdx, col1, col2) {
  const sid = window.state?.sessionId;
  if (!sid) return;

  const newOrder = [...col1.children, ...col2.children]
    .map(item => parseInt(item.dataset.originalSlot) || 0)
    .filter(s => s > 0);

  fetch(`/api/session/${sid}/groups`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ block_index: blockIdx, new_order: newOrder }),
  }).catch(() => {});
}

function _sortByTag(blockIdx, listIdPrefix, col1, col2) {
  const sid = window.state?.sessionId;
  if (!sid) return;

  fetch(`/api/session/${sid}/sort`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ block_index: blockIdx }),
  })
  .then(r => r.json())
  .then(data => {
    if (!data.new_order) return;

    // Rebuild card elements indexed by original slot
    const allItems = [...col1.children, ...col2.children];
    const byOrigSlot = {};
    allItems.forEach(item => {
      const s = parseInt(item.dataset.originalSlot) || 0;
      if (s > 0) byOrigSlot[s] = item;
    });
    const empties = allItems.filter(item => !parseInt(item.dataset.originalSlot));

    // Place filled cards in new_order sequence, then pad with empties to 50
    const ordered = data.new_order
      .map(s => byOrigSlot[s])
      .filter(Boolean);
    const all50 = ordered.concat(empties).slice(0, 50);

    // Clear and repopulate
    col1.innerHTML = '';
    col2.innerHTML = '';
    all50.slice(0,  25).forEach(el => col1.appendChild(el));
    all50.slice(25, 50).forEach(el => col2.appendChild(el));

    _persistSlotOrder(blockIdx, col1, col2);
  })
  .catch(() => {});
}


// ---------------------------------------------------------------------------
// Warning banners
// ---------------------------------------------------------------------------

function renderWarnings(w) {
  const msgs = [];
  if (w?.sequential_mnet) msgs.push('Group slots match M-Net addresses sequentially — consider rearranging if address order does not reflect intended group order.');
  if (w?.unsorted_tags)   msgs.push('IC group tag names are not in ascending order — use "Sort by Tag Name" to alphabetize.');
  if (!msgs.length) return '';
  return `<div class="alert alert-warn">${msgs.map(m => `<div>&#9888; ${m}</div>`).join('')}</div>`;
}


// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function showError(id, msg) {
  const el = document.getElementById(id);
  if (el) { el.textContent = msg; el.style.display = ''; }
}

function hideError(id) {
  const el = document.getElementById(id);
  if (el) el.style.display = 'none';
}


// ---------------------------------------------------------------------------
// JSON export / session preload (codetest feature)
// ---------------------------------------------------------------------------

function exportJson(sessionId, tool) {
  fetch('/api/export-json', {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ session_id: sessionId, tool }),
  })
  .then(r => {
    if (!r.ok) return r.json().then(d => { throw new Error(d.error || 'Export failed.'); });
    return r.blob();
  })
  .then(blob => {
    const url = URL.createObjectURL(blob);
    const a   = document.createElement('a');
    a.href     = url;
    a.download = 'config_export.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  })
  .catch(err => alert(err.message || 'Export failed.'));
}

function preloadSession(sid, onSuccess) {
  fetch(`/api/session/${sid}/groups`)
    .then(r => r.json())
    .then(data => {
      if (data.blocks) {
        onSuccess({ session_id: sid, blocks: data.blocks, multi: data.blocks.length > 1 });
      }
    })
    .catch(() => {});
}
