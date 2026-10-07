const $ = (selector) => document.querySelector(selector);

const input = $('#directUrl');
const analyzeBtn = $('#analyzeBtn');
const statusEl = $('#downloadStatus');
const liveEl = $('#toolLive');
const analysisResult = $('#analysisResult');
const mediaSummary = $('.media-summary');
const mediaTitle = $('#mediaTitle');
const mediaMeta = $('#mediaMeta');
const thumbnail = $('#mediaThumbnail');
const formatList = $('#formatList');
const downloadJob = $('#downloadJob');
const jobLabel = $('#jobLabel');
const jobProgress = $('#jobProgress');
const progressBar = $('#serverProgressBar');
const jobMessage = $('#jobMessage');
const jobStats = $('#jobStats');
const jobPercent = $('#jobPercent');
const jobReady = $('#jobReady');
const jobDownloadLink = $('#jobDownloadLink');

const POLL_MS = 800;
const MAX_POLL_FAILURES = 4;

let currentUrl = '';
let pollTimer = null;
// Bumped whenever a new analysis or download starts so stale polls stop updating the UI.
let activeToken = 0;

function setStatus(message, type = '') {
  statusEl.textContent = message;
  statusEl.className = `status-msg${type ? ` ${type}` : ''}`;
}

function announce(message) {
  if (liveEl) liveEl.textContent = message;
}

function humanBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '';
  const units = ['B', 'KB', 'MB', 'GB'];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(i ? 1 : 0)} ${units[i]}`;
}

function humanDuration(seconds) {
  if (!Number.isFinite(seconds) || seconds <= 0) return '';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h ? `${h}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}` : `${m}:${String(s).padStart(2,'0')}`;
}

function normalizeUrl(value) {
  const trimmed = value.trim();
  if (!trimmed) return '';
  // People often paste "youtube.com/watch?v=…" without the scheme.
  return /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {'Content-Type': 'application/json', ...(options.headers || {})},
    ...options,
  });
  let data = {};
  try { data = await response.json(); } catch {}
  if (!response.ok) {
    const error = new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  return data;
}

function setFormatButtonsDisabled(disabled) {
  document.querySelectorAll('.format-download').forEach(btn => { btn.disabled = disabled; });
}

function formatDetails(item) {
  const bits = [];
  if (item.width && item.height) bits.push(`${item.width}×${item.height}`);
  if (item.fps > 30) bits.push(`${item.fps} fps`);
  const codec = item.audio_only ? item.acodec : item.vcodec;
  const ext = (item.ext || 'media').toUpperCase();
  bits.push(codec ? `${ext} (${codec})` : ext);
  const size = humanBytes(item.filesize);
  if (size) bits.push(item.video_only ? `${size} + audio` : size);
  return bits.join(' · ');
}

function formatRow(item) {
  const row = document.createElement('div');
  row.className = 'server-format-row';

  const badge = document.createElement('span');
  badge.className = `file-icon ${item.audio_only ? 'q3' : 'q1'}`;
  badge.textContent = (item.ext || 'media').toUpperCase().slice(0, 4);

  const info = document.createElement('div');
  const title = document.createElement('b');
  title.textContent = item.label || 'Media';
  const small = document.createElement('small');
  small.textContent = formatDetails(item);
  info.append(title, small);

  const button = document.createElement('button');
  button.className = 'btn btn-secondary format-download';
  button.type = 'button';
  button.dataset.format = item.id;
  button.dataset.label = `${item.label || 'Media'} ${(item.ext || '').toUpperCase()}`.trim();
  button.textContent = 'Download';
  button.setAttribute('aria-label', `Download ${button.dataset.label}`);

  row.append(badge, info, button);
  return row;
}

function renderFormats(data) {
  formatList.replaceChildren();
  const groups = [
    ['Video', (data.formats || []).filter(item => !item.audio_only)],
    ['Audio only', (data.formats || []).filter(item => item.audio_only)],
  ];
  for (const [name, items] of groups) {
    if (!items.length) continue;
    const heading = document.createElement('h4');
    heading.className = 'format-group-title';
    heading.textContent = name;
    formatList.appendChild(heading);
    items.forEach(item => formatList.appendChild(formatRow(item)));
  }
}

function stopPolling() {
  activeToken += 1;
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = null;
}

async function analyze() {
  if (analyzeBtn.disabled) return;
  const url = normalizeUrl(input.value);
  if (!url) {
    input.focus();
    setStatus('Paste a link to a video page first.', 'error');
    return;
  }
  input.value = url;
  currentUrl = url;
  stopPolling();
  analysisResult.hidden = true;
  downloadJob.hidden = true;
  analyzeBtn.disabled = true;
  analyzeBtn.classList.add('is-loading');
  analyzeBtn.setAttribute('aria-busy', 'true');
  analyzeBtn.textContent = 'Analyzing…';
  setStatus('Analyzing the media source. This usually takes a few seconds…');
  try {
    const data = await api('/api/analyze', {
      method: 'POST',
      body: JSON.stringify({url}),
    });
    mediaTitle.textContent = data.title || 'Media';
    const duration = humanDuration(data.duration);
    mediaMeta.textContent = [duration, data.extractor ? `Source: ${data.extractor}` : '', `${data.formats?.length || 0} format options`].filter(Boolean).join(' · ');
    if (data.thumbnail) {
      thumbnail.src = data.thumbnail;
      thumbnail.hidden = false;
      mediaSummary.classList.remove('no-thumb');
    } else {
      thumbnail.removeAttribute('src');
      thumbnail.hidden = true;
      mediaSummary.classList.add('no-thumb');
    }
    renderFormats(data);
    setFormatButtonsDisabled(false);
    analysisResult.hidden = false;
    setStatus('Choose a format below.', 'success');
    announce(`Media found: ${data.title || 'Media'}. Choose a format.`);
  } catch (error) {
    setStatus(error.message || 'The media source could not be analyzed.', 'error');
    announce(error.message || 'The media source could not be analyzed.');
  } finally {
    analyzeBtn.disabled = false;
    analyzeBtn.classList.remove('is-loading');
    analyzeBtn.removeAttribute('aria-busy');
    analyzeBtn.textContent = 'Analyze';
  }
}

function setProgress(percent) {
  const value = Math.max(0, Math.min(100, Math.round(percent)));
  progressBar.style.width = `${value}%`;
  jobPercent.textContent = `${value}%`;
  jobProgress.setAttribute('aria-valuenow', String(value));
}

function jobStatsText(data) {
  if (data.status !== 'downloading') return '';
  const parts = [];
  const done = humanBytes(data.downloaded_bytes);
  const total = humanBytes(data.total_bytes);
  if (done && total) parts.push(`${done} of ${total}`);
  const speed = humanBytes(data.speed);
  if (speed) parts.push(`${speed}/s`);
  if (Number.isFinite(data.eta) && data.eta > 0) {
    parts.push(data.eta >= 60 ? `${Math.ceil(data.eta / 60)} min left` : `${Math.round(data.eta)}s left`);
  }
  return parts.join(' · ');
}

function startBrowserDownload(href, filename) {
  const link = document.createElement('a');
  link.href = href;
  link.download = filename || '';
  link.hidden = true;
  document.body.appendChild(link);
  link.click();
  link.remove();
}

async function createDownload(formatId, label) {
  if (!currentUrl) return;
  stopPolling();
  const token = activeToken;
  downloadJob.hidden = false;
  downloadJob.classList.remove('is-error', 'is-ready');
  jobReady.hidden = true;
  jobLabel.textContent = label || 'Download';
  jobStats.textContent = '';
  setProgress(0);
  jobMessage.textContent = 'Starting download…';
  setFormatButtonsDisabled(true);
  downloadJob.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  announce(`Preparing ${label || 'download'}.`);
  try {
    const data = await api('/api/download', {
      method: 'POST',
      body: JSON.stringify({url: currentUrl, format_id: formatId}),
    });
    if (token !== activeToken) return;
    pollJob(data.job_id, token, 0);
  } catch (error) {
    if (token !== activeToken) return;
    failJob(error.message || 'Could not start the download.');
  }
}

function failJob(message) {
  downloadJob.classList.add('is-error');
  jobMessage.textContent = message;
  jobPercent.textContent = 'Failed';
  jobStats.textContent = '';
  setFormatButtonsDisabled(false);
  announce(`Download failed. ${message}`);
}

async function pollJob(jobId, token, failures) {
  if (token !== activeToken) return;
  let data;
  try {
    data = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
  } catch (error) {
    if (token !== activeToken) return;
    // A missing job will not come back; brief network hiccups usually do.
    if (error.status === 404 || failures + 1 >= MAX_POLL_FAILURES) {
      failJob(error.message || 'Could not read the download status.');
      return;
    }
    pollTimer = setTimeout(() => pollJob(jobId, token, failures + 1), POLL_MS * (failures + 2));
    return;
  }
  if (token !== activeToken) return;

  setProgress(Number(data.progress) || 0);
  jobMessage.textContent = data.message || data.status;
  jobStats.textContent = jobStatsText(data);

  if (data.status === 'ready') {
    downloadJob.classList.add('is-ready');
    jobDownloadLink.href = data.download_url;
    jobDownloadLink.setAttribute('download', data.filename || 'media');
    jobDownloadLink.textContent = data.filename ? `Download ${data.filename}` : 'Download finished file';
    const size = humanBytes(data.total_bytes);
    jobStats.textContent = size;
    jobReady.hidden = false;
    setFormatButtonsDisabled(false);
    startBrowserDownload(data.download_url, data.filename);
    announce('Your file is ready and the download has started.');
    return;
  }
  if (data.status === 'error') {
    failJob(data.error || 'The download failed.');
    return;
  }
  pollTimer = setTimeout(() => pollJob(jobId, token, 0), POLL_MS);
}

thumbnail?.addEventListener('error', () => {
  thumbnail.hidden = true;
  mediaSummary.classList.add('no-thumb');
});
analyzeBtn?.addEventListener('click', analyze);
input?.addEventListener('keydown', event => {
  if (event.key === 'Enter') {
    event.preventDefault();
    analyze();
  }
});
document.addEventListener('click', event => {
  const button = event.target.closest('.format-download');
  if (!button || button.disabled) return;
  createDownload(button.dataset.format || 'best', button.dataset.label);
});

const params = new URLSearchParams(location.search);
const initialUrl = params.get('url');
if (initialUrl) {
  input.value = initialUrl;
  analyze();
}
