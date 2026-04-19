/**
 * Shared JS for Central Controller Config Tools.
 * Depends on SortableJS (loaded from CDN in base.html — loaded per-page when needed).
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

  zone.addEventListener('dragover', e => { e.preventDefault(); zone.classList.add('dragging'); });
  zone.addEventListener('dragleave', () => zone.classList.remove('dragging'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('dragging');
    const f = e.dataTransfer.files[0];
    if (f) uploadFile(f, uploadUrl, zone, onSuccess);
  });
}

function uploadFile(file, url, zone, onSuccess) {
  const errId = zone.closest('.card')?.querySelector('[id$="-error"]')?.id;

  if (file.size > 5 * 1024 * 1024) {
    if (errId) showError(errId, 'File exceeds the 5 MB limit.');
    return;
  }

  zone.classList.add('uploading');
  zone.innerHTML = `<div class="icon"><span class="spinner"></span></div><p>Uploading…</p>`;
  if (errId) hideError(errId);

  const fd = new FormData();
  fd.append('file', file);

  fetch(url, { method: 'POST', body: fd })
    .then(r => r.json().then(d => ({ ok: r.ok, data: d })))
    .then(({ ok, data }) => {
      zone.classList.remove('uploading');
      if (!ok) {
        resetZone(zone, file.name);
        if (errId) showError(errId, data.error || 'Upload failed.');
        return;
      }
      resetZone(zone, file.name, true);
      onSuccess(data);
    })
    .catch(err => {
      zone.classList.remove('uploading');
      resetZone(zone, file.name);
      if (errId) showError(errId, 'Network error — please try again.');
    });
}

function resetZone(zone, filename, success = false) {
  const accept = zone.dataset.accept || '.dat';
  if (success) {
    zone.innerHTML = `<div class="icon">&#10003;</div><p><strong>${escHtml(filename)}</strong> uploaded</p>`;
    zone.style.borderColor = 'var(--green)';
    zone.style.color = 'var(--green)';
  } else {
    zone.innerHTML = `
      <div class="icon">&#128196;</div>
      <p>Drag &amp; drop your <strong>${accept}</strong> file here, or <label class="link-btn">browse
        <input type="file" accept="${accept}" style="display:none" onchange="this.parentElement.closest('.drop-zone').dispatchEvent(new Event('reselect'))">
      </label></p>
      <small>Maximum 5 MB</small>`;
  }
}


// ---------------------------------------------------------------------------
// Sortable group list
// ---------------------------------------------------------------------------

// Maps blockIdx -> current order array (list of old slot numbers)
const _orderState = {};

function initSortable(listId, blockIdx) {
  const el = document.getElementById(listId);
  if (!el || typeof Sortable === 'undefined') return;

  // Capture initial order from DOM
  _orderState[blockIdx] = [...el.querySelectorAll('.group-card')].map(c => parseInt(c.dataset.slot));

  Sortable.create(el, {
    handle: '.drag-handle',
    animation: 150,
    ghostClass: 'sortable-ghost',
    chosenClass: 'sortable-chosen',
    onEnd() {
      const newOrder = [...el.querySelectorAll('.group-card')].map(c => parseInt(c.dataset.slot));
      _orderState[blockIdx] = newOrder;
      updateSlotNumbers(el);
      persistOrder(blockIdx, newOrder);
    },
  });

  // Sort-by-tag button
  document.querySelectorAll(`.sort-btn[data-idx="${blockIdx}"]`).forEach(btn => {
    btn.addEventListener('click', () => sortByTag(blockIdx, listId));
  });
}

function updateSlotNumbers(listEl) {
  listEl.querySelectorAll('.group-card').forEach((card, i) => {
    const slotEl = card.querySelector('.group-slot');
    if (slotEl) slotEl.textContent = i + 1;
  });
}

function persistOrder(blockIdx, newOrder) {
  const sid = window.state?.sessionId;
  if (!sid) return;
  fetch(`/api/session/${sid}/groups`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ block_index: blockIdx, new_order: newOrder }),
  }).catch(() => {});
}

function sortByTag(blockIdx, listId) {
  const sid = window.state?.sessionId;
  if (!sid) return;
  fetch(`/api/session/${sid}/sort`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ block_index: blockIdx }),
  })
  .then(r => r.json())
  .then(data => {
    if (!data.new_order) return;
    const listEl = document.getElementById(listId);
    if (!listEl) return;
    // Re-order DOM cards according to new_order
    const cards = {};
    listEl.querySelectorAll('.group-card').forEach(c => { cards[parseInt(c.dataset.slot)] = c; });
    data.new_order.forEach(slot => {
      if (cards[slot]) listEl.appendChild(cards[slot]);
    });
    updateSlotNumbers(listEl);
    _orderState[blockIdx] = data.new_order;
  })
  .catch(() => {});
}


// ---------------------------------------------------------------------------
// Group card renderer
// ---------------------------------------------------------------------------

function renderGroupCard(g) {
  const types = (g.unit_types || []).join(', ');
  const mnets = (g.mnet_addresses || []).join(', ');
  return `
    <div class="group-card" data-slot="${g.slot}">
      <span class="drag-handle">&#9776;</span>
      <span class="group-slot">${g.slot}</span>
      <span class="group-tag">${escHtml(g.tag || '(unnamed)')}</span>
      <span class="group-mnets">${escHtml(mnets)}</span>
      <span class="group-types">${escHtml(types)}</span>
    </div>`;
}

function renderWarnings(w) {
  const msgs = [];
  if (w?.sequential_mnet) msgs.push('Group slots match M-Net addresses sequentially — rearranging is recommended if groups do not need to be in address order.');
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
