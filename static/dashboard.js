// Burraq Web Dashboard v4.0 - Vanilla JS
// Real-time updates via WebSocket, dynamic navigation, and settings

(() => {
  'use strict';

  // Configuration
  const API_BASE = window.location.origin;
  
  // State
  const state = {
    currentSection: 'downloads',
    filter: 'all',
    tasks: [],
    history: [],
    settings: {},
    ws: null,
    reconnectAttempts: 0,
    maxReconnectAttempts: 10,
    downloadType: 'video',
  };

  // Quality and Format options
  const VIDEO_QUALITIES = [
    { value: 'best', label: 'Best' },
    { value: '2160p', label: '4K' },
    { value: '1440p', label: '2K' },
    { value: '1080p', label: '1080p' },
    { value: '720p', label: '720p' },
    { value: '480p', label: '480p' },
    { value: '360p', label: '360p' },
    { value: '240p', label: '240p' },
    { value: 'F-video', label: 'F-Phone' },
  ];

  const AUDIO_QUALITIES = [
    { value: '320', label: '320kbps' },
    { value: '256', label: '256kbps' },
    { value: '192', label: '192kbps' },
    { value: '128', label: '128kbps' },
  ];

  const VIDEO_FORMATS = [
    { value: 'mp4', label: 'MP4' },
    { value: 'mkv', label: 'MKV' },
    { value: 'webm', label: 'WebM' },
    { value: 'mov', label: 'MOV' },
    { value: 'avi', label: 'AVI' },
  ];

  const AUDIO_FORMATS = [
    { value: 'mp3', label: 'MP3' },
    { value: 'm4a', label: 'M4A' },
    { value: 'flac', label: 'FLAC' },
    { value: 'opus', label: 'OPUS' },
    { value: 'wav', label: 'WAV' },
    { value: 'aac', label: 'AAC' },
  ];

  // DOM Elements
  const $ = (id) => document.getElementById(id);
  const el = {
    // Navigation
    navItems: () => document.querySelectorAll('.nav-item'),
    sectionTitle: () => $('sectionTitle'),
    topFilters: () => $('topFilters'),
    headerActions: () => $('headerActions'),
    
    // Downloads
    downloadList: () => $('downloadList'),
    queueSize: () => $('queueSize'),
    activeCount: () => $('activeCount'),
    
    // History
    historyList: () => $('historyList'),
    
    // Settings
    downloadDirInput: () => $('downloadDirInput'),
    maxConcurrentInput: () => $('maxConcurrentInput'),
    ytdlpPathInput: () => $('ytdlpPathInput'),
    ffmpegPathInput: () => $('ffmpegPathInput'),
    browserCookiesToggle: () => $('browserCookiesToggle'),
    browserSelect: () => $('browserSelect'),
    speedLimitInput: () => $('speedLimitInput'),
    embedMetadataToggle: () => $('embedMetadataToggle'),
    embedThumbnailsToggle: () => $('embedThumbnailsToggle'),
    autoUpdateToggle: () => $('autoUpdateToggle'),
    saveSettingsBtn: () => $('saveSettingsBtn'),
    
    // Download Form
    addDownloadForm: () => $('addDownloadForm'),
    urlInput: () => $('urlInput'),
    typeSelect: () => $('typeSelect'),
    qualitySelect: () => $('qualitySelect'),
    formatSelect: () => $('formatSelect'),
    clipboardPasteBtn: () => $('clipboardPasteBtn'),
    
    // Status
    statusIndicator: () => $('statusIndicator'),
    statusText: () => $('statusText'),
    ytdlpVersion: () => $('ytdlpVersion'),
    
    // Actions
    pauseAllBtn: () => $('pauseAllBtn'),
    resumeAllBtn: () => $('resumeAllBtn'),
    openFolderBtn: () => $('openFolderBtn'),
    
    // Storage Analytics
    storageSection: () => $('storageSection'),
    driveTotal: () => $('driveTotal'),
    driveFree: () => $('driveFree'),
    folderSize: () => $('folderSize'),
    storagePercent: () => $('storagePercent'),
    storageProgress: () => $('storageProgress'),
    lastHour: () => $('lastHour'),
    todayCount: () => $('todayCount'),
    yesterdayCount: () => $('yesterdayCount'),
    fileCount: () => $('fileCount'),
    folderCount: () => $('folderCount'),
    
    // Sections
    downloadsSection: () => $('downloadsSection'),
    historySection: () => $('historySection'),
    settingsSection: () => $('settingsSection'),
    aboutSection: () => $('aboutSection'),
    downloadFormContainer: () => $('downloadFormContainer'),
  };

  // Initialize
  document.addEventListener('DOMContentLoaded', () => {
    initWebSocket();
    initEventListeners();
    loadSettings();
    loadVersion();
    renderQualityOptions();
    renderFormatOptions();
  });

  // WebSocket Connection
  function initWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws`;
    
    state.ws = new WebSocket(wsUrl);
    
    state.ws.onopen = () => {
      state.reconnectAttempts = 0;
      updateStatus(true);
    };
    
    state.ws.onmessage = (event) => {
      const data = JSON.parse(event.data);
      if (data.type === 'status_update') {
        updateTasks(data.data.active_tasks);
        processEvents(data.events);
      }
    };
    
    state.ws.onclose = () => {
      updateStatus(false);
      if (state.reconnectAttempts < state.maxReconnectAttempts) {
        state.reconnectAttempts++;
        setTimeout(initWebSocket, 2000 * state.reconnectAttempts);
      }
    };
    
    state.ws.onerror = (error) => {
      console.error('WebSocket error:', error);
    };
  }

  // Update UI Status
  function updateStatus(online) {
    if (online) {
      el.statusIndicator().className = 'w-2 h-2 rounded-full bg-green-400 animate-pulse';
      el.statusText().textContent = 'Online';
    } else {
      el.statusIndicator().className = 'w-2 h-2 rounded-full bg-slate-500';
      el.statusText().textContent = 'Offline';
    }
  }

  // Load yt-dlp version
  async function loadVersion() {
    try {
      const response = await fetch(`${API_BASE}/health`);
      const data = await response.json();
      el.ytdlpVersion().textContent = `v${data.ytdlp_version || '?'}`;
    } catch (error) {
      el.ytdlpVersion().textContent = '-';
    }
  }

  // Load settings from backend
  async function loadSettings() {
    try {
      const response = await fetch(`${API_BASE}/config`);
      const data = await response.json();
      state.settings = data;
      
      // Update form fields
      if (el.downloadDirInput()) el.downloadDirInput().value = data.download_dir || '';
      if (el.maxConcurrentInput()) el.maxConcurrentInput().value = data.max_concurrent || 3;
      if (el.ytdlpPathInput()) el.ytdlpPathInput().value = data.ytdlp_path || '';
      if (el.ffmpegPathInput()) el.ffmpegPathInput().value = data.ffmpeg_path || '';
      if (el.browserCookiesToggle()) el.browserCookiesToggle().checked = data.browser_cookies || false;
      if (el.browserSelect()) el.browserSelect().value = data.browser || 'chrome';
      if (el.speedLimitInput()) el.speedLimitInput().value = data.speed_limit || '';
      if (el.embedMetadataToggle()) el.embedMetadataToggle().checked = data.embed_metadata !== false;
      if (el.embedThumbnailsToggle()) el.embedThumbnailsToggle().checked = data.embed_thumbnails !== false;
      if (el.autoUpdateToggle()) el.autoUpdateToggle().checked = data.auto_update !== false;
      
      // Update toggle switch visual states
      updateToggleSwitches();
    } catch (error) {
      console.error('Failed to load settings:', error);
    }
  }

  // Update toggle switch visual states
  function updateToggleSwitches() {
    document.querySelectorAll('.toggle-switch').forEach(toggle => {
      const input = toggle.querySelector('input[type="checkbox"]');
      const track = toggle.querySelector('.toggle-track');
      const tooltip = toggle.querySelector('.toggle-tooltip');
      
      if (input.checked) {
        track.classList.add('on');
        track.classList.remove('off');
        tooltip.classList.add('on');
        tooltip.classList.remove('off');
        tooltip.textContent = 'Status: ON';
      } else {
        track.classList.remove('on');
        track.classList.add('off');
        tooltip.classList.remove('on');
        tooltip.classList.add('off');
        tooltip.textContent = 'Status: OFF';
      }
    });
  }

  // Update Tasks
  function updateTasks(tasks) {
    state.tasks = tasks;
    renderTasks();
    el.queueSize().textContent = tasks.length;
    el.activeCount().textContent = tasks.filter(t => t.status === 'Downloading').length;
  }

  // Process Events
  function processEvents(events) {
    for (const event of events) {
      if (event.type === 'task_completed') {
        showToast(`Download completed: ${event.title}`, 'success');
      } else if (event.type === 'task_failed') {
        showToast(`Download failed: ${event.title} - ${event.error || 'Unknown error'}`, 'error');
      } else if (event.type === 'task_cancelled') {
        showToast(`Download cancelled: ${event.title}`, 'info');
      } else if (event.type === 'metadata_fetched') {
        // Update task with fetched metadata
        const task = state.tasks.find(t => t.task_id === event.task_id);
        if (task) {
          task.title = event.title || task.title;
          task.thumbnail = event.thumbnail;
          task.uploader = event.uploader;
          renderTasks();
        }
      }
    }
  }

  // Render Tasks
  function renderTasks() {
    const filtered = filterTasks(state.tasks, state.filter);
    
    if (filtered.length === 0) {
      el.downloadList().innerHTML = `
        <div class="text-center py-12 text-slate-400">
          <svg class="w-16 h-16 mx-auto mb-4 opacity-20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
            <path d="M12 2v16M6 10l6 6 6-6" stroke-linecap="round" stroke-linejoin="round"/>
          </svg>
          <p>No downloads to display</p>
        </div>
      `;
      return;
    }

    el.downloadList().innerHTML = filtered.map(task => `
      <div class="download-card" data-task-id="${task.task_id}" data-type="${task.download_type}" data-status="${task.status}">
        <div class="flex items-start justify-between mb-3">
          <div class="flex-1 min-w-0">
            <h3 class="font-medium text-slate-100 truncate mb-1">${escapeHtml(task.title || 'Untitled')}</h3>
            ${task.uploader ? `<p class="text-xs text-slate-500 truncate mb-1">by ${escapeHtml(task.uploader)}</p>` : ''}
            <div class="flex items-center gap-3 text-xs text-slate-400">
              <span class="px-2 py-0.5 rounded bg-slate-800/50">${task.download_type}</span>
              <span>${task.quality}</span>
              <span>${task.format_type}</span>
            </div>
          </div>
          <span class="status-badge status-${task.status.toLowerCase()}">${task.status}</span>
        </div>
        
        <div class="mb-3">
          <div class="flex items-center justify-between text-xs mb-1">
            <span class="text-slate-400">Progress</span>
            <span class="font-mono text-cyan-400">${task.progress.toFixed(1)}%</span>
          </div>
          <div class="progress-track">
            <div class="progress-fill" style="width: ${task.progress}%"></div>
          </div>
        </div>
        
        <div class="flex items-center justify-between text-xs">
          <div class="flex items-center gap-4 text-slate-400">
            <span>Speed: <span class="text-cyan-400 font-mono">${task.speed || '--'}</span></span>
            <span>ETA: <span class="text-cyan-400 font-mono">${task.eta || '--'}</span></span>
          </div>
          <div class="flex items-center gap-2">
            <input type="number" class="speed-limit-input" placeholder="Limit" 
                   data-task-id="${task.task_id}" value="${task.speed_limit || ''}"
                   title="Speed limit (KB/s)">
            <button class="px-2 py-1 rounded bg-slate-800/50 hover:bg-red-500/20 hover:text-red-400 transition-colors"
                    onclick="cancelTask('${task.task_id}')">
              ✕
            </button>
          </div>
        </div>
      </div>
    `).join('');
  }

  // Filter Tasks
  function filterTasks(tasks, filter) {
    switch (filter) {
      case 'video':
        return tasks.filter(t => t.download_type === 'video');
      case 'audio':
        return tasks.filter(t => t.download_type === 'audio');
      case 'playlist':
        return tasks.filter(t => t.is_playlist);
      case 'completed':
        return state.tasks.filter(t => t.status === 'Completed');
      case 'failed':
        return state.tasks.filter(t => t.status === 'Failed');
      default:
        return tasks;
    }
  }

   // Render History - FIXED with data attributes for filtering
   function renderHistory() {
     if (state.history.length === 0) {
       el.historyList().innerHTML = `
         <div class="text-center py-12 text-slate-400">
           <svg class="w-16 h-16 mx-auto mb-4 opacity-20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1">
             <path d="M12 2a10 10 0 0 0-10 10c0 5.523 4.477 10 10 10s10-4.477 10-10A10 10 0 0 0 12 2z"/>
             <path d="M12 6v6l3 3" stroke-linecap="round"/>
           </svg>
           <p>No download history</p>
         </div>
       `;
       return;
     }

     el.historyList().innerHTML = state.history.map(item => `
       <div class="download-card history-item" data-type="${item.file_type || 'video'}" data-status="${item.status || 'completed'}">
         <div class="flex items-start justify-between mb-3">
           <div class="flex-1 min-w-0">
             <h3 class="font-medium text-slate-100 truncate mb-1">${escapeHtml(item.title || 'Untitled')}</h3>
             <div class="flex items-center gap-3 text-xs text-slate-400">
               <span class="px-2 py-0.5 rounded bg-slate-800/50 capitalize">${item.file_type || 'video'}</span>
               <span>${formatSize(item.size_bytes || 0)}</span>
               <span>${item.completed_at || ''}</span>
             </div>
           </div>
         </div>
         <div class="text-xs text-slate-400 truncate">
           ${escapeHtml(item.filepath || 'File not found')}
         </div>
       </div>
     `).join('');
   }

  // Filter History Items - NEW FUNCTION
  function filterHistoryItems(filter) {
    const items = el.historyList().querySelectorAll('.history-item');
    items.forEach(item => {
      const type = item.dataset.type;
      const status = item.dataset.status;
      
      let show = false;
      switch (filter) {
        case 'all':
          show = true;
          break;
        case 'video':
          show = type === 'video';
          break;
        case 'audio':
          show = type === 'audio';
          break;
        case 'playlist':
          show = type === 'playlist';
          break;
        case 'completed':
          show = status === 'completed';
          break;
        case 'failed':
          show = false; // History only shows completed items
          break;
        default:
          show = true;
      }
      
      item.classList.toggle('hidden', !show);
    });
  }

  // Render Quality Options (Dynamic based on type)
  function renderQualityOptions() {
    const qualities = state.downloadType === 'video' ? VIDEO_QUALITIES : AUDIO_QUALITIES;
    el.qualitySelect().innerHTML = qualities.map(q => 
      `<option value="${q.value}">${q.label}</option>`
    ).join('');
  }

  // Render Format Options (Dynamic based on type)
  function renderFormatOptions() {
    const formats = state.downloadType === 'video' ? VIDEO_FORMATS : AUDIO_FORMATS;
    el.formatSelect().innerHTML = formats.map(f => 
      `<option value="${f.value}">${f.label}</option>`
    ).join('');
  }

  // Event Listeners
  function initEventListeners() {
    // Navigation
    el.navItems().forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const section = item.dataset.section;
        switchSection(section);
      });
    });

    // Type selection - Update quality and format dropdowns
    el.typeSelect().addEventListener('change', () => {
      state.downloadType = el.typeSelect().value;
      renderQualityOptions();
      renderFormatOptions();
    });

    // Clipboard Paste Button - Smart paste functionality
    if (el.clipboardPasteBtn()) {
      el.clipboardPasteBtn().addEventListener('click', async () => {
        try {
          // Request clipboard permission and read text
          const text = await navigator.clipboard.readText();
          
          // Sanitize the URL
          const sanitizedUrl = sanitizeUrl(text);
          
          if (sanitizedUrl) {
            const inputField = el.urlInput();
            inputField.value = sanitizedUrl;
            // Dispatch synthetic events to ensure the system state updates natively
            inputField.dispatchEvent(new Event('input', { bubbles: true }));
            inputField.dispatchEvent(new Event('change', { bubbles: true }));
            inputField.focus();
            showToast('URL pasted from clipboard', 'success');
          } else {
            showToast('No valid URL found in clipboard', 'error');
          }
        } catch (err) {
          console.error('Clipboard read failed:', err);
          if (err.name === 'NotAllowedError') {
            showToast('Clipboard permission denied. Click the input field and paste manually (Ctrl+V).', 'error');
          } else {
            showToast('Failed to read clipboard. Please paste manually.', 'error');
          }
        }
      });
    }

    // Add Download Form - Enhanced with metadata pre-fetch
    el.addDownloadForm().addEventListener('submit', async (e) => {
      e.preventDefault();
      
      // Get and sanitize URL
      const rawUrl = el.urlInput().value.trim();
      const url = sanitizeUrl(rawUrl);
      
      if (!url) {
        showToast('Please enter a valid URL', 'error');
        return;
      }

      // Disable form during submission
      const submitBtn = e.target.querySelector('button[type="submit"]');
      const originalText = submitBtn.textContent;
      submitBtn.disabled = true;
      submitBtn.textContent = 'Adding...';

      try {
        // First, fetch metadata to get title, thumbnail, etc.
        let metadata = null;
        try {
          const infoResponse = await fetch(`${API_BASE}/get-info`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url }),
          });
          
          if (infoResponse.ok) {
            metadata = await infoResponse.json();
          }
        } catch (infoErr) {
          console.warn('Could not fetch metadata, proceeding with download:', infoErr);
        }

        // Add download to queue
        const response = await fetch(`${API_BASE}/add-download`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            url,
            download_type: el.typeSelect().value,
            quality: el.qualitySelect().value,
            format: el.formatSelect().value,
            title: metadata?.title || 'Untitled',
            is_playlist: metadata?.is_playlist || false,
            embed_metadata: state.settings.embed_metadata !== false,
            download_subtitles: false,
            legacy_mode: false,
          }),
        });

        if (response.ok) {
          el.urlInput().value = '';
          showToast('Download added to queue', 'success');
        } else {
          const error = await response.json();
          showToast(error.detail || 'Failed to add download', 'error');
        }
      } catch (err) {
        showToast('Connection error', 'error');
      } finally {
        submitBtn.disabled = false;
        submitBtn.textContent = originalText;
      }
    });

    // Pause/Resume All
    el.pauseAllBtn().addEventListener('click', async () => {
      await fetch(`${API_BASE}/pause-all`, { method: 'POST' });
      showToast('All downloads paused', 'info');
    });

    el.resumeAllBtn().addEventListener('click', async () => {
      await fetch(`${API_BASE}/resume-all`, { method: 'POST' });
      showToast('All downloads resumed', 'info');
    });

    // Save Settings
    el.saveSettingsBtn().addEventListener('click', saveSettings);

    // Speed limit inputs
    el.downloadList().addEventListener('change', (e) => {
      if (e.target.classList.contains('speed-limit-input')) {
        const taskId = e.target.dataset.taskId;
        const limit = e.target.value ? parseInt(e.target.value) : null;
        setSpeedLimit(taskId, limit);
      }
    });

    // Toggle switch event listeners
    document.querySelectorAll('.toggle-switch').forEach(toggle => {
      const input = toggle.querySelector('input[type="checkbox"]');
      const track = toggle.querySelector('.toggle-track');
      const tooltip = toggle.querySelector('.toggle-tooltip');
      
      input.addEventListener('change', () => {
        if (input.checked) {
          track.classList.add('on');
          track.classList.remove('off');
          tooltip.classList.add('on');
          tooltip.classList.remove('off');
          tooltip.textContent = 'Status: ON';
        } else {
          track.classList.remove('on');
          track.classList.add('off');
          tooltip.classList.remove('on');
          tooltip.classList.add('off');
          tooltip.textContent = 'Status: OFF';
        }
      });
    });
  }

  // URL Sanitization - Remove spaces, tracking tags, and fix malformed protocols
  function sanitizeUrl(url) {
    if (!url) return null;
    
    // Trim whitespace
    url = url.trim();
    
    // Remove common tracking parameters
    try {
      const urlObj = new URL(url);
      const trackingParams = ['fbclid', 'gclid', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content'];
      trackingParams.forEach(param => urlObj.searchParams.delete(param));
      url = urlObj.toString();
    } catch (e) {
      // If URL parsing fails, just use the trimmed URL
    }
    
    // Ensure protocol is present
    if (!url.startsWith('http://') && !url.startsWith('https://')) {
      url = 'https://' + url;
    }
    
    return url;
  }

  // Switch Section
  function switchSection(section) {
    state.currentSection = section;
    
    // Update nav items
    el.navItems().forEach(item => {
      item.classList.toggle('active', item.dataset.section === section);
    });

    // Show/hide sections
    el.downloadsSection().classList.toggle('hidden', section !== 'downloads');
    el.historySection().classList.toggle('hidden', section !== 'history');
    el.settingsSection().classList.toggle('hidden', section !== 'settings');
    el.aboutSection().classList.toggle('hidden', section !== 'about');
    el.storageSection().classList.toggle('hidden', section !== 'storage');
    el.downloadFormContainer().classList.toggle('hidden', section !== 'downloads');

    // Update title
    el.sectionTitle().textContent = section.charAt(0).toUpperCase() + section.slice(1);

    // Show/hide top filters
    if (section === 'downloads' || section === 'history') {
      renderTopFilters();
      el.topFilters().classList.remove('hidden');
    } else {
      el.topFilters().classList.add('hidden');
    }

    // Load history when switching to history section
    if (section === 'history') {
      loadHistory();
    }
    
    // Load storage analytics when switching to storage section
    if (section === 'storage') {
      loadStorageAnalytics();
    }
  }

  // Load Storage Analytics
  async function loadStorageAnalytics() {
    try {
      const [storage, historyStats, analyticsLogs] = await Promise.all([
        fetch(`${API_BASE}/analytics/storage`).then(r => r.json()),
        fetch(`${API_BASE}/analytics/history-stats`).then(r => r.json()),
        fetch(`${API_BASE}/analytics/logs`).then(r => r.json()),
      ]);
      
      // Update storage analytics
      if (el.driveTotal()) el.driveTotal().textContent = `${storage.drive_total_gb} GB`;
      if (el.driveFree()) el.driveFree().textContent = `${storage.drive_free_gb} GB`;
      if (el.folderSize()) el.folderSize().textContent = `${storage.folder_size_gb} GB`;
      
      // Update storage progress bar
      const percent = storage.drive_total_gb > 0 
        ? Math.round((storage.drive_used_gb / storage.drive_total_gb) * 100) 
        : 0;
      if (el.storagePercent()) el.storagePercent().textContent = `${percent}%`;
      if (el.storageProgress()) el.storageProgress().style.width = `${percent}%`;
      
      // Update history stats
      if (el.lastHour()) el.lastHour().textContent = historyStats.last_hour;
      if (el.todayCount()) el.todayCount().textContent = historyStats.today;
      if (el.yesterdayCount()) el.yesterdayCount().textContent = historyStats.yesterday;
      
      // Update folder structure insights
      if (el.fileCount()) el.fileCount().textContent = storage.file_count;
      if (el.folderCount()) el.folderCount().textContent = storage.folder_count;
      
      // Update analytics logs data (Phase 3)
      if (analyticsLogs) {
        // Could add format distribution display here if needed
        console.log('Analytics logs:', analyticsLogs);
      }
    } catch (error) {
      console.error('Failed to load storage analytics:', error);
    }
  }

  // Open folder button in storage section
  if (el.openFolderBtn()) {
    el.openFolderBtn().addEventListener('click', async () => {
      await fetch(`${API_BASE}/open-folder`, { method: 'POST' });
      showToast('Opening download folder', 'info');
    });
  }

  // Render Top Filters
  function renderTopFilters() {
    const filters = [
      { value: 'all', label: 'All' },
      { value: 'video', label: 'Video' },
      { value: 'audio', label: 'Audio' },
      { value: 'playlist', label: 'Playlist' },
      { value: 'completed', label: 'Completed' },
      { value: 'failed', label: 'Failed' },
    ];

    el.topFilters().innerHTML = filters.map(f => `
      <button type="button" class="filter-btn ${state.filter === f.value ? 'active' : ''}" data-filter="${f.value}">
        ${f.label}
      </button>
    `).join('');

    // Add event listeners to filter buttons
    el.topFilters().querySelectorAll('.filter-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        state.filter = btn.dataset.filter;
        el.topFilters().querySelectorAll('.filter-btn').forEach(b => b.classList.toggle('active', b === btn));
        
        if (state.currentSection === 'downloads') {
          renderTasks();
        } else if (state.currentSection === 'history') {
          // FIX: Use the new filterHistoryItems function for History section
          filterHistoryItems(state.filter);
        }
      });
    });
  }

  // Load History
  async function loadHistory(filter = "all") {
    try {
      const response = await fetch(`${API_BASE}/history?file_type=${filter}&status=${filter === 'failed' ? 'failed' : 'completed'}`);
      state.history = await response.json();
      renderHistory();
    } catch (error) {
      console.error('Failed to load history:', error);
    }
  }

  // Save Settings
  async function saveSettings() {
    const config = {
      download_dir: el.downloadDirInput().value,
      max_concurrent: parseInt(el.maxConcurrentInput().value) || 3,
      ytdlp_path: el.ytdlpPathInput().value,
      ffmpeg_path: el.ffmpegPathInput().value,
      browser_cookies: el.browserCookiesToggle().checked,
      browser: el.browserSelect().value,
      speed_limit: el.speedLimitInput().value ? parseInt(el.speedLimitInput().value) : null,
      embed_metadata: el.embedMetadataToggle().checked,
      embed_thumbnails: el.embedThumbnailsToggle().checked,
      auto_update: el.autoUpdateToggle().checked,
    };

    try {
      await fetch(`${API_BASE}/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(config),
      });
      showToast('Settings saved', 'success');
    } catch (error) {
      showToast('Failed to save settings', 'error');
    }
  }

  // Cancel Task
  window.cancelTask = async (taskId) => {
    try {
      await fetch(`${API_BASE}/cancel/${taskId}`, { method: 'DELETE' });
      showToast('Task cancelled', 'info');
    } catch (err) {
      showToast('Failed to cancel task', 'error');
    }
  };

  // Set Speed Limit
  async function setSpeedLimit(taskId, limit) {
    try {
      await fetch(`${API_BASE}/speed-limit/${taskId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ speed_limit: limit }),
      });
    } catch (err) {
      console.error('Failed to set speed limit:', err);
    }
  }

  // Toast Notification
  let toastTimer;
  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast show`;
    toast.textContent = message;
    
    if (type === 'success') {
      toast.style.borderColor = 'rgba(0, 255, 136, 0.3)';
    } else if (type === 'error') {
      toast.style.borderColor = 'rgba(255, 64, 96, 0.3)';
    }
    
    document.body.appendChild(toast);
    
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      toast.remove();
    }, 3000);
  }

  // Escape HTML
  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  }

  // Format file size
  function formatSize(bytes) {
    for (const unit of ['B', 'KB', 'MB', 'GB', 'TB']) {
      if (bytes < 1024.0) {
        return `${bytes.toFixed(1)} ${unit}`;
      }
      bytes /= 1024.0;
    }
    return `${bytes.toFixed(1)} PB`;
  }
})();