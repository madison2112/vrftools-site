// ── Session state ──────────────────────────────────────────────────────────────
const sessionId = localStorage.getItem('session_id');
const days      = JSON.parse(localStorage.getItem('days') || '[]');

const _vp = window.MTDZ_PAGES || {};
const _PAGE_INDEX  = _vp.index    || 'index.html';
const _PAGE_REPORT = _vp.report   || 'report.html';
const _PAGE_SYS    = _vp.sysconfig || 'sysinfo.html';

if (!sessionId) { window.location.href = _PAGE_INDEX; }

let currentDay    = days[0] || null;
let currentSysIdx = 0;

// ── DOM refs ───────────────────────────────────────────────────────────────────
const linkReport     = document.getElementById('link-report');
const linkSysconfig  = document.getElementById('link-sysconfig');
const dayTabsRow     = document.getElementById('day-tabs-row');
const dayTabsEl      = document.getElementById('day-tabs');
const sysSelectorRow = document.getElementById('system-selector-row');
const sysSelect      = document.getElementById('system-select');
const errorEl        = document.getElementById('error-msg');
const oduGraphs      = document.getElementById('odu-graphs');
const oduSkeleton    = document.getElementById('odu-skeleton');
const iduGraphs      = document.getElementById('idu-graphs');
const iduSkeleton    = document.getElementById('idu-skeleton');

// ── Init ───────────────────────────────────────────────────────────────────────

linkReport.style.display = '';
linkReport.href = _PAGE_REPORT;
linkSysconfig.style.display = '';
linkSysconfig.href = _PAGE_SYS;

// Day tabs (MTLZ)
if (days.length > 1) {
  dayTabsRow.style.display = '';
  days.forEach(day => {
    const tab = document.createElement('button');
    tab.className = 'day-tab' + (day === currentDay ? ' active' : '');
    tab.textContent = day;
    tab.addEventListener('click', () => selectDay(day));
    dayTabsEl.appendChild(tab);
  });
}

// System selector
sysSelect.addEventListener('change', () => {
  currentSysIdx = parseInt(sysSelect.value, 10);
  renderCurrentSystem();
});

// Load first day
loadDay(currentDay);

// ── Day selection ──────────────────────────────────────────────────────────────
function selectDay(day) {
  currentDay = day;
  document.querySelectorAll('.day-tab').forEach(t => {
    t.classList.toggle('active', t.textContent === day);
  });
  loadDay(day);
}

// ── Data loading ───────────────────────────────────────────────────────────────
async function loadDay(day) {
  showSkeletons(true);
  errorEl.classList.remove('visible');

  let data;
  try {
    const resp = await fetch(`${API}/api/data/${sessionId}/${day}`, { headers: proxyKeyHeader() });
    if (!resp.ok) {
      if (resp.status === 404) {
        handleExpired();
        return;
      }
      throw new Error((await resp.json().catch(() => ({}))).detail || resp.statusText);
    }
    data = await resp.json();
  } catch (e) {
    errorEl.textContent = `Error loading data: ${e.message}`;
    errorEl.classList.add('visible');
    showSkeletons(false);
    return;
  }

  window._graphData = data;

  // Populate system selector
  if (data.systems.length > 1) {
    sysSelectorRow.style.display = '';
    sysSelect.innerHTML = '';
    data.systems.forEach((sys, i) => {
      const opt = document.createElement('option');
      opt.value = i;
      opt.textContent = sys.system_id;
      if (i === currentSysIdx) opt.selected = true;
      sysSelect.appendChild(opt);
    });
  } else {
    sysSelectorRow.style.display = 'none';
    currentSysIdx = 0;
  }

  showSkeletons(false);
  renderCurrentSystem();
}

function renderCurrentSystem() {
  const data = window._graphData;
  if (!data) return;
  const sys = data.systems[currentSysIdx];
  if (!sys) return;

  oduGraphs.innerHTML = '';
  sys.odu_graphs.forEach(g => {
    const div = document.createElement('div');
    div.style.marginBottom = '16px';
    oduGraphs.appendChild(div);
    Plotly.newPlot(div, g.graph.data, g.graph.layout, { responsive: true, displayModeBar: true });
  });

  iduGraphs.innerHTML = '';
  sys.idu_graphs.forEach(g => {
    const wrapper = document.createElement('div');
    iduGraphs.appendChild(wrapper);

    const shadingCount = g.graph.shading_count || 0;
    if (shadingCount > 0) {
      const origOpacities = g.graph.layout.shapes.slice(0, shadingCount).map(s => s.opacity);
      let shadingVisible = true;
      const btn = document.createElement('button');
      btn.className = 'advanced-toggle';
      btn.textContent = 'Hide shading';
      btn.style.marginBottom = '4px';
      btn.addEventListener('click', () => {
        shadingVisible = !shadingVisible;
        btn.textContent = shadingVisible ? 'Hide shading' : 'Show shading';
        const update = {};
        for (let i = 0; i < shadingCount; i++) {
          update[`shapes[${i}].opacity`] = shadingVisible ? origOpacities[i] : 0;
        }
        Plotly.relayout(plotDiv, update);
      });
      wrapper.appendChild(btn);
    }

    const plotDiv = document.createElement('div');
    wrapper.appendChild(plotDiv);
    Plotly.newPlot(plotDiv, g.graph.data, g.graph.layout, { responsive: true, displayModeBar: true });
  });
}

function showSkeletons(show) {
  oduSkeleton.style.display = show ? '' : 'none';
  iduSkeleton.style.display = show ? '' : 'none';
  oduGraphs.style.display   = show ? 'none' : '';
  iduGraphs.style.display   = show ? 'none' : '';
}
