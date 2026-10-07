
// Served locally: browsers block module workers loaded from another origin.
import { FFmpeg } from '../vendor/ffmpeg/index.js';
import { fetchFile, toBlobURL } from 'https://cdn.jsdelivr.net/npm/@ffmpeg/util@0.12.1/dist/esm/index.js';

const $ = s => document.querySelector(s);
const pageTool = document.body.dataset.tool || '';
const statusEl = $('#toolStatus');
const liveRegion = $('#toolLive');
const progressWrap = $('#progressWrap');
const progressBar = $('#progressBar');
const progressText = $('#progressText');
const resultPanel = $('#resultPanel');
const resultLink = $('#resultLink');
const fileInput = $('#fileInput');
const uploadZone = $('#uploadZone');
const fileSummary = $('#fileSummary');
const fileNameEl = $('#fileName');
const fileSizeEl = $('#fileSize');
const videoPreview = $('#videoPreview');
const previewEl = $('#previewVideo');
let selectedFile = null;
let ffmpeg = null;
let loaded = false;

function setStatus(msg, type='') {
  if (!statusEl) return;
  statusEl.textContent = msg;
  statusEl.className = 'status-msg' + (type ? ' ' + type : '');
  if (liveRegion) liveRegion.textContent = msg;
}

function bytes(n) {
  if (!Number.isFinite(n)) return '';
  const u = ['B','KB','MB','GB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}

async function ensureFFmpeg() {
  if (loaded) return ffmpeg;
  setStatus('Loading the browser video engine…');
  ffmpeg = new FFmpeg();
  ffmpeg.on('progress', ({ progress }) => {
    const p = Math.max(0, Math.min(100, Math.round(progress * 100)));
    if (progressWrap) progressWrap.classList.add('show');
    if (progressBar) progressBar.style.width = `${p}%`;
    if (progressText) progressText.textContent = `${p}%`;
  });
  // The ESM build is required: the module worker cannot importScripts() the UMD build.
  const baseURL = 'https://unpkg.com/@ffmpeg/core@0.12.6/dist/esm';
  await ffmpeg.load({
    coreURL: await toBlobURL(`${baseURL}/ffmpeg-core.js`, 'text/javascript'),
    wasmURL: await toBlobURL(`${baseURL}/ffmpeg-core.wasm`, 'application/wasm')
  });
  loaded = true;
  setStatus('Video engine ready.', 'success');
  return ffmpeg;
}

function showFile(file) {
  selectedFile = file;
  if (fileSummary) fileSummary.classList.add('show');
  if (fileNameEl) fileNameEl.textContent = file.name;
  if (fileSizeEl) fileSizeEl.textContent = bytes(file.size);
  if (videoPreview && previewEl && file.type.startsWith('video/')) {
    const old = previewEl.dataset.objectUrl;
    if (old) URL.revokeObjectURL(old);
    const url = URL.createObjectURL(file);
    previewEl.src = url;
    previewEl.dataset.objectUrl = url;
    videoPreview.classList.add('show');
  }
  setStatus('File selected. Choose your settings and start processing.');
}

if (uploadZone && fileInput) {
  uploadZone.addEventListener('click', () => fileInput.click());
  uploadZone.addEventListener('keydown', e => {
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); fileInput.click(); }
  });
  ['dragenter','dragover'].forEach(type => uploadZone.addEventListener(type, e => {
    e.preventDefault(); uploadZone.classList.add('dragover');
  }));
  ['dragleave','drop'].forEach(type => uploadZone.addEventListener(type, e => {
    e.preventDefault(); uploadZone.classList.remove('dragover');
  }));
  uploadZone.addEventListener('drop', e => {
    const f = e.dataTransfer.files?.[0];
    if (f) showFile(f);
  });
  fileInput.addEventListener('change', () => {
    const f = fileInput.files?.[0];
    if (f) showFile(f);
  });
}

async function saveOutput(name, mime='application/octet-stream') {
  const data = await ffmpeg.readFile(name);
  const blob = new Blob([data.buffer], { type: mime });
  const url = URL.createObjectURL(blob);
  if (resultPanel) resultPanel.classList.add('show');
  if (resultLink) {
    resultLink.href = url;
    resultLink.download = name;
  }
  setStatus('Your file is ready.', 'success');
}

async function processFile() {
  if (!selectedFile) {
    setStatus('Choose a video file first.', 'error');
    fileInput?.focus();
    return;
  }
  const startBtn = $('#processBtn');
  if (startBtn) startBtn.disabled = true;
  if (resultPanel) resultPanel.classList.remove('show');
  if (progressWrap) progressWrap.classList.add('show');
  if (progressBar) progressBar.style.width = '0%';
  try {
    await ensureFFmpeg();
    const inputExt = (selectedFile.name.split('.').pop() || 'mp4').replace(/[^a-z0-9]/gi,'').toLowerCase();
    const inputName = `input.${inputExt || 'mp4'}`;
    await ffmpeg.writeFile(inputName, await fetchFile(selectedFile));

    if (pageTool === 'compress') {
      const preset = $('#compressionPreset')?.value || 'balanced';
      const resolution = $('#resolution')?.value || 'original';
      let crf = '28';
      if (preset === 'small') crf = '32';
      if (preset === 'quality') crf = '23';
      const output = 'compressed-video.mp4';
      const args = ['-i', inputName];
      if (resolution !== 'original') args.push('-vf', `scale=-2:${resolution}`);
      args.push('-c:v','libx264','-crf',crf,'-preset','veryfast','-c:a','aac','-b:a','128k',output);
      setStatus('Compressing video in your browser…');
      await ffmpeg.exec(args);
      await saveOutput(output, 'video/mp4');
    }

    if (pageTool === 'convert') {
      const format = $('#outputFormat')?.value || 'mp4';
      let output = `converted-video.${format}`;
      let args = ['-i', inputName];
      let mime = 'video/mp4';
      if (format === 'mp4') {
        args.push('-c:v','libx264','-preset','veryfast','-crf','25','-c:a','aac',output);
        mime = 'video/mp4';
      } else if (format === 'webm') {
        args.push('-c:v','libvpx-vp9','-b:v','0','-crf','34','-c:a','libopus',output);
        mime = 'video/webm';
      } else if (format === 'gif') {
        args.push('-vf','fps=12,scale=720:-1:flags=lanczos',output);
        mime = 'image/gif';
      } else if (format === 'mp3') {
        output = 'audio.mp3';
        args.push('-vn','-c:a','libmp3lame','-b:a','192k',output);
        mime = 'audio/mpeg';
      }
      setStatus(`Converting video to ${format.toUpperCase()}…`);
      await ffmpeg.exec(args);
      await saveOutput(output, mime);
    }

    if (pageTool === 'trim') {
      const start = $('#startTime')?.value?.trim() || '00:00:00';
      const end = $('#endTime')?.value?.trim() || '';
      const output = 'trimmed-video.mp4';
      // -to must also be an input option: after input seeking, an output -to counts from the new start.
      const args = ['-ss', start];
      if (end) args.push('-to', end);
      args.push('-i', inputName,'-c:v','libx264','-preset','veryfast','-crf','24','-c:a','aac',output);
      setStatus('Trimming video in your browser…');
      await ffmpeg.exec(args);
      await saveOutput(output, 'video/mp4');
    }
  } catch (err) {
    console.error(err);
    setStatus('Processing failed on this browser or file. Try a smaller video or another common format such as MP4.', 'error');
  } finally {
    if (startBtn) startBtn.disabled = false;
  }
}

$('#processBtn')?.addEventListener('click', processFile);

async function handleDirectDownload() {
  const input = $('#directUrl');
  const btn = $('#downloadDirectBtn');
  const openBtn = $('#openSourceBtn');
  const status = $('#downloadStatus');
  if (!input || !btn) return;
  const value = input.value.trim();
  if (!value) { input.focus(); return; }
  let url;
  try { url = new URL(value); } catch {
    status.textContent = 'Enter a valid URL.';
    status.className = 'status-msg error';
    return;
  }
  if (!/^https?:$/.test(url.protocol)) {
    status.textContent = 'Only http and https URLs are supported.';
    status.className = 'status-msg error';
    return;
  }
  openBtn.href = url.href;
  openBtn.hidden = false;
  btn.disabled = true;
  status.textContent = 'Trying to fetch the media file directly…';
  status.className = 'status-msg';
  try {
    const res = await fetch(url.href, { mode:'cors' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const type = res.headers.get('content-type') || '';
    if (!type.startsWith('video/') && !type.startsWith('audio/') && !url.pathname.match(/\.(mp4|webm|mov|m4v|mp3|wav|ogg)$/i)) {
      throw new Error('Not a direct media file');
    }
    const blob = await res.blob();
    const objectUrl = URL.createObjectURL(blob);
    const name = url.pathname.split('/').pop() || 'video';
    const a = document.createElement('a');
    a.href = objectUrl;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
    status.textContent = 'Download started.';
    status.className = 'status-msg success';
  } catch (err) {
    status.textContent = 'This host blocks direct browser downloads or the URL is not a direct media file. You can open the source instead.';
    status.className = 'status-msg error';
  } finally {
    btn.disabled = false;
  }
}

$('#downloadDirectBtn')?.addEventListener('click', handleDirectDownload);

if (pageTool === 'download') {
  const params = new URLSearchParams(location.search);
  const prefill = params.get('url');
  if (prefill && $('#directUrl')) $('#directUrl').value = prefill;
}
