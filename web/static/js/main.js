/**
 * Shared JS for Central Controller Config Tools.
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
      <div class="group-card" draggable="true">
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
 * Wire up native HTML5 drag-and-drop on the fixed slot grid.
 * Slots are fixed containers; only card content swaps on drop.
 * Empty slots accept drops but cannot be dragged.
 */
function initSlotGrid(listIdPrefix, blockIdx) {
  const col1 = document.getElementById(`${listIdPrefix}-col1`);
  const col2 = document.getElementById(`${listIdPrefix}-col2`);
  if (!col1 || !col2) return;

  if (!window.state.gridCols) window.state.gridCols = {};
  window.state.gridCols[blockIdx] = { col1, col2 };

  let dragSrc = null;

  function allSlots() {
    return [...col1.children, ...col2.children];
  }

  function bindSlot(slotEl) {
    slotEl.addEventListener('dragstart', e => {
      dragSrc = slotEl;
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', ''); // required by Firefox
    });

    slotEl.addEventListener('dragend', () => {
      allSlots().forEach(s => s.classList.remove('drag-over'));
      dragSrc = null;
    });

    slotEl.addEventListener('dragover', e => {
      if (dragSrc && dragSrc !== slotEl) e.preventDefault();
    });

    slotEl.addEventListener('dragenter', e => {
      if (!dragSrc || dragSrc === slotEl) return;
      e.preventDefault();
      allSlots().forEach(s => s.classList.remove('drag-over'));
      slotEl.classList.add('drag-over');
    });

    slotEl.addEventListener('dragleave', e => {
      if (!slotEl.contains(e.relatedTarget)) slotEl.classList.remove('drag-over');
    });

    slotEl.addEventListener('drop', e => {
      e.preventDefault();
      slotEl.classList.remove('drag-over');
      if (!dragSrc || dragSrc === slotEl) return;

      const tmpOrig        = dragSrc.dataset.originalSlot;
      dragSrc.dataset.originalSlot = slotEl.dataset.originalSlot;
      slotEl.dataset.originalSlot  = tmpOrig;

      const tmpHtml  = dragSrc.innerHTML;
      dragSrc.innerHTML = slotEl.innerHTML;
      slotEl.innerHTML  = tmpHtml;

      // Re-attach draggable after innerHTML swap (event listeners don't survive)
      [dragSrc, slotEl].forEach(s => {
        const card = s.querySelector('.group-card');
        if (card) card.setAttribute('draggable', 'true');
      });

      dragSrc = null;
      _persistSlotOrder(blockIdx, col1, col2);
    });
  }

  allSlots().forEach(bindSlot);

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
  if (!sid) return Promise.resolve();

  const newOrder = [...col1.children, ...col2.children]
    .map(item => parseInt(item.dataset.originalSlot) || 0);

  return fetch(`/api/session/${sid}/groups`, {
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

async function exportJson(sessionId, tool) {
  // Flush any pending slot-order saves before exporting so the JSON captures
  // the latest card arrangement.  Without this the server still sees the
  // pre-drag order when it builds the export payload.
  if (window.state && window.state.gridCols) {
    var saves = Object.entries(window.state.gridCols).map(function(entry) {
      var idx  = parseInt(entry[0]);
      var cols = entry[1];
      return _persistSlotOrder(idx, cols.col1, cols.col2);
    });
    await Promise.all(saves);
  }

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
    a.download = 'vrf-tools_session.json';
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

function initFloatingSaveButton(toolName) {
  var existing = document.getElementById('float-save-btn');
  if (existing) existing.remove();

  var btn = document.createElement('button');
  btn.id = 'float-save-btn';
  btn.className = 'float-save-btn';
  btn.innerHTML = '<span class="save-icon">&#128190;</span> Save Session / Share';
  btn.title = 'Export this session as a shareable JSON file';

  btn.addEventListener('click', function() {
    if (window.state && window.state.sessionId) {
      exportJson(window.state.sessionId, toolName);
    }
  });

  document.body.appendChild(btn);
  return btn;
}

function showFloatingSaveButton() {
  var btn = document.getElementById('float-save-btn');
  if (btn) btn.classList.add('visible');
}

// Controller name auto-save on change
document.addEventListener('change', function(e) {
  if (!e.target.classList.contains('ctrl-name-input')) return;
  var idx = parseInt(e.target.dataset.idx);
  var newName = e.target.value.trim();
  if (!newName || !(window.state && window.state.sessionId)) return;

  fetch('/api/session/' + window.state.sessionId + '/controller-name', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ block_index: idx, name: newName }),
  })
  .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
  .then(function(result) {
    if (result.ok) {
      e.target.style.borderColor = 'var(--green)';
      e.target.style.background = '#f1f8f1';
      setTimeout(function() {
        e.target.style.borderColor = 'transparent';
        e.target.style.background = 'transparent';
      }, 1200);
    }
  })
  .catch(function() {});
});

// Double-click group tag names to edit inline
document.addEventListener('dblclick', function(e) {
  var tagEl = e.target.closest('.group-tag');
  if (!tagEl || tagEl.querySelector('.group-tag-edit')) return;

  var slotItem = tagEl.closest('.slot-item');
  if (!slotItem) return;
  var slot = parseInt(slotItem.dataset.originalSlot);
  if (!slot) return;

  var blockSection = slotItem.closest('.block-section');
  var blockIdx = blockSection ? parseInt(blockSection.dataset.blockIdx) : 0;

  var currentText = tagEl.textContent.trim();
  var input = document.createElement('input');
  input.type = 'text';
  input.className = 'group-tag-edit';
  input.value = currentText;
  input.style.width = Math.max(currentText.length * 10 + 20, 80) + 'px';

  var commit = function() {
    var newTag = input.value.trim();
    if (newTag && newTag !== currentText && window.state && window.state.sessionId) {
      fetch('/api/session/' + window.state.sessionId + '/group-name', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ block_index: blockIdx, slot: slot, tag: newTag }),
      })
      .then(function(r) { return r.json().then(function(d) { return { ok: r.ok, data: d }; }); })
      .then(function(result) {
        if (result.ok) {
          tagEl.textContent = newTag;
        }
      })
      .catch(function() {});
    }
    input.remove();
  };

  var cancel = function() {
    input.remove();
  };

  input.addEventListener('blur', commit);
  input.addEventListener('keydown', function(ke) {
    if (ke.key === 'Enter') { ke.preventDefault(); commit(); }
    if (ke.key === 'Escape') { ke.preventDefault(); cancel(); }
  });

  tagEl.appendChild(input);
  input.focus();
  input.select();
});

// Cancel any active tag edit when a drag starts
document.addEventListener('dragstart', function() {
  var active = document.querySelector('.group-tag-edit');
  if (active) active.remove();
});
