# Burraq Chrome Extension v3.0 — Universal Downloader

## What's new in v3

- **1000+ site support** — detects video/audio on every yt-dlp-supported site
- **Biopunk Neural HUD** — animated particle canvas, bioluminescent UI,
  2035-style design
- **Arrow dial selectors** — quality and format browsed with ◀ ▶ without
  dropdowns
- **Universal URL detection** — og:video, HTML5 `<video>`, og:image fallbacks
- **Animated server status** — pulsing dot with auto-refresh every 8 seconds

## Supported Sites (sample)

YouTube, Vimeo, Twitch, TikTok, Twitter/X, Reddit, Instagram, Facebook,
SoundCloud, Bandcamp, Dailymotion, Bilibili, Rumble, Odysee, NicoVideo, BBC,
CNN, OK.ru, VKontakte, Coub, Mixcloud, PeerTube, Brightcove, Wistia, Kaltura,
TED, Streamable, Audiomack … and 1000+ more via yt-dlp extractors.

## Installation

1. Chrome → `chrome://extensions/` → enable Developer Mode
2. **Load unpacked** → select this folder
3. Start the Python server: `Burraq`

## Server API (unchanged)

```text
POST http://localhost:9090/add-download
{
  "url": "...",
  "download_type": "video" | "audio",
  "is_playlist": false,
  "quality": "1080p" | "720p" | "best" | "320" | ...,
  "format": "mp4" | "mp3" | "mkv" | ...,
  "title": "..."
}
```

## Files

```
manifest.json   MV3 manifest — <all_urls> permissions
popup.html      HUD layout
popup.css       Biopunk neural design system
popup.js        State machine + server integration
content.js      Universal video detector (50 site patterns)
content.css     Injected button + floating notice
README.md       This file
icons/          16/48/128px PNG icons
```
