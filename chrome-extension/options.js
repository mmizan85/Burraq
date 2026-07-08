'use strict';

const DEFAULTS = {
  serverUrl: 'http://localhost:9090',
  embedMetadata: true,
  downloadSubtitles: false,
  defaultQuality: '1080p',
  legacyMode: false,
};

const el = {
  serverUrl: document.getElementById('serverUrl'),
  embedMetadata: document.getElementById('embedMetadata'),
  downloadSubtitles: document.getElementById('downloadSubtitles'),
  defaultQuality: document.getElementById('defaultQuality'),
  legacyMode: document.getElementById('legacyMode'),
  saveBtn: document.getElementById('saveBtn'),
  saveStatus: document.getElementById('saveStatus'),
};

document.addEventListener('DOMContentLoaded', async () => {
  await loadSettings();
  wireEvents();
});

function wireEvents() {
  el.saveBtn.addEventListener('click', saveSettings);
  [el.serverUrl, el.embedMetadata, el.downloadSubtitles, el.defaultQuality, el.legacyMode].forEach(node => {
    node.addEventListener('change', () => setStatus('Unsaved changes'));
  });
}

async function loadSettings() {
  const stored = await storageGet([
    'serverUrl',
    'embedMetadata',
    'downloadSubtitles',
    'defaultQuality',
    'legacyMode',
  ]);

  el.serverUrl.value =
    typeof stored.serverUrl === 'string' && stored.serverUrl
      ? stored.serverUrl
      : DEFAULTS.serverUrl;
  el.embedMetadata.checked =
    typeof stored.embedMetadata === 'boolean'
      ? stored.embedMetadata
      : DEFAULTS.embedMetadata;
  el.downloadSubtitles.checked =
    typeof stored.downloadSubtitles === 'boolean'
      ? stored.downloadSubtitles
      : DEFAULTS.downloadSubtitles;
  el.defaultQuality.value =
    typeof stored.defaultQuality === 'string' && stored.defaultQuality
      ? stored.defaultQuality
      : DEFAULTS.defaultQuality;
  el.legacyMode.checked =
    typeof stored.legacyMode === 'boolean'
      ? stored.legacyMode
      : DEFAULTS.legacyMode;

  setStatus('Settings loaded');
}

async function saveSettings() {
  const payload = {
    serverUrl: el.serverUrl.value.trim() || DEFAULTS.serverUrl,
    embedMetadata: el.embedMetadata.checked,
    downloadSubtitles: el.downloadSubtitles.checked,
    defaultQuality: el.defaultQuality.value,
    legacyMode: el.legacyMode.checked,
  };

  await storageSet(payload);
  setStatus('Settings saved');
}

function setStatus(message) {
  el.saveStatus.textContent = message;
}

function storageGet(keys) {
  return new Promise(resolve => chrome.storage.sync.get(keys, resolve));
}

function storageSet(value) {
  return new Promise(resolve => chrome.storage.sync.set(value, resolve));
}