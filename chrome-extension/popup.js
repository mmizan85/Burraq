'use strict';

const DEFAULT_SERVER_URL = 'http://localhost:9090';
const DOWNLOAD_MESSAGE = 'QUEUE_DEVICE_DOWNLOAD';
const ACTIVE_TASK_KEY = 'pf_active_task_id';

// Dynamic server URL - will be loaded from settings
let SERVER_URL = DEFAULT_SERVER_URL;

const VQ = [
  ['Best', 'best', 'Auto'],
  ['4K', '2160p', '2160p'],
  ['2K', '1440p', '1440p'],
  ['1080p', '1080p', 'Full HD'],
  ['720p', '720p', 'HD'],
  ['480p', '480p', 'SD'],
  ['360p', '360p', 'Low'],
  ['240p', '240p', 'Min'],
  ['F-Phone', 'F-video', 'Feature Phone'],
];

const AQ = [
  ['Best', 'best', 'Auto'],
  ['320k', '320', 'Lossless'],
  ['256k', '256', 'Hi-Fi'],
  ['192k', '192', 'Standard'],
  ['128k', '128', 'Economy'],
];

const VF = [
  ['MP4', 'mp4', 'H.264'],
  ['MKV', 'mkv', 'Matroska'],
  ['WebM', 'webm', 'VP9'],
  ['MOV', 'mov', 'QuickTime'],
  ['AVI', 'avi', 'Legacy'],
];

const AF = [
  ['MP3', 'mp3', 'Universal'],
  ['M4A', 'm4a', 'Apple AAC'],
  ['FLAC', 'flac', 'Lossless'],
  ['OPUS', 'opus', 'Best ratio'],
  ['WAV', 'wav', 'Uncompressed'],
  ['AAC', 'aac', 'AAC raw'],
];

const DEFAULT_SETTINGS = {
  embedMetadata: true,
  downloadSubtitles: false,
  defaultQuality: '1080p',
  legacyMode: false,
};

const S = {
  online: false,
  type: 'video',
  qualityIdx: 3,
  formatIdx: 0,
  qList: VQ,
  fList: VF,
  playlist: 'single',
  url: '',
  title: '',
  duration: '',
  isPlaylist: false,
  busy: false,
  manualInput: false,
  statusTimer: 0,
  activeTaskId: '',
  settings: { ...DEFAULT_SETTINGS },
  canvas: {
    rafId: 0,
    ctx: null,
    canvas: null,
    nodes: [],
    running: false,
    inactivityTimer: 0,
  },
};

const $ = id => document.getElementById(id);
const el = {
  scDot: () => $('scDot'),
  scTxt: () => $('scTxt'),
  errStrip: () => $('errStrip'),
  errTxt: () => $('errTxt'),
  errX: () => $('errX'),
  mediaCard: () => $('mediaCard'),
  mcThumb: () => $('mcThumb'),
  mcTitle: () => $('mcTitle'),
  mcHost: () => $('mcHost'),
  mcDuration: () => $('mcDuration'),
  mcBadge: () => $('mcBadge'),
  urlIn: () => $('urlIn'),
  pasteBtn: () => $('pasteBtn'),
  clearBtn: () => $('clearBtn'),
  reviewBtn: () => $('reviewBtn'),
  plBlock: () => $('plBlock'),
  plSeg: () => $('plSeg'),
  qPrev: () => $('qPrev'),
  qNext: () => $('qNext'),
  qVal: () => $('qVal'),
  qSub: () => $('qSub'),
  fPrev: () => $('fPrev'),
  fNext: () => $('fNext'),
  fVal: () => $('fVal'),
  fSub: () => $('fSub'),
  dlBtn: () => $('dlBtn'),
  dlContent: () => $('dlContent'),
  folderBtn: () => $('folderBtn'),
  settingsBtn: () => $('settingsBtn'),
  fsYtdlp: () => $('fsYtdlp'),
  fsQueue: () => $('fsQueue'),
  fsActive: () => $('fsActive'),
  fsDot: () => $('fsDot'),
  statusDock: () => $('statusDock'),
  statusTxt: () => $('statusTxt'),
  statusFill: () => $('statusFill'),
  toast: () => $('toast'),
  toastIco: () => $('toastIco'),
  toastMsg: () => $('toastMsg'),
};

// Get server URL from settings
async function getServerUrl() {
  const settings = await storageGetSync(['serverUrl']);
  return settings.serverUrl || DEFAULT_SERVER_URL;
}

// Get API endpoints based on server URL
function getEndpoints() {
  return {
    health: `${SERVER_URL}/health`,
    info: `${SERVER_URL}/get-info`,
    status: `${SERVER_URL}/status`,
    openFolder: `${SERVER_URL}/open-folder`,
  };
}

document.addEventListener('DOMContentLoaded', async () => {
  initCanvas();
  wireEvents();
  await loadPrefs();
  renderDials();
  // Load server URL from settings
  SERVER_URL = await getServerUrl();
  await Promise.all([pingServer(), detectPage(), restoreActiveTask()]);
  setInterval(pingServer, 9090);
});

function initCanvas() {
  const canvas = $('bgCanvas');
  const ctx = canvas.getContext('2d');
  canvas.width = 370;
  canvas.height = 560;

  S.canvas.canvas = canvas;
  S.canvas.ctx = ctx;
  S.canvas.nodes = Array.from({ length: 28 }, () => ({
    x: Math.random() * canvas.width,
    y: Math.random() * canvas.height,
    vx: (Math.random() - 0.5) * 0.35,
    vy: (Math.random() - 0.5) * 0.35,
    r: Math.random() * 1.8 + 0.6,
  }));

  const resume = () => {
    if (document.hidden) {
      return;
    }
    startCanvas();
    scheduleCanvasIdlePause();
  };

  canvas.addEventListener('mouseenter', resume);
  document.addEventListener('mousemove', resume, { passive: true });
  document.addEventListener('pointerdown', resume, { passive: true });
  window.addEventListener('focus', resume);
  window.addEventListener('blur', stopCanvas);
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) {
      stopCanvas();
    } else {
      resume();
    }
  });
  document.body.addEventListener('mouseleave', stopCanvas);

  startCanvas();
  scheduleCanvasIdlePause();
}

function startCanvas() {
  if (S.canvas.running || !S.canvas.ctx || !S.canvas.canvas) {
    return;
  }
  S.canvas.running = true;

  const draw = () => {
    if (!S.canvas.running) {
      return;
    }

    const { ctx, canvas, nodes } = S.canvas;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    for (const node of nodes) {
      node.x += node.vx;
      node.y += node.vy;
      if (node.x < 0 || node.x > canvas.width) {
        node.vx *= -1;
      }
      if (node.y < 0 || node.y > canvas.height) {
        node.vy *= -1;
      }
    }

    for (let i = 0; i < nodes.length; i += 1) {
      for (let j = i + 1; j < nodes.length; j += 1) {
        const dx = nodes[i].x - nodes[j].x;
        const dy = nodes[i].y - nodes[j].y;
        const distance = Math.sqrt(dx * dx + dy * dy);
        if (distance < 90) {
          ctx.beginPath();
          ctx.strokeStyle = `rgba(0,255,180,${(1 - distance / 90) * 0.18})`;
          ctx.lineWidth = 0.6;
          ctx.moveTo(nodes[i].x, nodes[i].y);
          ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.stroke();
        }
      }
    }

    for (const node of nodes) {
      ctx.beginPath();
      ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(0,255,180,0.45)';
      ctx.fill();
    }

    S.canvas.rafId = requestAnimationFrame(draw);
  };

  S.canvas.rafId = requestAnimationFrame(draw);
}

function stopCanvas() {
  S.canvas.running = false;
  if (S.canvas.rafId) {
    cancelAnimationFrame(S.canvas.rafId);
    S.canvas.rafId = 0;
  }
  if (S.canvas.inactivityTimer) {
    clearTimeout(S.canvas.inactivityTimer);
    S.canvas.inactivityTimer = 0;
  }
}

function scheduleCanvasIdlePause() {
  if (S.canvas.inactivityTimer) {
    clearTimeout(S.canvas.inactivityTimer);
  }
  S.canvas.inactivityTimer = setTimeout(stopCanvas, 12000);
}

async function pingServer() {
  el.scDot().className = 'sc-dot checking';
  el.scTxt().textContent = 'PINGING';

  try {
    const res = await fetch(`${SERVER_URL}/health`, { signal: AbortSignal.timeout(3000) });
    const data = await res.json();

    S.online = res.ok;
    if (!res.ok) {
      throw new Error('offline');
    }

    el.scDot().className = 'sc-dot online';
    el.scTxt().textContent = 'ONLINE';
    el.fsYtdlp().textContent = `yt-dlp ${data.ytdlp_version || '?'}`;
    el.fsQueue().textContent = String(data.queue_size ?? '0');
    el.fsActive().textContent = String(data.active_downloads ?? '0');
    el.fsDot().style.background = 'var(--bio)';
  } catch {
    S.online = false;
    el.scDot().className = 'sc-dot offline';
    el.scTxt().textContent = 'OFFLINE';
    el.fsDot().style.background = 'var(--danger)';
    showErr('Server offline - run: Burraq');
  }
}

async function detectPage() {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url) {
      return;
    }

    if (
      tab.url.startsWith('chrome://') ||
      tab.url.startsWith('about:') ||
      tab.url.startsWith('chrome-extension://')
    ) {
      showErr('Navigate to a supported media page to detect content.');
      return;
    }

    let info = null;
    try {
      info = await chrome.tabs.sendMessage(tab.id, { type: 'GET_PAGE_INFO' });
    } catch {
      info = fallbackInfo(tab);
    }

    applyInfo(info || fallbackInfo(tab));
  } catch (error) {
    showErr(`Could not detect page: ${error.message}`);
  }
}

function fallbackInfo(tab) {
  const url = tab.url || '';
  let host = '';
  let isPlaylist = false;
  try {
    const parsed = new URL(url);
    host = parsed.hostname.replace(/^www\./, '');
    isPlaylist =
      parsed.searchParams.has('list') || /playlist/i.test(parsed.pathname + parsed.search);
  } catch {
    host = '';
  }

  return {
    url,
    host,
    title: (tab.title || 'Untitled').replace(/\s*[-|].*YouTube.*$/i, '').trim(),
    thumbnail: null,
    siteName: guessSiteName(host),
    isPlaylist,
  };
}

function applyInfo(info) {
  if (!info || S.manualInput) {
    return;
  }

  S.url = info.url || '';
  S.title = info.title || 'Untitled';
  S.isPlaylist = Boolean(info.isPlaylist);
  el.urlIn().value = S.url;

  updatePlaylistVisibility(S.url, S.isPlaylist);
  renderMediaCard({
    title: S.title,
    host: info.host || '',
    duration: info.duration_string || formatDuration(info.duration),
    badge: (info.siteName || 'WEB').toUpperCase().slice(0, 12),
    thumbnail: info.thumbnail || '',
  });
}

function wireEvents() {
  el.errX().addEventListener('click', hideErr);
  el.reviewBtn().addEventListener('click', handleReview);
  el.pasteBtn().addEventListener('click', handlePaste);
  el.clearBtn().addEventListener('click', clearInput);
  el.dlBtn().addEventListener('click', handleDownload);
  el.folderBtn().addEventListener('click', handleOpenFolder);
  el.settingsBtn().addEventListener('click', () => chrome.runtime.openOptionsPage());

  el.urlIn().addEventListener('input', () => {
    S.url = el.urlIn().value.trim();
    S.manualInput = true;
    updatePlaylistVisibility(S.url);
  });

  el.plSeg()
    .querySelectorAll('.seg-pill')
    .forEach(btn => {
      btn.addEventListener('click', () => {
        el.plSeg()
          .querySelectorAll('.seg-pill')
          .forEach(node => node.classList.remove('active'));
        btn.classList.add('active');
        S.playlist = btn.dataset.val;
      });
    });

  document.querySelectorAll('.type-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.type-pill').forEach(node => {
        node.classList.toggle('active', node === btn);
      });

      S.type = btn.dataset.type;
      if (S.type === 'audio') {
        S.qList = AQ;
        S.fList = AF;
        S.qualityIdx = 0;
        S.formatIdx = 0;
      } else {
        S.qList = VQ;
        S.fList = VF;
        S.qualityIdx = getQualityIndexFromValue(S.settings.defaultQuality);
        S.formatIdx = 0;
      }

      renderDials();
      savePrefs();
    });
  });

  el.qPrev().addEventListener('click', () => nudge('q', -1));
  el.qNext().addEventListener('click', () => nudge('q', 1));
  el.fPrev().addEventListener('click', () => nudge('f', -1));
  el.fNext().addEventListener('click', () => nudge('f', 1));
}

function nudge(axis, delta) {
  if (axis === 'q') {
    S.qualityIdx = (S.qualityIdx + delta + S.qList.length) % S.qList.length;
  } else {
    S.formatIdx = (S.formatIdx + delta + S.fList.length) % S.fList.length;
  }
  renderDials();
  savePrefs();
}

function renderDials() {
  const q = S.qList[S.qualityIdx];
  const f = S.fList[S.formatIdx];
  el.qVal().textContent = q[0];
  el.qSub().textContent = q[2];
  el.fVal().textContent = f[0];
  el.fSub().textContent = f[2];
}

async function handleReview() {
  hideErr();

  const raw = el.urlIn().value.trim();
  if (!raw) {
    showErr('Please paste or type a valid URL first.');
    return;
  }

  if (!isValidUrl(raw)) {
    showErr('Invalid URL format. Must start with http:// or https://');
    return;
  }

  S.url = raw;
  S.manualInput = true;
  updatePlaylistVisibility(raw);

  if (!S.online) {
    renderFallbackCard(raw);
    showErr('Server offline - metadata preview is unavailable.');
    return;
  }

  el.reviewBtn().disabled = true;
  el.reviewBtn().classList.add('loading');

  try {
    const res = await fetch(`${SERVER_URL}/get-info`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url: raw }),
      signal: AbortSignal.timeout(12000),
    });

    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || `Server ${res.status}`);
    }

    S.title = data.title || 'Untitled';
    S.duration = data.duration_string || formatDuration(data.duration);
    S.isPlaylist = Boolean(data.is_playlist) || hasPlaylistHint(raw);
    updatePlaylistVisibility(raw, S.isPlaylist);

    renderMediaCard({
      title: S.title,
      host: safeHost(raw),
      duration: S.duration,
      badge: (data.extractor || guessSiteName(safeHost(raw)) || 'WEB')
        .toUpperCase()
        .slice(0, 12),
      thumbnail: data.thumbnail || '',
    });

    toast('Live metadata loaded', 'INFO');
  } catch (error) {
    renderFallbackCard(raw);
    showErr(error.name === 'TimeoutError' ? 'Metadata lookup timed out.' : error.message);
  } finally {
    el.reviewBtn().disabled = false;
    el.reviewBtn().classList.remove('loading');
  }
}

async function handleDownload() {
  hideErr();

  const url = el.urlIn().value.trim();
  if (!url) {
    showErr('Enter or auto-detect a media URL first.');
    return;
  }

  if (!S.online) {
    showErr('Server is offline. Run: Burraq');
    return;
  }

  if (S.busy) {
    return;
  }

  const qEntry = S.qList[S.qualityIdx];
  const fEntry = S.fList[S.formatIdx];
  const payload = {
    url,
    title: S.title || 'Untitled',
    download_type: S.type,
    is_playlist: S.isPlaylist && S.playlist === 'playlist',
    quality: qEntry[1],
    format: fEntry[1],
  };

  setBusy(true);

  try {
    const result = await sendRuntimeMessage({
      type: DOWNLOAD_MESSAGE,
      payload,
    });

    if (!result?.ok) {
      throw new Error(result?.error || 'Unable to queue the download.');
    }

    S.activeTaskId = result.taskId || '';
    if (S.activeTaskId) {
      await storageSetLocal({ [ACTIVE_TASK_KEY]: S.activeTaskId });
      startStatusPolling(S.activeTaskId);
    }

    el.dlContent().textContent = `QUEUED [${result.taskId || '--'}]`;
    toast(`Queued: ${(S.title || 'Untitled').slice(0, 34)}`, 'OK');
    setTimeout(() => pingServer(), 600);

    setTimeout(() => {
      setBusy(false);
      resetDownloadButton();
    }, 1800);
  } catch (error) {
    setBusy(false);
    resetDownloadButton();
    showErr(error.message);
    toast(error.message, 'ERR');
  }
}

async function handlePaste() {
  try {
    const value = (await navigator.clipboard.readText()).trim();
    if (!value) {
      return;
    }
    el.urlIn().value = value;
    S.url = value;
    S.manualInput = true;
    updatePlaylistVisibility(value);
    toast('URL pasted', 'OK');
  } catch {
    toast('Clipboard access denied', 'ERR');
  }
}

function clearInput() {
  el.urlIn().value = '';
  S.url = '';
  S.title = '';
  S.duration = '';
  S.manualInput = false;
  S.isPlaylist = false;
  el.mediaCard().style.display = 'none';
  updatePlaylistVisibility('');
}

async function handleOpenFolder() {
  if (!S.online) {
    showErr('Server is offline. Cannot open the download folder.');
    return;
  }

  try {
    const res = await fetch(`${SERVER_URL}/open-folder`, {
      method: 'POST',
      signal: AbortSignal.timeout(6000),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || `Server ${res.status}`);
    }
    toast('Download folder opened', 'DIR');
  } catch (error) {
    showErr(error.name === 'TimeoutError' ? 'Open folder request timed out.' : error.message);
  }
}

function setBusy(on) {
  S.busy = on;
  el.dlBtn().disabled = on;
  if (on) {
    el.dlContent().innerHTML = '<span class="spin">↻</span> SENDING...';
  }
}

function resetDownloadButton() {
  el.dlBtn().disabled = false;
  el.dlContent().innerHTML = `
    <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
      <path d="M10 2v11M5 9l5 5 5-5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M2 15v1a2 2 0 002 2h12a2 2 0 002-2v-1" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
    </svg>
    SEND TO Burraq
  `;
}

function renderMediaCard({ title, host, duration, badge, thumbnail }) {
  el.mediaCard().style.display = 'flex';
  el.mediaCard().classList.add('refreshing');
  setTimeout(() => el.mediaCard().classList.remove('refreshing'), 400);

  el.mcTitle().textContent = (title || 'Untitled').slice(0, 88);
  el.mcHost().textContent = host || 'Unknown source';
  el.mcDuration().textContent = duration ? `• ${duration}` : '';
  el.mcBadge().textContent = badge || 'WEB';

  if (thumbnail) {
    el.mcThumb().style.display = 'block';
    el.mcThumb().src = thumbnail;
  } else {
    el.mcThumb().style.display = 'none';
    el.mcThumb().removeAttribute('src');
  }
}

function renderFallbackCard(url) {
  renderMediaCard({
    title: guessSiteName(safeHost(url)) + ' Media',
    host: safeHost(url),
    duration: '',
    badge: guessSiteName(safeHost(url)).toUpperCase().slice(0, 12),
    thumbnail: '',
  });
}

function updatePlaylistVisibility(url, forced = null) {
  const show = typeof forced === 'boolean' ? forced : hasPlaylistHint(url);
  S.isPlaylist = show;
  el.plBlock().style.display = show ? 'flex' : 'none';
  if (!show) {
    S.playlist = 'single';
    el.plSeg()
      .querySelectorAll('.seg-pill')
      .forEach(btn => btn.classList.toggle('active', btn.dataset.val === 'single'));
  }
}

function hasPlaylistHint(url) {
  return /(?:[?&]list=|playlist)/i.test(url || '');
}

function formatDuration(value) {
  const total = Number(value);
  if (!Number.isFinite(total) || total <= 0) {
    return '';
  }
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = Math.floor(total % 60);
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
  }
  return `${minutes}:${String(seconds).padStart(2, '0')}`;
}

function showErr(msg) {
  el.errTxt().textContent = msg;
  el.errStrip().style.display = 'flex';
}

function hideErr() {
  el.errStrip().style.display = 'none';
}

let toastTimer = 0;
function toast(message, icon = 'OK') {
  el.toastIco().textContent = icon;
  el.toastMsg().textContent = message;
  el.toast().classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.toast().classList.remove('show'), 3200);
}

async function savePrefs() {
  await storageSetSync({
    pf_type: S.type,
    pf_qi: S.qualityIdx,
    pf_fi: S.formatIdx,
  });
}

async function loadPrefs() {
  const [syncData, localData] = await Promise.all([
    storageGetSync(['pf_type', 'pf_qi', 'pf_fi']),
    storageGetLocal([
      'embedMetadata',
      'downloadSubtitles',
      'defaultQuality',
      'legacyMode',
    ]),
  ]);

  S.settings = {
    embedMetadata:
      typeof localData.embedMetadata === 'boolean'
        ? localData.embedMetadata
        : DEFAULT_SETTINGS.embedMetadata,
    downloadSubtitles:
      typeof localData.downloadSubtitles === 'boolean'
        ? localData.downloadSubtitles
        : DEFAULT_SETTINGS.downloadSubtitles,
    defaultQuality:
      typeof localData.defaultQuality === 'string' && localData.defaultQuality
        ? localData.defaultQuality
        : DEFAULT_SETTINGS.defaultQuality,
    legacyMode:
      typeof localData.legacyMode === 'boolean'
        ? localData.legacyMode
        : DEFAULT_SETTINGS.legacyMode,
  };

  if (syncData.pf_type) {
    S.type = syncData.pf_type;
  }
  S.qList = S.type === 'audio' ? AQ : VQ;
  S.fList = S.type === 'audio' ? AF : VF;
  S.qualityIdx =
    syncData.pf_qi !== undefined
      ? syncData.pf_qi
      : S.type === 'audio'
        ? 0
        : getQualityIndexFromValue(S.settings.defaultQuality);
  S.formatIdx = syncData.pf_fi !== undefined ? syncData.pf_fi : 0;

  document.querySelectorAll('.type-pill').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.type === S.type);
  });
}

function getQualityIndexFromValue(value) {
  const index = VQ.findIndex(item => item[1] === value);
  return index >= 0 ? index : 3;
}

async function restoreActiveTask() {
  const data = await storageGetLocal([ACTIVE_TASK_KEY]);
  const taskId = data[ACTIVE_TASK_KEY];
  if (typeof taskId === 'string' && taskId) {
    S.activeTaskId = taskId;
    startStatusPolling(taskId);
  }
}

function startStatusPolling(taskId) {
  stopStatusPolling();
  S.activeTaskId = taskId;
  updateStatusUi('Linking to task...', 4);
  pollTaskStatus();
  S.statusTimer = setInterval(pollTaskStatus, 2000);
}

function stopStatusPolling(clearTask = true) {
  if (S.statusTimer) {
    clearInterval(S.statusTimer);
    S.statusTimer = 0;
  }
  if (clearTask) {
    S.activeTaskId = '';
    storageRemoveLocal([ACTIVE_TASK_KEY]);
  }
}

async function pollTaskStatus() {
  if (!S.activeTaskId) {
    return;
  }

  try {
    const res = await fetch(`${SERVER_URL}/status?task_id=${encodeURIComponent(S.activeTaskId)}`, {
      signal: AbortSignal.timeout(5000),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || `Server ${res.status}`);
    }

    const task = data.task;
    if (!task) {
      updateStatusUi('Waiting for task state...', 6);
      return;
    }

    const progress = Number(task.progress || 0);
    const status = task.status || 'Queued';
    const detail =
      status === 'Downloading'
        ? `Downloading... ${Math.round(progress)}%`
        : status === 'Processing'
          ? 'Processing media...'
          : status === 'Completed'
            ? 'Completed'
            : status === 'Failed'
              ? `Failed: ${task.error || 'Unknown error'}`
              : status;

    updateStatusUi(detail, progress);

    if (status === 'Completed' || status === 'Failed' || status === 'Cancelled') {
      stopStatusPolling(true);
      setTimeout(() => {
        updateStatusUi(status === 'Completed' ? 'Ready for next task' : detail, status === 'Completed' ? 100 : 0);
      }, 1600);
    }
  } catch {
    updateStatusUi('Status sync paused', 0);
  }
}

function updateStatusUi(message, progress = 0) {
  el.statusDock().style.display = 'flex';
  el.statusTxt().textContent = message;
  el.statusFill().style.width = `${Math.max(0, Math.min(100, progress))}%`;
}

function guessSiteName(host) {
  const map = {
    'youtube.com': 'YouTube',
    'youtu.be': 'YouTube',
    'vimeo.com': 'Vimeo',
    'twitch.tv': 'Twitch',
    'twitter.com': 'X',
    'x.com': 'X',
    'tiktok.com': 'TikTok',
    'reddit.com': 'Reddit',
    'instagram.com': 'Instagram',
    'facebook.com': 'Facebook',
    'soundcloud.com': 'SoundCloud',
    'bandcamp.com': 'Bandcamp',
  };

  for (const [key, value] of Object.entries(map)) {
    if ((host || '').includes(key)) {
      return value;
    }
  }

  const segment = (host || 'web').split('.')[0];
  return segment.charAt(0).toUpperCase() + segment.slice(1);
}

function safeHost(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return '';
  }
}

function isValidUrl(value) {
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:';
  } catch {
    return false;
  }
}

function sendRuntimeMessage(message) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(message, response => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      resolve(response);
    });
  });
}

function storageGetLocal(keys) {
  return new Promise(resolve => chrome.storage.local.get(keys, resolve));
}

function storageSetLocal(value) {
  return new Promise(resolve => chrome.storage.local.set(value, resolve));
}

function storageRemoveLocal(keys) {
  return new Promise(resolve => chrome.storage.local.remove(keys, resolve));
}

function storageGetSync(keys) {
  return new Promise(resolve => chrome.storage.sync.get(keys, resolve));
}

function storageSetSync(value) {
  return new Promise(resolve => chrome.storage.sync.set(value, resolve));
}
