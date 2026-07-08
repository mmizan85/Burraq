'use strict';

(function () {
  const ROOT_ID = 'Burraq-root';
  const OVERLAY_ID = 'Burraq-overlay';
  const LAUNCHER_ID = 'Burraq-launcher';
  const MENU_ID = 'Burraq-menu';
  const TOAST_ID = 'Burraq-toast';
  const DOWNLOAD_MESSAGE = 'QUEUE_DEVICE_DOWNLOAD';
  const FAB_POSITION_KEY = 'Burraq_fab_position_v1';
  const INLINE_RETRY_LIMIT = 6;
  const GENERIC_RETRY_LIMIT = 4;
  const MENU_CLOSE_DELAY_MS = 120;
  const TOAST_DURATION_MS = 2000;
  const IDLE_HIDE_DELAY_MS = 3000;
  const DRAG_THRESHOLD_PX = 4;

  const DEVICE_OPTIONS = [
    {
      deviceType: 'pc_laptop',
      icon: '\uD83D\uDCBB',
      label: 'PC & Laptop',
      meta: '1080p MP4',
      downloadType: 'video',
      quality: '1080p',
      format: 'mp4',
    },
    {
      deviceType: 'original_quality',
      icon: '\uD83C\uDFA5',
      label: 'Original Quality Video',
      meta: 'Best MKV/MP4',
      downloadType: 'video',
      quality: 'best',
      format: 'mkv',
    },
    {
      deviceType: 'mobile_phone',
      icon: '\uD83D\uDCF1',
      label: 'iPhone & Android Phone',
      meta: '720p MP4',
      downloadType: 'video',
      quality: '720p',
      format: 'mp4',
    },
    {
      deviceType: 'smart_tv',
      icon: '\uD83D\uDCFA',
      label: 'Smart TV',
      meta: 'Best MP4',
      downloadType: 'video',
      quality: 'best',
      format: 'mp4',
    },
    {
      deviceType: 'feature_phone',
      icon: '\uD83D\uDCDF',
      label: 'Feature Phone',
      meta: 'Low-bandwidth MP4',
      downloadType: 'video',
      quality: 'F-video',
      format: 'mp4',
    },
    {
      deviceType: 'audio',
      icon: '\uD83C\uDFB5',
      label: 'Audio (MP3/M4A)',
      meta: 'Best MP3',
      downloadType: 'audio',
      quality: 'best',
      format: 'mp3',
    },
  ];

  const YTDLP_SITES = [
    { host: /youtube\.com|youtu\.be/, name: 'YouTube', color: '#ff0000' },
    { host: /vimeo\.com/, name: 'Vimeo', color: '#1ab7ea' },
    { host: /twitch\.tv/, name: 'Twitch', color: '#9146ff' },
    { host: /dailymotion\.com/, name: 'Dailymotion', color: '#0066dc' },
    { host: /bilibili\.com/, name: 'Bilibili', color: '#fb7299' },
    { host: /rumble\.com/, name: 'Rumble', color: '#85c742' },
    { host: /facebook\.com|fb\.com/, name: 'Facebook', color: '#1877f2' },
    { host: /instagram\.com/, name: 'Instagram', color: '#c13584' },
    { host: /twitter\.com|x\.com/, name: 'X / Twitter', color: '#1da1f2' },
    { host: /tiktok\.com/, name: 'TikTok', color: '#ff0050' },
    { host: /reddit\.com/, name: 'Reddit', color: '#ff4500' },
    { host: /soundcloud\.com/, name: 'SoundCloud', color: '#ff5500' },
    { host: /bandcamp\.com/, name: 'Bandcamp', color: '#1da0c3' },
    { host: /bbc\.co\.uk|bbc\.com/, name: 'BBC', color: '#bb1919' },
    { host: /cnn\.com/, name: 'CNN', color: '#cc0000' },
    { host: /nytimes\.com/, name: 'NYTimes', color: '#000000' },
  ];

  const state = {
    lastUrl: location.href,
    currentTitle: document.title,
    currentUrl: window.location.href,
    injectTimer: 0,
    retryCount: 0,
    root: null,
    overlay: null,
    launcher: null,
    launcherLabel: null,
    menu: null,
    toast: null,
    optionButtons: [],
    menuListenersCleanup: null,
    toastTimer: 0,
    hideTimer: 0,
    info: null,
    mode: 'inline',
    suppressClickUntil: 0,
    fabPosition: null,
    drag: {
      active: false,
      moved: false,
      pointerId: null,
      startX: 0,
      startY: 0,
      originX: 0,
      originY: 0,
    },
  };

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message && message.type === 'GET_PAGE_INFO') {
      sendResponse(buildPageInfo());
    }
  });

  function getDynamicVideoTitle() {
    // 1. Try YouTube-specific selectors first (updates immediately on SPA nav)
    const ytTitle =
      document
        .querySelector('ytd-watch-metadata h1 yt-formatted-string')
        ?.textContent?.trim() ||
      document.querySelector('#title yt-formatted-string')?.textContent?.trim();
    if (ytTitle && ytTitle.length > 2) return ytTitle;

    // 2. Fallback to standard meta/document title
    const raw = getMetaContent('og:title') || document.title || 'Untitled';
    return raw.replace(/\s*[-|]\s*YouTube$/i, '').trim() || 'Untitled';
  }

  function buildPageInfo() {
    const rawUrl = location.href;
    const url = rawUrl;
    const host = location.hostname.replace(/^www\./, '');
    const site = detectSite(host);
    const isYouTube = /(^|\.)youtube\.com$|(^|\.)youtu\.be$/.test(host);
    const videoId = isYouTube ? getYouTubeVideoId() : null;
    const parsedUrl = safeUrl(rawUrl);
    const isPlaylist = Boolean(
      parsedUrl &&
        (parsedUrl.searchParams.has('list') ||
          /\/playlist(?:\/|$)/i.test(parsedUrl.pathname)),
    );

    const ogImage = getMetaContent('og:image');
    const ogVideo =
      getMetaContent('og:video:url') || getMetaContent('og:video');
    const videoEl = document.querySelector('video');
    const audioEl = document.querySelector('audio');
    const title = getDynamicVideoTitle();
    const directMediaUrl =
      videoEl?.currentSrc ||
      videoEl?.src ||
      audioEl?.currentSrc ||
      audioEl?.src ||
      ogVideo ||
      null;
    const thumbnail = videoId
      ? 'https://i.ytimg.com/vi/' + videoId + '/mqdefault.jpg'
      : ogImage || null;
    const duration = getMetaContent('og:video:duration') || null;
    const hasMedia = isYouTube
      ? Boolean(videoId)
      : Boolean(directMediaUrl || detectMediaInPage());

    return {
      url: url,
      canonicalUrl: sanitizeMediaUrl(rawUrl),
      rawUrl: rawUrl,
      host: host,
      title: title,
      thumbnail: thumbnail,
      siteName: site.name,
      siteColor: site.color,
      isYouTube: isYouTube,
      isPlaylist: isPlaylist,
      videoId: videoId,
      directMediaUrl: directMediaUrl,
      duration: duration,
      hasMedia: hasMedia,
      isSupported: true,
    };
  }

  function detectSite(host) {
    for (const site of YTDLP_SITES) {
      if (site.host.test(host)) {
        return site;
      }
    }
    return { name: null, color: null }; // 👈 Changed to null for unsupported sites
  }

  function getMetaContent(propertyName) {
    const selector =
      'meta[property="' +
      propertyName +
      '"], meta[name="' +
      propertyName +
      '"]';
    return document.querySelector(selector)?.content || '';
  }

  function getYouTubeVideoId() {
    try {
      return extractYouTubeVideoId(new URL(location.href));
    } catch (_error) {
      return null;
    }
  }

  function extractYouTubeVideoId(url) {
    const host = url.hostname.replace(/^www\./, '');
    const parts = url.pathname.split('/').filter(Boolean);

    if (host === 'youtu.be') {
      return parts[0] || null;
    }

    if (
      parts[0] === 'shorts' ||
      parts[0] === 'live' ||
      parts[0] === 'embed' ||
      parts[0] === 'v'
    ) {
      return parts[1] || null;
    }

    return url.searchParams.get('v');
  }

  function safeUrl(value) {
    try {
      return new URL(value);
    } catch (_error) {
      return null;
    }
  }

  function sanitizeMediaUrl(value) {
    try {
      const url = new URL(value);
      const host = url.hostname.replace(/^www\./, '');
      const isYouTube = /(^|\.)youtube\.com$|(^|\.)youtu\.be$/.test(host);

      if (!isYouTube) {
        return url.toString();
      }

      const videoId = extractYouTubeVideoId(url);
      if (videoId) {
        return 'https://www.youtube.com/watch?v=' + videoId;
      }

      url.searchParams.delete('list');
      url.searchParams.delete('index');
      url.searchParams.delete('pp');
      return url.toString();
    } catch (_error) {
      return value;
    }
  }

  function detectMediaInPage() {
    return Boolean(
      document.querySelector(
        "video, audio, meta[property='og:video'], meta[property='og:video:url'], " +
          "iframe[src*='youtube'], iframe[src*='vimeo'], iframe[src*='twitch'], " +
          '[data-video-id], [data-media-id]',
      ),
    );
  }

  function scheduleInject(delay) {
    clearTimeout(state.injectTimer);
    state.injectTimer = window.setTimeout(() => {
      state.injectTimer = 0;
      tryInject();
    }, delay);
  }

  function tryInject() {
    if (!document.body) {
      scheduleInject(250);
      return;
    }

    if (state.root && state.root.isConnected) {
      return;
    }

    const info = buildPageInfo();
    state.info = info;

    if (!info.siteName) {
      cleanup();
      return;
    }

    if (!info.hasMedia && !info.isYouTube) {
      cleanup();
      return;
    }

    const target = resolveInjectionTarget(info);
    if (!target) {
      state.retryCount += 1;
      scheduleInject(500);
      return;
    }

    cleanup();
    state.info = info;
    injectLauncher(target, info);
    state.retryCount = 0;
  }

  function resolveInjectionTarget(info) {
    if (info.isYouTube) {
      const likeAnchor = findBestMatch([
        'ytd-segmented-like-dislike-button-renderer',
        'segmented-like-dislike-button-view-model',
        'ytd-menu-renderer #top-level-buttons-computed > *:first-child',
        'ytd-watch-metadata #top-level-buttons-computed > ytd-toggle-button-renderer',
      ]);

      if (likeAnchor) {
        return {
          mode: 'inline',
          placement: 'before',
          anchor: likeAnchor,
        };
      }

      if (state.retryCount < INLINE_RETRY_LIMIT) {
        return null;
      }

      const actionBar = findBestMatch([
        '#top-level-buttons-computed',
        '#top-level-buttons',
        'ytd-menu-renderer #top-level-buttons-computed',
        'ytd-watch-metadata #actions-inner',
      ]);

      if (actionBar) {
        return {
          mode: 'inline',
          placement: 'prepend',
          container: actionBar,
        };
      }

      return { mode: 'fab' };
    }

    const inlineTarget = findGenericInlineTarget();
    if (inlineTarget) {
      return inlineTarget;
    }

    if (state.retryCount < GENERIC_RETRY_LIMIT) {
      return null;
    }

    return { mode: 'fab' };
  }

  function findGenericInlineTarget() {
    const afterAnchor = findBestMatch([
      "[data-testid='share-button']",
      "[aria-label*='Share' i]",
      "[title*='Share' i]",
      '.share-button',
    ]);

    if (afterAnchor) {
      return {
        mode: 'inline',
        placement: 'after',
        anchor: normalizeActionAnchor(afterAnchor),
      };
    }

    const container = findBestMatch([
      '.action-buttons',
      '.video-actions',
      "[class*='action-bar']",
      "[class*='video-actions']",
      "[class*='player-controls']",
    ]);

    if (container) {
      return {
        mode: 'inline',
        placement: 'prepend',
        container: container,
      };
    }

    return null;
  }

  function findBestMatch(selectors) {
    const matches = [];

    for (const selector of selectors) {
      for (const element of document.querySelectorAll(selector)) {
        if (isEligibleTarget(element)) {
          matches.push(element);
        }
      }
      if (matches.length > 0) {
        break;
      }
    }

    if (matches.length === 0) {
      return null;
    }

    return pickClosestToMedia(matches);
  }

  function isEligibleTarget(element) {
    if (!element || !element.isConnected) {
      return false;
    }

    if (state.root && state.root.contains(element)) {
      return false;
    }

    const style = window.getComputedStyle(element);
    if (style.display === 'none' || style.visibility === 'hidden') {
      return false;
    }

    const rect = element.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
  }

  function pickClosestToMedia(elements) {
    const mediaRect = getPrimaryMediaRect();
    if (!mediaRect || elements.length === 1) {
      return elements[0];
    }

    const mediaCenterX = mediaRect.left + mediaRect.width / 2;
    const mediaCenterY = mediaRect.top + mediaRect.height / 2;

    return elements.slice().sort((left, right) => {
      const leftRect = left.getBoundingClientRect();
      const rightRect = right.getBoundingClientRect();
      const leftScore = distanceScore(leftRect, mediaCenterX, mediaCenterY);
      const rightScore = distanceScore(rightRect, mediaCenterX, mediaCenterY);
      return leftScore - rightScore;
    })[0];
  }

  function distanceScore(rect, x, y) {
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 2;
    const deltaX = centerX - x;
    const deltaY = centerY - y;
    return Math.sqrt(deltaX * deltaX + deltaY * deltaY);
  }

  function getPrimaryMediaRect() {
    const media = document.querySelector(
      "video, iframe[src*='youtube'], iframe[src*='vimeo'], iframe[src*='twitch'], audio",
    );
    return media ? media.getBoundingClientRect() : null;
  }

  function normalizeActionAnchor(element) {
    return element.closest("button, a, [role='button']") || element;
  }

  function injectLauncher(target, info) {
    const root = createLauncherRoot(target.mode, target.placement);
    const overlay = createOverlay(info);
    const launcher = root.querySelector('#' + LAUNCHER_ID);
    const launcherLabel = root.querySelector('.Burraq-launcher__label');

    if (!launcher || !launcherLabel || !overlay) {
      return;
    }

    state.root = root;
    state.overlay = overlay;
    state.launcher = launcher;
    state.launcherLabel = launcherLabel;
    state.menu = overlay.querySelector('#' + MENU_ID);
    state.toast = overlay.querySelector('#' + TOAST_ID);
    state.optionButtons = Array.from(
      overlay.querySelectorAll('.Burraq-menu__option'),
    );
    state.mode = target.mode;

    launcher.addEventListener('click', onLauncherClick);
    launcher.addEventListener('pointerdown', onLauncherPointerDown);
    launcher.addEventListener('pointermove', onLauncherPointerMove);
    launcher.addEventListener('pointerup', onLauncherPointerEnd);
    launcher.addEventListener('pointercancel', onLauncherPointerEnd);

    for (const button of state.optionButtons) {
      button.addEventListener('click', onOptionClick);
    }

    if (target.mode === 'fab') {
      document.body.appendChild(root);
    } else if (!mountInlineRoot(root, target)) {
      root.className = 'Burraq-root Burraq-root--fab Burraq-root--visible';
      state.mode = 'fab';
      document.body.appendChild(root);
    }

    document.body.appendChild(overlay);

    if (state.mode === 'fab') {
      requestAnimationFrame(() => {
        applyStoredFabPosition();
        refreshFloatingVisibility();
      });
    }
  }

  function createLauncherRoot(mode, placement) {
    const root = document.createElement('div');
    root.id = ROOT_ID;
    root.className =
      'Burraq-root Burraq-root--' +
      mode +
      (placement ? ' Burraq-root--' + placement : '');
    if (mode === 'fab') {
      root.classList.add('Burraq-root--visible');
    }
    root.innerHTML =
      '<button id="' +
      LAUNCHER_ID +
      '" class="Burraq-launcher" type="button" aria-haspopup="menu" aria-expanded="false">' +
      '<span class="Burraq-launcher__icon" aria-hidden="true">' +
      
      '<svg viewBox="0 0 20 20" fill="none">' +
      '<path d="M10 2v10M6 8l4 4 4-4" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"></path>' +
      '<path d="M3 14v1a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-1" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"></path>' +
      '</svg>' +
      '</span>' +
      '<span class="Burraq-launcher__label ">Burraq</span>' +
      '<span class="Burraq-launcher__caret" aria-hidden="true">\u25BE</span>' +
      '</button>';
    return root;
  }

  function createOverlay(info) {
    const overlay = document.createElement('div');
    overlay.id = OVERLAY_ID;
    overlay.className = 'Burraq-overlay';

    const menu = document.createElement('div');
    menu.id = MENU_ID;
    menu.className = 'Burraq-menu';
    menu.hidden = true;
    menu.setAttribute('role', 'menu');

    const glow = document.createElement('div');
    glow.className = 'Burraq-menu__glow';
    menu.appendChild(glow);

    const panel = document.createElement('div');
    panel.className = 'Burraq-menu__panel';

    const header = document.createElement('div');
    header.className = 'Burraq-menu__header';

    const title = document.createElement('div');
    title.className = 'Burraq-menu__title';
    title.textContent = 'Burraq Device Profiles';

    const subtitle = document.createElement('div');
    subtitle.className = 'Burraq-menu__subtitle';
    subtitle.textContent =
      info.siteName + ' \u2022 ' + truncateText(info.title, 40);

    header.appendChild(title);
    header.appendChild(subtitle);
    panel.appendChild(header);

    const list = document.createElement('div');
    list.className = 'Burraq-menu__list';

    for (const option of DEVICE_OPTIONS) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'Burraq-menu__option';
      button.setAttribute('role', 'menuitem');
      button.dataset.deviceType = option.deviceType;
      button.innerHTML =
        '<span class="Burraq-menu__emoji" aria-hidden="true">' +
        option.icon +
        '</span>' +
        '<span class="Burraq-menu__copy">' +
        '<span class="Burraq-menu__label">' +
        escapeHtml(option.label) +
        '</span>' +
        '<span class="Burraq-menu__meta">' +
        escapeHtml(option.meta) +
        '</span>' +
        '</span>';
      list.appendChild(button);
    }

    panel.appendChild(list);
    menu.appendChild(panel);

    const toast = document.createElement('div');
    toast.id = TOAST_ID;
    toast.className = 'Burraq-toast';
    toast.hidden = true;
    toast.setAttribute('aria-live', 'polite');

    overlay.appendChild(menu);
    overlay.appendChild(toast);
    return overlay;
  }

  function mountInlineRoot(root, target) {
    if (
      target.placement === 'before' &&
      target.anchor &&
      target.anchor.parentElement
    ) {
      target.anchor.insertAdjacentElement('beforebegin', root);
      return true;
    }

    if (
      target.placement === 'after' &&
      target.anchor &&
      target.anchor.parentElement
    ) {
      target.anchor.insertAdjacentElement('afterend', root);
      return true;
    }

    if (target.placement === 'prepend' && target.container) {
      target.container.insertBefore(root, target.container.firstChild || null);
      return true;
    }

    return false;
  }

  function onLauncherClick(event) {
    event.stopImmediatePropagation();
    event.preventDefault();
    event.stopPropagation();

    if (Date.now() < state.suppressClickUntil) {
      return;
    }

    if (!state.menu || !state.launcher) {
      return;
    }

    if (state.menu.hidden) {
      openMenu();
      return;
    }

    closeMenu();
  }

  function onLauncherPointerDown(event) {
    if (
      !isFloatingRoot() ||
      event.button !== 0 ||
      !state.root ||
      !state.launcher
    ) {
      return;
    }

    const rect = state.root.getBoundingClientRect();
    setFabPosition(rect.left, rect.top, false);
    clearTimeout(state.hideTimer);
    showFloatingRoot();

    state.drag.active = true;
    state.drag.moved = false;
    state.drag.pointerId = event.pointerId;
    state.drag.startX = event.clientX;
    state.drag.startY = event.clientY;
    state.drag.originX = rect.left;
    state.drag.originY = rect.top;

    state.root.classList.add('Burraq-root--dragging');
    if (state.launcher.setPointerCapture) {
      state.launcher.setPointerCapture(event.pointerId);
    }
  }

  function onLauncherPointerMove(event) {
    if (!state.drag.active || event.pointerId !== state.drag.pointerId) {
      return;
    }

    const deltaX = event.clientX - state.drag.startX;
    const deltaY = event.clientY - state.drag.startY;
    if (!state.drag.moved && Math.hypot(deltaX, deltaY) < DRAG_THRESHOLD_PX) {
      return;
    }

    state.drag.moved = true;
    event.preventDefault();
    event.stopPropagation();
    setFabPosition(
      state.drag.originX + deltaX,
      state.drag.originY + deltaY,
      false,
    );
  }

  function onLauncherPointerEnd(event) {
    if (!state.drag.active || event.pointerId !== state.drag.pointerId) {
      return;
    }

    if (
      state.launcher &&
      state.launcher.releasePointerCapture &&
      state.launcher.hasPointerCapture &&
      state.launcher.hasPointerCapture(event.pointerId)
    ) {
      state.launcher.releasePointerCapture(event.pointerId);
    }

    if (state.drag.moved && state.root) {
      const rect = state.root.getBoundingClientRect();
      setFabPosition(rect.left, rect.top, true);
      state.suppressClickUntil = Date.now() + 250;
      event.preventDefault();
      event.stopPropagation();
    }

    state.drag.active = false;
    state.drag.moved = false;
    state.drag.pointerId = null;

    if (state.root) {
      state.root.classList.remove('Burraq-root--dragging');
    }

    scheduleFloatingHide();
  }

  function openMenu() {
    updateCurrentVideoContext();
    if (!state.menu || !state.launcher) {
      return;
    }

    showFloatingRoot();
    state.menu.hidden = false;
    positionFloatingElement(state.menu, 10);
    state.launcher.setAttribute('aria-expanded', 'true');

    requestAnimationFrame(() => {
      if (state.menu) {
        state.menu.classList.add('Burraq-menu--open');
      }
    });

    bindMenuDismissListeners();
  }

  function closeMenu() {
    if (!state.menu || state.menu.hidden) {
      return;
    }

    state.menu.classList.remove('Burraq-menu--open');
    if (state.launcher) {
      state.launcher.setAttribute('aria-expanded', 'false');
    }

    if (typeof state.menuListenersCleanup === 'function') {
      state.menuListenersCleanup();
      state.menuListenersCleanup = null;
    }

    const menu = state.menu;
    window.setTimeout(() => {
      if (
        menu === state.menu &&
        !menu.classList.contains('Burraq-menu--open')
      ) {
        menu.hidden = true;
      }
    }, 160);

    scheduleFloatingHide();
  }

  function bindMenuDismissListeners() {
    if (state.menuListenersCleanup) {
      return;
    }

    const handlePointerDown = event => {
      const target = event.target;
      if (
        (state.root && state.root.contains(target)) ||
        (state.overlay && state.overlay.contains(target))
      ) {
        return;
      }
      closeMenu();
    };

    const handleKeyDown = event => {
      if (event.key === 'Escape') {
        closeMenu();
      }
    };

    const handleViewportChange = () => {
      closeMenu();
    };

    document.addEventListener('mousedown', handlePointerDown, true);
    document.addEventListener('touchstart', handlePointerDown, true);
    document.addEventListener('keydown', handleKeyDown, true);
    document.addEventListener('scroll', handleViewportChange, true);
    window.addEventListener('resize', handleViewportChange, true);

    state.menuListenersCleanup = () => {
      document.removeEventListener('mousedown', handlePointerDown, true);
      document.removeEventListener('touchstart', handlePointerDown, true);
      document.removeEventListener('keydown', handleKeyDown, true);
      document.removeEventListener('scroll', handleViewportChange, true);
      window.removeEventListener('resize', handleViewportChange, true);
    };
  }

  async function onOptionClick(event) {
    event.stopImmediatePropagation();
    event.preventDefault();
    event.stopPropagation();

    if (!state.info || !state.launcher || !state.launcherLabel) {
      return;
    }

    const button = event.currentTarget;
    const option = DEVICE_OPTIONS.find(
      item => item.deviceType === button.dataset.deviceType,
    );
    if (!option) {
      return;
    }

    const payload = {
      url: sanitizeMediaUrl(state.currentUrl),
      title: state.currentTitle || 'Untitled',
      device_type: option.deviceType,
      download_type: option.downloadType,
      is_playlist: false,
      quality: option.quality,
      format: option.format,
    };

    if (!payload.url) {
      showToast('No media URL detected on this page.', 'error');
      closeMenu();
      return;
    }

    setBusyState(button, true);
    showToast(
      'Downloading ' +
        truncateText(payload.title, 28) +
        ' as ' +
        option.label +
        '...',
      'success',
    );
    window.setTimeout(() => {
      closeMenu();
    }, MENU_CLOSE_DELAY_MS);

    try {
      const response = await sendRuntimeMessage({
        type: DOWNLOAD_MESSAGE,
        payload: payload,
      });

      if (!response || !response.ok) {
        throw new Error(response?.error || 'Unable to queue this download.');
      }
    } catch (error) {
      showToast(normalizeError(error), 'error');
    } finally {
      setBusyState(button, false);
    }
  }

  function setBusyState(button, isBusy) {
    if (!state.launcher || !state.launcherLabel) {
      return;
    }

    state.launcher.disabled = isBusy;
    state.launcher.classList.toggle('Burraq-launcher--busy', isBusy);
    state.launcherLabel.textContent = isBusy ? 'Sending...' : 'Burraq';

    for (const optionButton of state.optionButtons) {
      optionButton.disabled = isBusy;
      optionButton.classList.toggle(
        'is-pending',
        isBusy && optionButton === button,
      );
    }
  }

  function showToast(message, tone) {
    if (!state.toast) {
      return;
    }

    showFloatingRoot();
    clearTimeout(state.toastTimer);
    state.toast.hidden = false;
    state.toast.className = 'Burraq-toast Burraq-toast--' + tone;
    state.toast.textContent = message;
    positionFloatingElement(state.toast, 12);

    requestAnimationFrame(() => {
      if (state.toast) {
        state.toast.classList.add('Burraq-toast--visible');
      }
    });

    state.toastTimer = window.setTimeout(() => {
      hideToast();
    }, TOAST_DURATION_MS);
  }

  function hideToast(immediate) {
    if (!state.toast) {
      return;
    }

    clearTimeout(state.toastTimer);
    state.toastTimer = 0;

    if (immediate) {
      state.toast.classList.remove('Burraq-toast--visible');
      state.toast.hidden = true;
      return;
    }

    state.toast.classList.remove('Burraq-toast--visible');
    const toast = state.toast;
    window.setTimeout(() => {
      if (
        toast === state.toast &&
        !toast.classList.contains('Burraq-toast--visible')
      ) {
        toast.hidden = true;
      }
    }, 180);

    scheduleFloatingHide();
  }

  function positionFloatingElement(element, offset) {
    if (!state.launcher) {
      return;
    }

    const viewportPadding = 12;
    const buttonRect = state.launcher.getBoundingClientRect();
    const elementRect = element.getBoundingClientRect();

    let top = buttonRect.bottom + offset;
    if (top + elementRect.height > window.innerHeight - viewportPadding) {
      top = Math.max(
        viewportPadding,
        buttonRect.top - elementRect.height - offset,
      );
    }

    let left = buttonRect.right - elementRect.width;
    if (left < viewportPadding) {
      left = viewportPadding;
    }
    if (left + elementRect.width > window.innerWidth - viewportPadding) {
      left = window.innerWidth - elementRect.width - viewportPadding;
    }

    element.style.top = Math.round(top) + 'px';
    element.style.left = Math.round(left) + 'px';
  }

  function cleanup() {
    clearTimeout(state.injectTimer);
    clearTimeout(state.hideTimer);
    state.injectTimer = 0;
    state.hideTimer = 0;

    if (typeof state.menuListenersCleanup === 'function') {
      state.menuListenersCleanup();
      state.menuListenersCleanup = null;
    }

    hideToast(true);

    if (state.root) {
      state.root.remove();
    }
    if (state.overlay) {
      state.overlay.remove();
    }

    state.root = null;
    state.overlay = null;
    state.launcher = null;
    state.launcherLabel = null;
    state.menu = null;
    state.toast = null;
    state.optionButtons = [];
    state.info = null;
    state.mode = 'inline';
    state.suppressClickUntil = 0;
    state.drag.active = false;
    state.drag.moved = false;
    state.drag.pointerId = null;
  }

  function handleUrlChange() {
    if (location.href === state.lastUrl) {
      if (!state.root || !state.root.isConnected) {
        scheduleInject(250);
      }
      return;
    }

    state.lastUrl = location.href;
    state.retryCount = 0;
    cleanup();

    // YouTube SPA needs a slightly longer delay to let the title DOM render
    const isYT = /(^|.)youtube.com$|(^|.)youtu.be$/.test(location.hostname);
    scheduleInject(isYT ? 800 : 500);
  }

  function refreshOverlayTitle(info) {
    if (state.overlay) {
      const subtitle = state.overlay.querySelector('.Burraq-menu__subtitle');
      if (subtitle) {
        subtitle.textContent =
          info.siteName + ' \u2022 ' + truncateText(info.title, 48);
      }
    }
  }

  function sendRuntimeMessage(message) {
    return new Promise((resolve, reject) => {
      try {
        chrome.runtime.sendMessage(message, response => {
          const runtimeError = chrome.runtime.lastError;
          if (runtimeError) {
            reject(new Error(runtimeError.message));
            return;
          }
          resolve(response);
        });
      } catch (error) {
        reject(error);
      }
    });
  }

  function normalizeError(error) {
    const message =
      error instanceof Error ? error.message : String(error || '');
    if (!message) {
      return 'Unable to reach the Burraq server.';
    }
    return message;
  }

  function updateCurrentVideoContext() {
    state.currentUrl = window.location.href;
    const titleElement =
      document.querySelector('ytd-watch-metadata h1 yt-formatted-string') ||
      document.querySelector('#title yt-formatted-string') ||
      document.querySelector('h1 yt-formatted-string') ||
      document.querySelector(
        '.ytd-video-primary-info-renderer h1 yt-formatted-string',
      ) ||
      document.querySelector(
        'h1.title.style-scope.ytd-video-primary-info-renderer',
      );
    state.currentTitle = titleElement
      ? titleElement.textContent.trim()
      : document.title;
    console.log('Burraq: Context synchronized for:', state.currentTitle);
  }

  function truncateText(value, maxLength) {
    if (!value || value.length <= maxLength) {
      return value || '';
    }
    return value.slice(0, maxLength - 1) + '\u2026';
  }

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function installNavigationHooks() {
    const methods = ['pushState', 'replaceState'];

    for (const methodName of methods) {
      const original = history[methodName];
      if (typeof original !== 'function') {
        continue;
      }

      history[methodName] = function () {
        const result = original.apply(this, arguments);
        window.setTimeout(handleUrlChange, 0);
        return result;
      };
    }

    window.addEventListener('popstate', handleUrlChange, true);
    window.addEventListener('hashchange', handleUrlChange, true);
    window.addEventListener(
      'yt-navigate-finish',
      updateCurrentVideoContext,
      true,
    );
    document.addEventListener(
      'fullscreenchange',
      refreshFloatingVisibility,
      true,
    );
    document.addEventListener('mousemove', handleMouseActivity, true);
  }

  function loadStoredFabPosition() {
    chrome.storage.local.get([FAB_POSITION_KEY], result => {
      const saved = result ? result[FAB_POSITION_KEY] : null;
      if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
        state.fabPosition = { x: saved.x, y: saved.y };
      } else {
        state.fabPosition = null;
      }

      if (state.mode === 'fab') {
        applyStoredFabPosition();
        refreshFloatingVisibility();
      }
    });
  }

  function isFloatingRoot() {
    return Boolean(state.root && state.mode === 'fab');
  }

  function applyStoredFabPosition() {
    if (!isFloatingRoot()) {
      return;
    }

    const rect = state.root.getBoundingClientRect();
    const fallback = {
      x: window.innerWidth - rect.width - 20,
      y: window.innerHeight - rect.height - 20,
    };
    const next = state.fabPosition || fallback;
    setFabPosition(next.x, next.y, false);
  }

  function clampFabPosition(x, y) {
    if (!state.root) {
      return { x: 20, y: 20 };
    }

    const rect = state.root.getBoundingClientRect();
    const width = rect.width || 160;
    const height = rect.height || 46;
    const minX = 12;
    const minY = 12;
    const maxX = Math.max(minX, window.innerWidth - width - 12);
    const maxY = Math.max(minY, window.innerHeight - height - 12);

    return {
      x: Math.min(maxX, Math.max(minX, x)),
      y: Math.min(maxY, Math.max(minY, y)),
    };
  }

  function setFabPosition(x, y, persist) {
    if (!isFloatingRoot()) {
      return;
    }

    const next = clampFabPosition(x, y);
    state.fabPosition = next;
    state.root.style.left = Math.round(next.x) + 'px';
    state.root.style.top = Math.round(next.y) + 'px';
    state.root.style.right = 'auto';
    state.root.style.bottom = 'auto';

    if (persist) {
      chrome.storage.local.set({
        [FAB_POSITION_KEY]: {
          x: next.x,
          y: next.y,
        },
      });
    }
  }

  function shouldAutoHideFloatingRoot() {
    return Boolean(isFloatingRoot() && document.fullscreenElement);
  }

  function showFloatingRoot() {
    if (!isFloatingRoot()) {
      return;
    }
    state.root.classList.add('Burraq-root--visible');
  }

  function hideFloatingRoot() {
    if (!isFloatingRoot() || !shouldAutoHideFloatingRoot()) {
      return;
    }
    state.root.classList.remove('Burraq-root--visible');
  }

  function scheduleFloatingHide() {
    clearTimeout(state.hideTimer);
    state.hideTimer = 0;

    if (!shouldAutoHideFloatingRoot()) {
      return;
    }

    state.hideTimer = window.setTimeout(() => {
      if (state.drag.active || (state.menu && !state.menu.hidden)) {
        return;
      }
      hideFloatingRoot();
    }, IDLE_HIDE_DELAY_MS);
  }

  function handleMouseActivity() {
    if (!shouldAutoHideFloatingRoot()) {
      return;
    }

    showFloatingRoot();
    scheduleFloatingHide();
  }

  function refreshFloatingVisibility() {
    if (!isFloatingRoot()) {
      return;
    }

    applyStoredFabPosition();

    if (shouldAutoHideFloatingRoot()) {
      state.root.classList.add('Burraq-root--autohide');
      showFloatingRoot();
      scheduleFloatingHide();
      return;
    }

    clearTimeout(state.hideTimer);
    state.hideTimer = 0;
    state.root.classList.remove('Burraq-root--autohide');
    state.root.classList.add('Burraq-root--visible');
  }

  function boot() {
    installNavigationHooks();
    loadStoredFabPosition();

    const observer = new MutationObserver(() => {
      handleUrlChange();
    });

    if (document.documentElement) {
      observer.observe(document.documentElement, {
        childList: true,
        subtree: true,
      });
    }

    scheduleInject(document.readyState === 'complete' ? 400 : 700);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }
})();
