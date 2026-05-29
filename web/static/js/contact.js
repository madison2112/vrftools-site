/* Scoping: Global-scope form handler. */
const API = '';

function csrfToken() {
  return document.querySelector('meta[name="csrf-token"]').content;
}

const form             = document.getElementById('contact-form');
const categorySelector    = document.getElementById('category-selector');
const categoryLocked      = document.getElementById('category-locked');
const categoryLockedLabel = document.getElementById('category-locked-label');
const toolSection         = document.getElementById('tool-section');
const toolReqLabel        = document.getElementById('tool-req-label');
const messageSection      = document.getElementById('message-section');
const messageTextarea  = document.getElementById('contact-message');
const attachSection    = document.getElementById('attachments-section');
const attachZone       = document.getElementById('attach-zone');
const fileInput        = document.getElementById('contact-files');
const manualChipList   = document.getElementById('manual-chip-list');
const consentCheck     = document.getElementById('contact-consent');
const btnSubmit        = document.getElementById('btn-submit');
const submitStatus     = document.getElementById('submit-status');
const errorMsg         = document.getElementById('error-msg');
const successMsg       = document.getElementById('success-msg');

const MAX_MANUAL_FILES   = 3;
const MAX_TOTAL_BYTES    = 25 * 1024 * 1024;
const ALLOWED_EXTS       = new Set(['mtdz', 'mtlz', 'png', 'jpg', 'jpeg', 'gif']);

const MESSAGE_PLACEHOLDERS = {
  issue:    'Describe what happened, what you expected, and how to reproduce it…',
  feature:  'Describe the feature and why it would be useful…',
  feedback: 'Share your thoughts…',
  other:    'How can we help?',
};

// ── State ───────────────────────────��──────────────────────────────���───────────

let currentCategory = null;
let manualFiles = [];

// ── URL parameters ─────────────────────────────────────────────────────────────

const params     = new URLSearchParams(window.location.search);
const lockedType = params.get('type');
const toolParam  = params.get('tool');

if (lockedType === 'issue' || lockedType === 'feature') {
  categorySelector.style.display = 'none';
  categoryLocked.style.display = '';
  const label = lockedType === 'issue' ? 'Issue' : 'Feature Request';
  if (categoryLockedLabel) categoryLockedLabel.textContent = label;
  setCategory(lockedType);
}

if (toolParam) {
  const cb = document.querySelector(`input[name="tool"][value="${toolParam}"]`);
  if (cb) cb.checked = true;
}

// ── Category radio change ──────────────────────────────────────────────────────

document.querySelectorAll('input[name="category"]').forEach(radio => {
  radio.addEventListener('change', () => setCategory(radio.value));
});

function setCategory(cat) {
  currentCategory = cat;
  messageSection.style.display = '';
  messageTextarea.placeholder = MESSAGE_PLACEHOLDERS[cat] || 'How can we help?';

  if (cat === 'issue' || cat === 'feature') {
    toolSection.style.display = '';
    toolReqLabel.textContent = cat === 'issue' ? '(required)' : '(optional)';
    toolReqLabel.style.color = cat === 'issue' ? 'var(--red)' : '';
    toolReqLabel.style.fontWeight = cat === 'issue' ? '600' : '';
  } else {
    toolSection.style.display = 'none';
  }

  if (cat === 'issue') {
    attachSection.style.display = '';
  } else {
    attachSection.style.display = 'none';
  }
}

// ── Manual file picker ─────────────────────────────────────────────────────────

attachZone.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', () => {
  const incoming = [...fileInput.files];
  fileInput.value = '';   // reset so same file can be re-added after removal

  for (const f of incoming) {
    const ext = f.name.split('.').pop().toLowerCase();
    if (!ALLOWED_EXTS.has(ext)) {
      showError(`File type .${ext} is not allowed. Please attach screenshots (PNG/JPG/GIF) or MTDZ/MTLZ files.`);
      return;
    }
  }

  const combined = [...manualFiles, ...incoming];
  if (combined.length > MAX_MANUAL_FILES) {
    showError(`You can attach up to ${MAX_MANUAL_FILES} files.`);
    return;
  }

  const totalBytes = combined.reduce((s, f) => s + f.size, 0);
  if (totalBytes > MAX_TOTAL_BYTES) {
    showError('Total attachment size exceeds 25 MB.');
    return;
  }

  errorMsg.classList.remove('visible');
  manualFiles = combined;
  renderManualChips();
});

function renderManualChips() {
  manualChipList.innerHTML = '';
  manualFiles.forEach((f, idx) => {
    const chip = document.createElement('div');
    chip.className = 'chip';
    chip.innerHTML = `<span>${f.name} <span style="opacity:0.6">(${(f.size / 1024).toFixed(0)} KB)</span></span>`;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chip-remove';
    btn.title = 'Remove';
    btn.textContent = '×';
    btn.addEventListener('click', () => {
      manualFiles.splice(idx, 1);
      renderManualChips();
    });
    chip.appendChild(btn);
    manualChipList.appendChild(chip);
  });
}

// ── Form submission ────────────────────────────────────────────────────────────

form.addEventListener('submit', async e => {
  e.preventDefault();
  errorMsg.classList.remove('visible');

  const email   = document.getElementById('contact-email').value.trim();
  const message = messageTextarea.value.trim();

  if (!currentCategory) {
    showError('Please select a category.');
    return;
  }
  if (!email) {
    showError('Please enter your email address.');
    return;
  }
  if (!message) {
    showError('Please enter a message.');
    return;
  }
  if (currentCategory === 'issue') {
    const checkedTools = document.querySelectorAll('input[name="tool"]:checked');
    if (checkedTools.length === 0) {
      showError('Please select at least one affected tool.');
      return;
    }
  }
  if (!consentCheck.checked) {
    showError('Please check the box to confirm before sending.');
    return;
  }

  btnSubmit.disabled = true;
  submitStatus.style.display = '';

  const fd = new FormData();
  fd.append('name',                 document.getElementById('contact-name').value.trim());
  fd.append('email',                email);
  fd.append('message',              message);
  fd.append('category',             currentCategory);
  fd.append('reply_consent',        'true');

  const selectedTools = [...document.querySelectorAll('input[name="tool"]:checked')].map(cb => cb.value);
  if (selectedTools.length > 0) {
    fd.append('tools', selectedTools.join(', '));
  }

  for (const f of manualFiles) {
    fd.append('attachments', f);
  }

  try {
    const resp = await fetch(`${API}/api/contact`, { method: 'POST', headers: { 'X-CSRFToken': csrfToken() }, body: fd });
    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(body.detail || `Server error (${resp.status})`);
    }
    form.style.display = 'none';
    successMsg.classList.add('visible');
  } catch (err) {
    showError(err.message || 'Failed to send message. Please try again or email support@vrftools.com directly.');
    btnSubmit.disabled = false;
    submitStatus.style.display = 'none';
  }
});

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.add('visible');
}
