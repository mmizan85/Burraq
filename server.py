"""
FastAPI server for handling download requests from the Chrome extension.
Includes WebSocket support for real-time updates.
"""

from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Literal, Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Global connection manager for WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass

manager = ConnectionManager()


class DownloadRequest(BaseModel):
    """Schema for download requests from the extension."""

    url: str
    download_type: Literal["video", "audio"]
    is_playlist: bool = False
    quality: str = "1080p"
    format: str = "mp4"
    title: Optional[str] = "Untitled"
    embed_metadata: bool = True
    download_subtitles: bool = False
    legacy_mode: bool = False
    speed_limit: Optional[int] = None


class SpeedLimitRequest(BaseModel):
    """Schema for speed limit requests."""

    speed_limit: Optional[int] = None  # KB/s, None = unlimited


class SettingsRequest(BaseModel):
    """Schema for settings update requests."""

    download_dir: Optional[str] = None
    max_concurrent: Optional[int] = None


class ConfigRequest(BaseModel):
    """Schema for full configuration update requests."""

    download_dir: Optional[str] = None
    max_concurrent: Optional[int] = None
    ytdlp_path: Optional[str] = None
    ffmpeg_path: Optional[str] = None
    browser_cookies: Optional[bool] = None
    browser: Optional[str] = None
    speed_limit: Optional[int] = None
    embed_metadata: Optional[bool] = None
    embed_thumbnails: Optional[bool] = None
    auto_update: Optional[bool] = None


class InfoRequest(BaseModel):
    """Schema for metadata preview requests."""

    url: str


class DownloadResponse(BaseModel):
    """Response after queuing a download."""

    status: str
    message: str
    task_id: str


def get_static_path() -> Path:
    """Get the static files path, handling PyInstaller's _MEIPASS for embedded assets."""
    from utils import get_resource_path
    return get_resource_path("static")


def create_app(download_manager):
    """Create and configure FastAPI application."""
    app = FastAPI(
        title="Burraq Download Server",
        description="Local server for media downloads via yt-dlp",
        version="1.0.0",
    )

    # Store download manager reference for WebSocket broadcasting
    app.state.dm = download_manager
    app.state.manager = manager

    # Mount static files for the web dashboard
    static_path = get_static_path()
    if static_path.exists():
        app.mount("/static", StaticFiles(directory=str(static_path)), name="static")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/")
    async def root():
        """Redirect to web dashboard."""
        from fastapi.responses import HTMLResponse
        index_path = static_path / "index.html"
        if index_path.exists():
            return HTMLResponse(index_path.read_text())
        return {"status": "ok", "message": "Burraq server is running"}

    @app.get("/health")
    async def health_check():
        """Health check endpoint for the extension."""
        return {
            "status": "online",
            "queue_size": download_manager.queue.qsize(),
            "active_downloads": len(download_manager.active_tasks),
            "ytdlp_version": download_manager.ytdlp_version,
            "download_dir": str(download_manager.download_dir),
        }

    @app.post("/get-info")
    async def get_info(request: InfoRequest):
        """Fetch accurate media metadata via yt-dlp without downloading."""
        _validate_http_url(request.url)

        try:
            info = await download_manager.fetch_info(request.url)
            return info
        except Exception as exc:
            logger.error("Metadata lookup failed for %s: %s", request.url, exc)
            raise HTTPException(status_code=500, detail=f"Metadata lookup failed: {exc}") from exc

    @app.post("/api/download", response_model=DownloadResponse)
    async def api_download(request: DownloadRequest):
        """API endpoint for adding download - returns 202 Accepted with task_id."""
        _validate_http_url(request.url)

        try:
            task_id = await download_manager.add_download(
                url=request.url,
                download_type=request.download_type,
                is_playlist=request.is_playlist,
                quality=request.quality,
                format_type=request.format,
                title=request.title or "Untitled",
                embed_metadata=request.embed_metadata,
                download_subtitles=request.download_subtitles,
                legacy_mode=request.legacy_mode,
            )

            if request.speed_limit is not None:
                download_manager.set_speed_limit(task_id, request.speed_limit)

            return DownloadResponse(
                status="accepted",
                message="Download queued successfully",
                task_id=task_id,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Error adding download via API: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error queuing download: {exc}") from exc

    @app.post("/api/queue/add", response_model=DownloadResponse)
    async def api_queue_add(request: DownloadRequest):
        """Queue add endpoint - returns 202 Accepted with task_id."""
        _validate_http_url(request.url)

        try:
            task_id = await download_manager.add_download(
                url=request.url,
                download_type=request.download_type,
                is_playlist=request.is_playlist,
                quality=request.quality,
                format_type=request.format,
                title=request.title or "Untitled",
                embed_metadata=request.embed_metadata,
                download_subtitles=request.download_subtitles,
                legacy_mode=request.legacy_mode,
            )

            if request.speed_limit is not None:
                download_manager.set_speed_limit(task_id, request.speed_limit)

            return DownloadResponse(
                status="accepted",
                message="Download queued successfully",
                task_id=task_id,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Error adding download to queue: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error queuing download: {exc}") from exc

    @app.post("/add-download", response_model=DownloadResponse)
    async def add_download(request: DownloadRequest):
        """Add a new download task to the queue."""
        _validate_http_url(request.url)

        try:
            logger.info(
                "Download request title=%s type=%s quality=%s format=%s playlist=%s legacy=%s",
                request.title,
                request.download_type,
                request.quality,
                request.format,
                request.is_playlist,
                request.legacy_mode,
            )

            task_id = await download_manager.add_download(
                url=request.url,
                download_type=request.download_type,
                is_playlist=request.is_playlist,
                quality=request.quality,
                format_type=request.format,
                title=request.title or "Untitled",
                embed_metadata=request.embed_metadata,
                download_subtitles=request.download_subtitles,
                legacy_mode=request.legacy_mode,
            )

            # Set speed limit if provided
            if request.speed_limit is not None:
                download_manager.set_speed_limit(task_id, request.speed_limit)

            return DownloadResponse(
                status="success",
                message="Download queued successfully",
                task_id=task_id,
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Error adding download: %s", exc, exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error queuing download: {exc}") from exc

    @app.get("/status")
    async def get_status(task_id: Optional[str] = None):
        """Return queue and task progress information."""
        return download_manager.get_status_snapshot(task_id)

    @app.get("/queue")
    async def get_queue_status():
        """Get current queue status and active downloads."""
        return {
            "queue_size": download_manager.queue.qsize(),
            "active_tasks": [
                {
                    "id": task.task_id,
                    "title": task.title,
                    "status": task.status,
                    "progress": task.progress,
                    "speed": task.speed,
                    "eta": task.eta,
                    "speed_limit": task.speed_limit,
                }
                for task in download_manager.active_tasks.values()
            ],
        }

    @app.get("/history")
    async def get_history(search: str = "", limit: int = 100, file_type: str = "all", status: str = "all"):
        """Get download history from database with optional filtering."""
        return download_manager.get_download_history(search=search, limit=limit, file_type=file_type, status=status)

    @app.post("/open-folder")
    async def open_folder():
        """Open the current Burraq download directory in the OS file manager."""
        target = download_manager.download_dir
        try:
            await asyncio.to_thread(_open_directory, target)
            return {"status": "success", "path": str(target)}
        except Exception as exc:
            logger.error("Failed to open download folder %s: %s", target, exc)
            raise HTTPException(status_code=500, detail=f"Could not open folder: {exc}") from exc

    @app.delete("/cancel/{task_id}")
    async def cancel_download(task_id: str):
        """Cancel a specific download task."""
        try:
            success = download_manager.cancel_task(task_id)
            if success:
                return {"status": "success", "message": f"Task {task_id} cancelled"}
            raise HTTPException(status_code=404, detail="Task not found")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    @app.post("/pause-all")
    async def pause_all():
        """Pause all active downloads."""
        download_manager.pause_all()
        return {"status": "success", "message": "All downloads paused"}

    @app.post("/resume-all")
    async def resume_all():
        """Resume all paused downloads."""
        download_manager.resume_all()
        return {"status": "success", "message": "All downloads resumed"}

    @app.post("/speed-limit/{task_id}")
    async def set_task_speed_limit(task_id: str, request: SpeedLimitRequest):
        """Set speed limit for a specific task."""
        success = download_manager.set_speed_limit(task_id, request.speed_limit)
        if success:
            return {"status": "success", "message": f"Speed limit set to {request.speed_limit} KB/s"}
        raise HTTPException(status_code=404, detail="Task not found")

    @app.post("/speed-limit")
    async def set_global_speed_limit(request: SpeedLimitRequest):
        """Set speed limit for all active downloads."""
        download_manager.set_global_speed_limit(request.speed_limit)
        return {"status": "success", "message": f"Global speed limit set to {request.speed_limit} KB/s"}

    @app.get("/config")
    async def get_config():
        """Get full configuration for the web dashboard."""
        from utils import load_config, find_ffmpeg, find_ytdlp_binary
        config = load_config()
        ytdlp_path, _ = find_ytdlp_binary()
        ffmpeg_path, _ = find_ffmpeg()
        return {
            "download_dir": str(download_manager.download_dir),
            "max_concurrent": download_manager.MAX_CONCURRENT,
            "ytdlp_path": ytdlp_path or "",
            "ffmpeg_path": ffmpeg_path or "",
            "browser_cookies": config.get("browser_cookies", False),
            "browser": config.get("browser", "chrome"),
            "speed_limit": config.get("speed_limit", ""),
            "embed_metadata": config.get("embed_metadata", True),
            "embed_thumbnails": config.get("embed_thumbnails", True),
            "auto_update": config.get("auto_update", True),
        }

    @app.get("/analytics/storage")
    async def get_storage_analytics():
        """Get storage analytics for the download directory."""
        loop = asyncio.get_running_loop()
        analytics = await loop.run_in_executor(None, download_manager.get_storage_analytics)
        return analytics

    @app.get("/analytics/history-stats")
    async def get_history_stats():
        """Get time-based download statistics from history."""
        loop = asyncio.get_running_loop()
        stats = await loop.run_in_executor(None, download_manager.get_history_stats)
        return stats

    @app.get("/analytics/logs")
    async def get_analytics_logs():
        """Get analytics data from analytics_logs table."""
        loop = asyncio.get_running_loop()
        analytics = await loop.run_in_executor(None, download_manager.get_analytics_logs)
        return analytics

    @app.post("/config")
    async def update_config(request: ConfigRequest):
        """Update full configuration."""
        from utils import save_config, set_download_directory, load_config
        config = load_config()
        
        if request.download_dir:
            download_manager.download_dir = set_download_directory(request.download_dir)
            config["download_dir"] = request.download_dir
        if request.max_concurrent:
            download_manager.MAX_CONCURRENT = request.max_concurrent
            download_manager.semaphore = asyncio.Semaphore(request.max_concurrent)
            config["max_concurrent"] = request.max_concurrent
        if request.ytdlp_path is not None:
            config["ytdlp_path"] = request.ytdlp_path
        if request.ffmpeg_path is not None:
            config["ffmpeg_path"] = request.ffmpeg_path
        if request.browser_cookies is not None:
            config["browser_cookies"] = request.browser_cookies
        if request.browser:
            config["browser"] = request.browser
        if request.speed_limit is not None:
            config["speed_limit"] = request.speed_limit
        if request.embed_metadata is not None:
            config["embed_metadata"] = request.embed_metadata
        if request.embed_thumbnails is not None:
            config["embed_thumbnails"] = request.embed_thumbnails
        if request.auto_update is not None:
            config["auto_update"] = request.auto_update
            
        save_config(config)
        return {"status": "success", "message": "Configuration updated"}

    @app.get("/settings")
    async def get_settings():
        """Get current settings."""
        return {
            "download_dir": str(download_manager.download_dir),
            "max_concurrent": download_manager.MAX_CONCURRENT,
        }

    @app.post("/settings")
    async def update_settings(request: SettingsRequest):
        """Update settings."""
        if request.download_dir:
            from utils import set_download_directory
            download_manager.download_dir = set_download_directory(request.download_dir)
        if request.max_concurrent:
            download_manager.MAX_CONCURRENT = request.max_concurrent
            download_manager.semaphore = asyncio.Semaphore(request.max_concurrent)
        return {"status": "success", "message": "Settings updated"}

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time updates."""
        await manager.connect(websocket)
        try:
            while True:
                # Send periodic status updates
                status = download_manager.get_status_snapshot()
                events = download_manager.poll_events()
                
                await websocket.send_json({
                    "type": "status_update",
                    "data": status,
                    "events": events,
                })
                await asyncio.sleep(1.0)
        except WebSocketDisconnect:
            manager.disconnect(websocket)
        except Exception as exc:
            logger.error("WebSocket error: %s", exc)
            manager.disconnect(websocket)

    return app


def _validate_http_url(url: str) -> None:
    """Validate URL and sanitize it."""
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")
    
    # Sanitize URL - remove spaces and fix protocol
    url = url.strip()
    
    # Ensure protocol is present
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    # Validate the URL format
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise HTTPException(status_code=400, detail="Invalid URL format")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid URL format")


def _sanitize_url(url: str) -> str:
    """Sanitize URL by removing tracking parameters and fixing protocol."""
    if not url:
        return ""
    
    url = url.strip()
    
    # Remove common tracking parameters
    try:
        from urllib.parse import urlparse, urlunparse, parse_qs, urlencode
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        tracking_params = ['fbclid', 'gclid', 'utm_source', 'utm_medium', 'utm_campaign', 'utm_term', 'utm_content']
        for param in tracking_params:
            params.pop(param, None)
        clean_query = urlencode(params, doseq=True)
        url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, clean_query, parsed.fragment))
    except Exception:
        pass
    
    # Ensure protocol is present
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    return url


def _open_directory(path: Path) -> None:
    directory = str(path.resolve())
    if sys.platform.startswith("win"):
        os.startfile(directory)  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", directory])
        return
    subprocess.Popen(["xdg-open", directory])