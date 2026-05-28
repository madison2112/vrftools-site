// MTDZ Viewer hub — square card grid with upload highlights, info popups,
// and session-based tool navigation. Matches the Central Controller Config
// Tools hub pattern (index.html + main.js).
(function () {
  'use strict';

  function csrfToken() {
    return document.querySelector('meta[name="csrf-token"]').content;
  }

  var PAGES = window.MTDZ_PAGES || {};

  // ── DOM refs ─────────────────────────────────────────────────────────
  var dropZone    = document.getElementById('drop-zone');
  var fileInput   = document.getElementById('file-input');
  var progressBar = document.getElementById('progress-bar');
  var uploadError = document.getElementById('upload-error');
  var uploadCard  = document.getElementById('upload-card');
  var fileBadge   = document.getElementById('file-loaded-badge');
  var fileNameEl  = document.getElementById('file-loaded-name');
  var processingRow = document.getElementById('upload-processing-row');

  // ── State ────────────────────────────────────────────────────────────
  var state = {
    sessionId: null,
    fileName:  null,
    fileType:  null,
    days:      [],
  };

  // ── Tool info (problem/solution popups) ──────────────────────────────
  var TOOL_INFO = {
    viewer: {
      title: 'View Log Data',
      problem: 'Maintenance Tool monitoring files contain sensor trend data in a proprietary binary format. Viewing them requires the Mitsubishi Maintenance Tool software — which runs only on Windows and requires a license.',
      solution: 'Upload your .MTDZ, .MTLZ, or .MTPZ file and view interactive sensor graphs directly in the browser. Select outdoor units, indoor units, and sensors to plot temperature, pressure, and status data over time.'
    },
    report: {
      title: 'Generate Report',
      problem: 'Creating a diagnostic report from monitoring data requires manually exporting graphs and assembling a document. This is time-consuming and error-prone for multi-day or multi-system files.',
      solution: 'Upload your file and download a pre-formatted Word document (.docx) with graphed sensor data for every system in the file. Ready to share or archive.'
    },
    sysconfig: {
      title: 'System Config',
      problem: 'Understanding the physical layout of a CITY MULTI system — which indoor units connect to which ports on which BC controller — requires tracing through M-Net address assignments. This is tedious and hard to visualize.',
      solution: 'Upload a .MTPZ system configuration file and see the full topology mapped out: outdoor units, BC controllers, indoor units, and their port connections. Available for both R2 and WR2 series.'
    },
    rawdata: {
      title: 'Download Raw Data',
      problem: 'When you need to perform custom analysis outside the browser — in Excel, Python, or another tool — the graphed views don\u2019t provide the underlying numeric data.',
      solution: 'Download a CSV file containing every sensor reading extracted from your monitoring file. All data, no aggregation — ready for external analysis.'
    }
  };

  // ── File-type labels for the "no file uploaded" red flash ─────────────
  var TOOL_FILE_TYPE = {
    viewer:    '.MTDZ, .MTLZ, or .MTPZ',
    report:    '.MTDZ, .MTLZ, or .MTPZ',
    sysconfig: '.MTPZ',
    rawdata:   '.MTDZ, .MTLZ, or .MTPZ',
  };

  // ── Session persistence ──────────────────────────────────────────────
  // Tool pages (viewer, report, sysinfo) read from localStorage using
  // the original key names. We store in both places: sessionStorage for
  // the hub's own restore-on-reload, and localStorage for tool page compat.
  function saveSession(data) {
    state.sessionId = data.session_id;
    state.fileName  = data._filename || '';
    state.fileType  = data.file_type;
    state.days      = data.days || [];
    try {
      sessionStorage.setItem('mtdz_session_id',   data.session_id);
      sessionStorage.setItem('mtdz_file_name',    state.fileName);
      sessionStorage.setItem('mtdz_file_type',    state.fileType);
      sessionStorage.setItem('mtdz_days',         JSON.stringify(state.days));
      // Compatibility: tool pages read these localStorage keys
      localStorage.setItem('session_id',          data.session_id);
      localStorage.setItem('file_type',           data.file_type);
      localStorage.setItem('days',                JSON.stringify(data.days));
      localStorage.setItem('systems',             JSON.stringify(data.systems || []));
      localStorage.setItem('sensor_catalog',      JSON.stringify(data.sensor_catalog || {}));
      localStorage.setItem('topology',            JSON.stringify(data.topology || {}));
      localStorage.setItem('filename',            state.fileName);
      // Show the loaded-file badge
      if (fileBadge && fileNameEl) {
        fileNameEl.textContent = state.fileName || 'File loaded';
        fileBadge.style.display = '';
      }
    } catch (e) { /* ignore quota errors */ }
  }

  // Wraps global clearStoredSession() from common.js to also reset local state
  // and hide the loaded-file badge.
  function clearSession() {
    state.sessionId = null;
    state.fileName  = null;
    state.fileType  = null;
    state.days      = [];
    clearStoredSession();
    if (fileBadge) fileBadge.style.display = 'none';
    clearHighlights();
  }

  function restoreSession() {
    try {
      var sid = sessionStorage.getItem('mtdz_session_id');
      if (!sid) return false;
      state.sessionId = sid;
      state.fileName  = sessionStorage.getItem('mtdz_file_name') || '';
      state.fileType  = sessionStorage.getItem('mtdz_file_type') || '';
      state.days      = JSON.parse(sessionStorage.getItem('mtdz_days') || '[]');
      // Show the badge on page reload if a session exists
      if (fileBadge && fileNameEl && state.fileName) {
        fileNameEl.textContent = state.fileName;
        fileBadge.style.display = '';
      }
      return true;
    } catch (e) { return false; }
  }

  // ── Highlights ───────────────────────────────────────────────────────
  function highlightAllTools() {
    document.querySelectorAll('.tool-card-square').forEach(function (c) {
      c.classList.add('highlighted');
    });
  }

  function clearHighlights() {
    document.querySelectorAll('.tool-card-square').forEach(function (c) {
      c.classList.remove('highlighted');
    });
  }

  // ── Upload error display ─────────────────────────────────────────────
  function showUploadError(msg) {
    uploadError.textContent = msg;
    uploadError.style.display = '';
    progressBar.classList.remove('visible');
  }
  function clearUploadError() {
    uploadError.textContent = '';
    uploadError.style.display = 'none';
  }

  // ── Upload handler ───────────────────────────────────────────────────
  async function handleFile(file) {
    var ext = file.name.split('.').pop().toUpperCase();
    if (['MTDZ', 'MTLZ', 'MTPZ'].indexOf(ext) === -1) {
      showUploadError('Unsupported file type: .' + ext + '. Please upload a .MTDZ, .MTLZ, or .MTPZ file.');
      return;
    }
    clearUploadError();
    progressBar.classList.add('visible');
    if (fileBadge) fileBadge.style.display = 'none';
    if (processingRow) processingRow.style.display = '';

    var form = new FormData();
    form.append('file', file);

    try {
      var resp = await fetch(API + '/api/upload', { method: 'POST', headers: { 'X-CSRFToken': csrfToken() }, body: form });
      if (!resp.ok) {
        var err = await resp.json().catch(function () { return { detail: resp.statusText }; });
        throw new Error(err.detail || 'Upload failed');
      }
      var data = await resp.json();
    } catch (e) {
      showUploadError('Upload error: ' + e.message);
      progressBar.classList.remove('visible');
      if (processingRow) processingRow.style.display = 'none';
      return;
    }

    progressBar.classList.remove('visible');
    if (processingRow) processingRow.style.display = 'none';
    data._filename = file.name;
    saveSession(data);
    clearHighlights();
    highlightAllTools();

    // .MTPZ (sysinfo) files auto-redirect to the System Config page
    if (data.file_type === 'sysinfo') {
      var sysCard = document.querySelector('.tool-card-square[data-tool="sysconfig"]');
      if (sysCard) sysCard.classList.add('highlighted');
      window.location.href = PAGES.sysconfig + '?session=' + data.session_id;
      return;
    }

    if (typeof umami !== 'undefined') {
      umami.track('file-uploaded', { file_type: data.file_type, days: data.days.length });
    }
  }

  // ── Info popup (same as central control hub pattern) ──────────────────
  function showInfoPopup(info) {
    var overlay = document.createElement('div');
    overlay.className = 'info-popup-overlay';
    overlay.innerHTML =
      '<div class="info-popup">' +
        '<h3>' + escHtml(info.title) + '</h3>' +
        '<p><span class="problem-label">The problem:</span> ' + escHtml(info.problem) + '</p>' +
        '<p><span class="solution-label">The solution:</span> ' + escHtml(info.solution) + '</p>' +
        '<button class="close-popup">Close</button>' +
      '</div>';
    document.body.appendChild(overlay);

    function closePopup() {
      document.removeEventListener('keydown', handleEscape);
      window.releaseFocus();
      overlay.remove();
    }
    function handleEscape(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        closePopup();
      }
    }
    document.addEventListener('keydown', handleEscape);

    overlay.querySelector('.close-popup').addEventListener('click', closePopup);
    overlay.addEventListener('click', function (e) { if (e.target === overlay) closePopup(); });

    window.trapFocus(overlay);
  }

  // ── Red flash + popup when clicking a card before uploading ───────────
  function flashCardWarning(card, message) {
    card.classList.add('warning-flash');
    showInfoPopup({
      title: 'Upload Required',
      problem: message,
      solution: 'Upload an .MTDZ, .MTLZ, or .MTPZ file in the upload box above, then click the highlighted card.'
    });
    setTimeout(function () {
      card.classList.remove('warning-flash');
    }, 2500);
  }

  // ── Card activation (click + keyboard) ────────────────────────────────
  function activateCard(card) {
    var tool = card.dataset.tool;
    var href = card.dataset.href;

    // Raw data download — special case (doesn't navigate)
    if (tool === 'rawdata') {
      if (!state.sessionId) {
        flashCardWarning(card, 'Upload a file before downloading raw data.');
        return;
      }
      downloadRawData();
      return;
    }

    // Session exists — navigate with session ID
    if (state.sessionId) {
      // Mobile block for viewer and sysconfig
      if ((tool === 'viewer' || tool === 'sysconfig') && isMobile()) {
        flashCardWarning(card, 'This tool is not available on mobile — please use a desktop browser.');
        return;
      }
      window.location.href = href + '?session=' + state.sessionId;
      return;
    }

    // No session — flash red with file-type specific message
    var ext = TOOL_FILE_TYPE[tool] || '.MTDZ';
    flashCardWarning(card, 'Upload a <strong>' + ext + '</strong> file before accessing this tool.');
  }

  document.querySelectorAll('.tool-card-square').forEach(function (card) {
    // Click handler
    card.addEventListener('click', function (e) {
      if (e.target.closest('.info-btn')) return;
      activateCard(card);
    });

    // Keyboard handler (Enter / Space)
    card.addEventListener('keydown', function (e) {
      if (e.target.closest('.info-btn')) return;
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();  // prevent Space from scrolling the page
        activateCard(card);
      }
    });
  });

  // ── Raw data download ────────────────────────────────────────────────
  async function downloadRawData() {
    if (!state.sessionId) return;
    try {
      var resp = await fetch(API + '/api/rawdata/' + state.sessionId);
      if (resp.status === 404) {
        clearSession();
        showUploadError('Your session expired — please re-upload your file.');
        return;
      }
      if (!resp.ok) throw new Error(resp.statusText);
      var disposition = resp.headers.get('Content-Disposition') || '';
      var match = disposition.match(/filename="([^"]+)"/);
      var filename = match ? match[1] : 'raw_data.zip';
      var blob = await resp.blob();
      var url = URL.createObjectURL(blob);
      var a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      showUploadError('Download failed: ' + e.message);
    }
  }

  // ── Info button clicks ───────────────────────────────────────────────
  document.querySelectorAll('.info-btn').forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      e.stopPropagation();
      e.preventDefault();
      var toolId = btn.dataset.popup;
      var info = TOOL_INFO[toolId];
      if (!info) return;
      showInfoPopup(info);
    });
  });

  // ── Upload zone ──────────────────────────────────────────────────────
  dropZone.addEventListener('click', function () { fileInput.click(); });
  dropZone.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();  // prevent Space from scrolling the page
      fileInput.click();
    }
  });
  dropZone.addEventListener('dragover', function (e) { e.preventDefault(); dropZone.classList.add('dragging'); });
  dropZone.addEventListener('dragleave', function () { dropZone.classList.remove('dragging'); });
  dropZone.addEventListener('drop', function (e) {
    e.preventDefault();
    dropZone.classList.remove('dragging');
    if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener('change', function () {
    if (fileInput.files[0]) handleFile(fileInput.files[0]);
  });

  // ── Session restore on page load ─────────────────────────────────────
  if (restoreSession()) {
    highlightAllTools();
  }

  // ── Clear data button ────────────────────────────────────────────────
  var btnClear = document.getElementById('btn-clear-data');
  if (btnClear) {
    btnClear.addEventListener('click', function () {
      clearSession();
      clearUploadError();
    });
  }
})();
