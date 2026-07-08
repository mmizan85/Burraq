"use strict";

const DEFAULT_SERVER_URL = "http://localhost:9090";
const DOWNLOAD_MESSAGE = "QUEUE_DEVICE_DOWNLOAD";
const REQUEST_TIMEOUT_MS = 10000;

const DEFAULT_SETTINGS = {
  serverUrl: DEFAULT_SERVER_URL,
  embedMetadata: true,
  downloadSubtitles: false,
  defaultQuality: "1080p",
  legacyMode: false,
};

// Initialize context menu on extension install
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: "Burraq-download",
    title: "Download with Burraq",
    contexts: ["link", "page"],
  });

  chrome.contextMenus.create({
    id: "Burraq-video",
    title: "Burraq: Video (Best)",
    contexts: ["link", "page"],
    parentId: "Burraq-download",
  });

  chrome.contextMenus.create({
    id: "Burraq-audio",
    title: "Burraq: Audio (MP3)",
    contexts: ["link", "page"],
    parentId: "Burraq-download",
  });

  chrome.contextMenus.create({
    id: "Burraq-fphone",
    title: "Burraq: Feature Phone (F-video)",
    contexts: ["link", "page"],
    parentId: "Burraq-download",
  });
});

// Context menu click handler
chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (!info.menuItemId.startsWith("Burraq-")) return;

  const serverUrl = await getServerUrl();
  const settings = await getDownloadSettings();
  
  let downloadType = "video";
  let quality = "best";
  let format = "mp4";

  if (info.menuItemId === "Burraq-audio") {
    downloadType = "audio";
    quality = "best";
    format = "mp3";
  } else if (info.menuItemId === "Burraq-fphone") {
    downloadType = "video";
    quality = "F-video";
    format = "mp4";
  }

  const url = info.linkUrl || info.pageUrl;
  if (!url) return;

  // Detect if URL is a playlist
  const isPlaylist = isYouTubePlaylist(url) || isYouTubeMusicPlaylist(url);

  const payload = {
    url,
    title: "Context Menu Download",
    download_type: downloadType,
    is_playlist: isPlaylist,
    quality,
    format,
    embed_metadata: settings.embedMetadata,
    download_subtitles: settings.downloadSubtitles,
    legacy_mode: settings.legacyMode,
  };

  try {
    await queueDownload(serverUrl, payload);
    showNotification("Burraq", `Download queued: ${downloadType} (${quality})${isPlaylist ? ' [Playlist]' : ''}`);
  } catch (error) {
    showNotification("Burraq Error", error.message);
  }
});

// Helper function to detect YouTube playlists
function isYouTubePlaylist(url) {
  try {
    const parsed = new URL(url);
    return parsed.hostname.includes('youtube.com') && 
           (parsed.searchParams.has('list') || /playlist/i.test(parsed.pathname));
  } catch {
    return false;
  }
}

// Helper function to detect YouTube Music playlists
function isYouTubeMusicPlaylist(url) {
  try {
    const parsed = new URL(url);
    return parsed.hostname.includes('music.youtube.com') && 
           (parsed.searchParams.has('list') || /playlist/i.test(parsed.pathname));
  } catch {
    return false;
  }
}

// Message listener
chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== DOWNLOAD_MESSAGE) {
    return false;
  }

  getServerUrl().then(serverUrl => {
    queueDownload(serverUrl, message.payload)
      .then((result) => {
        sendResponse({
          ok: true,
          taskId: result.task_id || null,
          message: result.message || "Download queued successfully.",
        });
      })
      .catch((error) => {
        sendResponse({
          ok: false,
          error: normalizeError(error),
        });
      });
  });

  return true;
});

// Get server URL from settings
async function getServerUrl() {
  const settings = await chrome.storage.sync.get(["serverUrl"]);
  return settings.serverUrl || DEFAULT_SERVER_URL;
}

// Queue download to server
async function queueDownload(serverUrl, payload) {
  const settings = await getDownloadSettings();
  const mergedPayload = buildPayload(payload, settings);

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(`${serverUrl}/add-download`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(mergedPayload),
      signal: controller.signal,
    });

    const data = await response.json().catch(() => null);
    if (!response.ok) {
      throw new Error(readErrorMessage(data, response.status));
    }

    return data || {};
  } finally {
    clearTimeout(timeoutId);
  }
}

// Get download settings
async function getDownloadSettings() {
  const stored = await chrome.storage.sync.get([
    "serverUrl",
    "embedMetadata",
    "downloadSubtitles",
    "defaultQuality",
    "legacyMode",
  ]);

  return {
    serverUrl:
      typeof stored.serverUrl === "string" && stored.serverUrl
        ? stored.serverUrl
        : DEFAULT_SETTINGS.serverUrl,
    embedMetadata:
      typeof stored.embedMetadata === "boolean"
        ? stored.embedMetadata
        : DEFAULT_SETTINGS.embedMetadata,
    downloadSubtitles:
      typeof stored.downloadSubtitles === "boolean"
        ? stored.downloadSubtitles
        : DEFAULT_SETTINGS.downloadSubtitles,
    defaultQuality:
      typeof stored.defaultQuality === "string" && stored.defaultQuality
        ? stored.defaultQuality
        : DEFAULT_SETTINGS.defaultQuality,
    legacyMode:
      typeof stored.legacyMode === "boolean"
        ? stored.legacyMode
        : DEFAULT_SETTINGS.legacyMode,
  };
}

// Build payload
function buildPayload(payload, settings) {
  const base = payload && typeof payload === "object" ? { ...payload } : {};
  const isVideo = (base.download_type || "video") === "video";

  if (!base.quality) {
    base.quality = settings.defaultQuality;
  }

  if (settings.legacyMode && isVideo) {
    base.format = "mp4";
  }

  return {
    ...base,
    embed_metadata: settings.embedMetadata,
    download_subtitles: settings.downloadSubtitles,
    legacy_mode: settings.legacyMode,
  };
}

// Read error message
function readErrorMessage(data, statusCode) {
  if (data && typeof data.detail === "string" && data.detail.trim()) {
    return data.detail.trim();
  }
  if (data && typeof data.message === "string" && data.message.trim()) {
    return data.message.trim();
  }
  return "Burraq server error (" + statusCode + ").";
}

// Normalize error
function normalizeError(error) {
  if (error && error.name === "AbortError") {
    return "Request timed out. Make sure the Burraq server is running.";
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return "Unable to reach the Burraq server.";
}

// Show notification
function showNotification(title, message) {
  if (typeof chrome.notifications !== "undefined") {
    chrome.notifications.create({
      type: "basic",
      iconUrl: "icons/icon48.png",
      title,
      message,
    });
  }
}