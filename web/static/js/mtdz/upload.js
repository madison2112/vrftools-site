const API = window.location.protocol === 'file:' ? 'http://localhost:8000' : '';

const dropZone      = document.getElementById('drop-zone');
const fileInput     = document.getElementById('file-input');
const progressBar   = document.getElementById('progress-bar');
const errorMsg      = document.getElementById('error-msg');
const deleteError   = document.getElementById('delete-error');
const modeCard      = document.getElementById('mode-card');
const uploadCard    = document.getElementById('upload-card');
const fileTitle     = document.getElementById('file-title');
const dayInfo       = document.getElementById('day-info');
const btnReport     = document.getElementById('btn-report');
const btnRawdata    = document.getElementById('btn-rawdata');
const btnSysconfig  = document.getElementById('btn-sysconfig');
const btnViewer     = document.getElementById('btn-viewer');
const btnDiffFile   = document.getElementById('btn-different-file');
const btnDeleteFile = document.getElementById('btn-delete-file');
const btnReportIssue = document.getElementById('btn-report-issue');

const isMobile = () => window.innerWidth < 768;

const _pages = window.MTDZ_PAGES || {};
const PAGE_REPORT  = _pages.report    || 'report.html';
const PAGE_SYSINFO = _pages.sysconfig || 'sysinfo.html';
const PAGE_VIEWER  = _pages.viewer    || 'viewer.html';
const PAGE_INDEX   = _pages.index     || 'index.html';

// ── Session helpers ────────────────────────────────────────────────────────────

function saveSession(data, filename) {
  localStorage.setItem('session_id',     data.session_id);
  localStorage.setItem('file_type',      data.file_type);
  localStorage.setItem('days',           JSON.stringify(data.days));
  localStorage.setItem('systems',        JSON.stringify(data.systems));
  localStorage.setItem('sensor_catalog', JSON.stringify(data.sensor_catalog || {}));
  localStorage.setItem('topology',       JSON.stringify(data.topology || {}));
  localStorage.setItem('filename',       filename);
}

function clearSession() {
  ['session_id','file_type','days','systems','sensor_catalog','topology','filename']
    .forEach(k => localStorage.removeItem(k));
}

function showModeCard(filename, days) {
  fileTitle.textContent = `File: ${filename}`;
  if (days.length > 1) {
    dayInfo.textContent = `${days.length} days: ${days.join(', ')}`;
  } else if (days.length === 1) {
    dayInfo.textContent = `Date: ${days[0]}`;
  } else {
    dayInfo.textContent = '';
  }
  uploadCard.style.display = 'none';
  modeCard.style.display = '';
  btnDiffFile.style.display = '';
  btnDeleteFile.style.display = '';
  btnReportIssue.style.display = '';
}

// ── Resume previous session on page load ──────────────────────────────────────

if (new URLSearchParams(window.location.search).get('expired') === '1') {
  clearSession();
  showError('Your session expired — please re-upload your file.');
  history.replaceState(null, '', window.location.pathname);
}

const storedId       = localStorage.getItem('session_id');
const storedFilename = localStorage.getItem('filename');
const storedDays     = JSON.parse(localStorage.getItem('days') || '[]');

if (storedId && storedFilename) {
  showModeCard(storedFilename, storedDays);
}

// ── Mode card navigation ───────────────────────────────────────────────────────

btnReport.addEventListener('click', () => { window.location.href = PAGE_REPORT; });

btnRawdata.addEventListener('click', async () => {
  const sid = localStorage.getItem('session_id');
  if (!sid) return;
  try {
    const resp = await fetch(`${API}/api/rawdata/${sid}`);
    if (resp.status === 404) { handleExpired(); return; }
    if (!resp.ok) throw new Error(resp.statusText);
    const disposition = resp.headers.get('Content-Disposition') || '';
    const match = disposition.match(/filename="([^"]+)"/);
    const filename = match ? match[1] : 'raw_data.zip';
    const blob = await resp.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  } catch (e) {
    deleteError.textContent = `Download failed: ${e.message}`;
    deleteError.classList.add('visible');
  }
});

btnSysconfig.addEventListener('click', () => {
  if (isMobile()) {
    showMobileBlock('System configuration map is not available on mobile — please use a desktop browser.');
    return;
  }
  window.location.href = PAGE_SYSINFO;
});

btnViewer.addEventListener('click', () => {
  if (isMobile()) {
    showMobileBlock('Log data graphs are not available on mobile — please use a desktop browser.');
    return;
  }
  window.location.href = PAGE_VIEWER;
});

function showMobileBlock(msg) {
  deleteError.textContent = msg;
  deleteError.classList.add('visible');
}

// ── Utility links ──────────────────────────────────────────────────────────────

btnDiffFile.addEventListener('click', e => {
  e.preventDefault();
  clearSession();
  modeCard.style.display = 'none';
  uploadCard.style.display = '';
  deleteError.classList.remove('visible');
});

btnDeleteFile.addEventListener('click', async e => {
  e.preventDefault();
  const sid = localStorage.getItem('session_id');
  if (!sid) { clearSession(); location.reload(); return; }
  try {
    await fetch(`${API}/api/session/${sid}`, { method: 'DELETE' });
  } catch (_) { /* ignore network errors — session may already be gone */ }
  clearSession();
  modeCard.style.display = 'none';
  uploadCard.style.display = '';
  deleteError.classList.remove('visible');
});

// ── Upload zone ────────────────────────────────────────────────────────────────

dropZone.addEventListener('click', () => fileInput.click());
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('dragging'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragging'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('dragging');
  const f = e.dataTransfer.files[0];
  if (f) handleFile(f);
});
fileInput.addEventListener('change', () => {
  if (fileInput.files[0]) handleFile(fileInput.files[0]);
});

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.add('visible');
  progressBar.classList.remove('visible');
}

async function handleFile(file) {
  const ext = file.name.split('.').pop().toUpperCase();
  if (!['MTDZ', 'MTLZ', 'MTPZ'].includes(ext)) {
    showError(`Unsupported file type: .${ext}. Please upload a .MTDZ or .MTLZ file.`);
    return;
  }
  errorMsg.classList.remove('visible');
  progressBar.classList.add('visible');

  const form = new FormData();
  form.append('file', file);

  let data;
  try {
    const resp = await fetch(`${API}/api/upload`, { method: 'POST', body: form });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ detail: resp.statusText }));
      throw new Error(err.detail || 'Upload failed');
    }
    data = await resp.json();
  } catch (e) {
    showError(`Upload error: ${e.message}`);
    return;
  }

  progressBar.classList.remove('visible');
  clearSession();
  saveSession(data, file.name);

  if (typeof umami !== 'undefined') {
    umami.track('file-uploaded', { file_type: data.file_type, days: data.days.length });
  }

  if (data.file_type === 'sysinfo') {
    window.location.href = PAGE_SYSINFO;
    return;
  }

  showModeCard(file.name, data.days);
}

function handleExpired() {
  clearSession();
  window.location.href = PAGE_INDEX + '?expired=1';
}
