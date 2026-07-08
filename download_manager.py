"""
Burraq download and conversion manager.
"""

from __future__ import annotations

import asyncio
import logging
import platform
import sqlite3
import subprocess
import threading
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from converter import ConversionCancelledError, FileConverter
from utils import auto_update_ytdlp, find_ffmpeg, find_ytdlp_binary, get_download_directory, get_data_path, get_resource_path, load_config

logger = logging.getLogger(__name__)

try:
    import yt_dlp

    _YTDLP_VERSION = yt_dlp.version.__version__
    logger.info("yt-dlp library loaded v%s", _YTDLP_VERSION)
except ImportError:
    yt_dlp = None
    _YTDLP_VERSION = "not installed"
    logger.warning("yt-dlp library not found, falling back to binary when available")


# Supported formats for metadata/thumbnail embedding
SUPPORTED_METADATA_FORMATS = {"mp4", "mkv", "mp3", "m4a", "mov", "avi"}
UNSUPPORTED_METADATA_FORMATS = {"webm", "flac", "wav", "opus", "3gp"}


@dataclass
class DownloadTask:
    task_id: str
    url: str
    title: str
    download_type: str
    quality: str
    format_type: str
    is_playlist: bool
    status: str = "Queued"
    progress: float = 0.0
    speed: str = "--"
    eta: str = "--"
    file_path: Optional[str] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=datetime.now)
    task_kind: str = "download"
    source_path: Optional[str] = None
    source_size: Optional[int] = None
    preset_key: Optional[str] = None
    output_format: Optional[str] = None
    cancel_requested: bool = False
    embed_metadata: bool = True
    download_subtitles: bool = False
    legacy_mode: bool = False
    speed_limit: Optional[int] = None  # KB/s, None = unlimited
    retry_count: int = 0
    max_retries: int = 3
    file_type: str = "video"  # For history filtering: "video", "audio", "playlist"
    uploader: Optional[str] = None  # Channel/Author name
    thumbnail: Optional[str] = None  # Thumbnail URL


class DownloadManager:
    MAX_CONCURRENT = 3
    HISTORY_LIMIT = 40
    FFMPEG_CONCURRENT_LIMIT = 3  # Strict limit for FFmpeg post-processing

    def __init__(self, download_dir: Optional[Path] = None):
        self.config = load_config()
        self.download_dir: Path = download_dir or get_download_directory()
        self.download_dir.mkdir(parents=True, exist_ok=True)

        self._ffmpeg_path, ffmpeg_message = find_ffmpeg()
        self._ytdlp_binary, ytdlp_message = find_ytdlp_binary()
        self.converter = FileConverter()

        logger.info(ffmpeg_message)
        logger.info(ytdlp_message)

        self.ytdlp_version: str = _YTDLP_VERSION
        self.MAX_CONCURRENT = int(self.config.get("max_concurrent", self.MAX_CONCURRENT))
        self.queue: asyncio.Queue = asyncio.Queue()
        self.active_tasks: Dict[str, DownloadTask] = {}
        self.completed_tasks: List[DownloadTask] = []
        self.semaphore = asyncio.Semaphore(self.MAX_CONCURRENT)
        # Strict semaphore for FFmpeg post-processing to prevent CPU/GPU overload
        self.ffmpeg_semaphore = asyncio.Semaphore(self.FFMPEG_CONCURRENT_LIMIT)
        self._shutdown = False
        self._is_paused = False  # Thread-safe pause flag for system tray control
        self._conversion_processes: Dict[str, subprocess.Popen] = {}
        self._event_lock = threading.Lock()
        self._events: deque[dict] = deque(maxlen=100)
        self._auto_update_enabled = bool(self.config.get("auto_update_ytdlp", True))
        self._db_lock = threading.Lock()
        # Use get_data_path() for writable runtime data (resolves to %%APPDATA%%/Burraq in frozen mode)
        self._history_db_path = get_data_path("history.db")
        self._legacy_history_db_path = get_data_path("Burraq_history.db")
        self._migrate_legacy_history_db()
        self._init_history_db()
        self._init_analytics_db()

        logger.info(
            "DownloadManager ready dir=%s max_concurrent=%s ffmpeg_limit=%s",
            self.download_dir,
            self.MAX_CONCURRENT,
            self.FFMPEG_CONCURRENT_LIMIT,
        )

    async def add_download(
        self,
        url: str,
        download_type: str,
        is_playlist: bool,
        quality: str,
        format_type: str,
        title: str,
        embed_metadata: bool = True,
        download_subtitles: bool = False,
        legacy_mode: bool = False,
    ) -> str:
        if not is_playlist:
            url = self._strip_playlist_params(url)

        task_id = str(uuid.uuid4())[:8]
        # Determine file_type for history filtering
        file_type = "playlist" if is_playlist else download_type
        
        task = DownloadTask(
            task_id=task_id,
            url=url,
            title=title,
            download_type=download_type,
            quality=quality,
            format_type=format_type,
            is_playlist=is_playlist,
            task_kind="download",
            output_format=format_type,
            embed_metadata=embed_metadata,
            download_subtitles=download_subtitles,
            legacy_mode=legacy_mode,
            file_type=file_type,
        )
        self.active_tasks[task_id] = task
        await self.queue.put(task)
        
        # Pre-fetch metadata and broadcast to WebSocket
        try:
            loop = asyncio.get_running_loop()
            metadata = await loop.run_in_executor(None, self._extract_info, url)
            task.title = metadata.get("title", title)
            task.uploader = metadata.get("uploader")
            task.thumbnail = metadata.get("thumbnail")
            self._push_event(
                "metadata_fetched",
                task_id=task_id,
                title=metadata.get("title", title),
                uploader=metadata.get("uploader"),
                thumbnail=metadata.get("thumbnail"),
            )
        except Exception as exc:
            logger.debug("Could not pre-fetch metadata for task %s: %s", task_id, exc)
        
        self._push_event(
            "incoming_link",
            task_id=task_id,
            title=task.title,
            url=url,
            task_kind="download",
        )
        logger.info("Queued download [%s] %s", task_id, task.title)
        return task_id

    async def add_conversion(
        self,
        source_path: str,
        output_format: str,
        preset_key: str,
        title: Optional[str] = None,
    ) -> str:
        source = Path(source_path).expanduser()
        if not source.exists() or not source.is_file():
            raise FileNotFoundError(f"Source file not found: {source}")

        output_format = output_format.lower()
        preset = self.converter.get_preset(output_format, preset_key)
        source_info = self.converter.probe_source(source)

        if self.converter.is_video_format(output_format) and not source_info.get("has_video"):
            raise ValueError("Audio-only files can only be converted to video formats when video exists.")
        if self.converter.is_audio_format(output_format) and not source_info.get("has_audio"):
            raise ValueError("The selected file does not contain an audio stream.")
        if preset.requires_video and not source_info.get("has_video"):
            raise ValueError("The selected preset requires a video source file.")

        task_id = str(uuid.uuid4())[:8]
        task = DownloadTask(
            task_id=task_id,
            url=str(source),
            title=title or source.name,
            download_type="audio" if self.converter.is_audio_format(output_format) else "video",
            quality=preset.label,
            format_type=output_format,
            is_playlist=False,
            task_kind="convert",
            source_path=str(source),
            source_size=source_info.get("size"),
            preset_key=preset_key,
            output_format=output_format,
            file_type="convert",
        )
        self.active_tasks[task_id] = task
        await self.queue.put(task)
        self._push_event(
            "incoming_link",
            task_id=task_id,
            title=task.title,
            url=str(source),
            task_kind="convert",
        )
        logger.info("Queued conversion [%s] %s", task_id, source.name)
        return task_id

    def poll_events(self) -> list[dict]:
        with self._event_lock:
            events = list(self._events)
            self._events.clear()
        return events

    def total_task_count(self) -> int:
        return len(self.active_tasks) + len(self.completed_tasks)

    def storage_used_bytes(self) -> int:
        total = 0
        try:
            for path in self.download_dir.rglob("*"):
                if path.is_file():
                    total += path.stat().st_size
        except Exception as exc:
            logger.debug("Failed to compute storage usage: %s", exc)
        return total

    def run_startup_updates(self) -> Optional[dict]:
        if not self._auto_update_enabled:
            return None
        return self.auto_update_ytdlp()

    def auto_update_ytdlp(self) -> dict:
        result = auto_update_ytdlp()
        self._refresh_ytdlp_version()
        return result

    def get_download_history(self, search: str = "", limit: int = 300, file_type: str = "all", status: str = "all") -> list[dict]:
        """Get download history from database with optional filtering by file_type and status."""
        conditions = []
        params: list = []
        
        if search.strip():
            conditions.append("title LIKE ? COLLATE NOCASE")
            params.append(f"%{search.strip()}%")
        
        if file_type and file_type != "all":
            conditions.append("file_type = ?")
            params.append(file_type)
        
        if status and status != "all":
            conditions.append("status = ?")
            params.append(status)
        
        clause = "WHERE " + " AND ".join(conditions) if conditions else ""
        params.append(max(1, int(limit)))
        
        query = f"""
            SELECT id, task_id, url, title, filepath, size_bytes, completed_at, file_type, status
            FROM download_history
            {clause}
            ORDER BY completed_at DESC
            LIMIT ?
        """
        with self._db_lock:
            with sqlite3.connect(self._history_db_path) as conn:
                rows = conn.execute(query, params).fetchall()

        return [
            {
                "id": row[0],
                "task_id": row[1],
                "url": row[2],
                "title": row[3],
                "filepath": row[4],
                "size_bytes": row[5] or 0,
                "completed_at": row[6],
                "file_type": row[7] or "video",
                "status": row[8] or "completed",
            }
            for row in rows
        ]

    def delete_history_record(self, record_id: int) -> bool:
        with self._db_lock:
            with sqlite3.connect(self._history_db_path) as conn:
                result = conn.execute("DELETE FROM download_history WHERE id = ?", (int(record_id),))
                conn.commit()
                return result.rowcount > 0

    def downloaded_bytes_for_month(self, year: Optional[int] = None, month: Optional[int] = None) -> int:
        now = datetime.now()
        year = int(year or now.year)
        month = int(month or now.month)
        month_key = f"{year:04d}-{month:02d}"
        with self._db_lock:
            with sqlite3.connect(self._history_db_path) as conn:
                row = conn.execute(
                    """
                    SELECT COALESCE(SUM(size_bytes), 0)
                    FROM download_history
                    WHERE strftime('%Y-%m', completed_at) = ?
                    """,
                    (month_key,),
                ).fetchone()
        return int(row[0] or 0)

    def get_storage_analytics(self) -> dict:
        """Get storage analytics for the download directory."""
        import shutil
        
        # Get drive usage
        try:
            drive_root = self.download_dir.drive if self.download_dir.is_absolute() else str(self.download_dir.parent)
            if not drive_root:
                drive_root = str(self.download_dir)
            usage = shutil.disk_usage(drive_root)
            total_gb = usage.total / (1024 ** 3)
            free_gb = usage.free / (1024 ** 3)
            used_gb = usage.used / (1024 ** 3)
        except Exception as exc:
            logger.debug("Could not get drive usage: %s", exc)
            total_gb = free_gb = used_gb = 0

        # Get folder size and file count
        folder_size = self.storage_used_bytes()
        folder_size_gb = folder_size / (1024 ** 3)
        
        # Count files and folders
        file_count = 0
        folder_count = 0
        try:
            for path in self.download_dir.rglob("*"):
                if path.is_file():
                    file_count += 1
                elif path.is_dir():
                    folder_count += 1
        except Exception as exc:
            logger.debug("Could not count files/folders: %s", exc)

        return {
            "drive_total_gb": round(total_gb, 2),
            "drive_free_gb": round(free_gb, 2),
            "drive_used_gb": round(used_gb, 2),
            "folder_size_gb": round(folder_size_gb, 2),
            "file_count": file_count,
            "folder_count": folder_count,
        }

    def get_analytics_logs(self) -> dict:
        """Get analytics data from analytics_logs table."""
        now = datetime.now()
        today_ago = now.timestamp() - 86400
        yesterday_ago = now.timestamp() - 172800
        
        analytics = {
            "today": 0,
            "yesterday": 0,
            "format_distribution": {},
            "total_folders": 0,
        }
        
        try:
            with self._db_lock:
                with sqlite3.connect(self._history_db_path) as conn:
                    # Today's downloads
                    row = conn.execute(
                        "SELECT COUNT(*) FROM analytics_logs WHERE timestamp >= datetime(?, 'unixepoch')",
                        (today_ago,),
                    ).fetchone()
                    analytics["today"] = row[0] or 0
                    
                    # Yesterday's downloads
                    row = conn.execute(
                        "SELECT COUNT(*) FROM analytics_logs WHERE timestamp >= datetime(?, 'unixepoch') AND timestamp < datetime(?, 'unixepoch')",
                        (yesterday_ago, today_ago),
                    ).fetchone()
                    analytics["yesterday"] = row[0] or 0
                    
                    # Format distribution
                    rows = conn.execute(
                        "SELECT file_format, COUNT(*) as count FROM analytics_logs GROUP BY file_format"
                    ).fetchall()
                    analytics["format_distribution"] = {row[0]: row[1] for row in rows}
                    
                    # Total unique folders
                    row = conn.execute(
                        "SELECT COUNT(DISTINCT target_folder_path) FROM analytics_logs WHERE target_folder_path IS NOT NULL"
                    ).fetchone()
                    analytics["total_folders"] = row[0] or 0
        except Exception as exc:
            logger.debug("Could not get analytics logs: %s", exc)
        
        return analytics

    def get_history_stats(self) -> dict:
        """Get time-based download statistics from history."""
        now = datetime.now()
        one_hour_ago = now.timestamp() - 3600
        today_ago = now.timestamp() - 86400
        yesterday_ago = now.timestamp() - 172800
        
        stats = {
            "last_hour": 0,
            "today": 0,
            "yesterday": 0,
        }
        
        try:
            with self._db_lock:
                with sqlite3.connect(self._history_db_path) as conn:
                    # Last hour
                    row = conn.execute(
                        "SELECT COUNT(*) FROM download_history WHERE completed_at >= datetime(?, 'unixepoch')",
                        (one_hour_ago,),
                    ).fetchone()
                    stats["last_hour"] = row[0] or 0
                    
                    # Today
                    row = conn.execute(
                        "SELECT COUNT(*) FROM download_history WHERE completed_at >= datetime(?, 'unixepoch')",
                        (today_ago,),
                    ).fetchone()
                    stats["today"] = row[0] or 0
                    
                    # Yesterday
                    row = conn.execute(
                        "SELECT COUNT(*) FROM download_history WHERE completed_at >= datetime(?, 'unixepoch') AND completed_at < datetime(?, 'unixepoch')",
                        (yesterday_ago, today_ago),
                    ).fetchone()
                    stats["yesterday"] = row[0] or 0
        except Exception as exc:
            logger.debug("Could not get history stats: %s", exc)
        
        return stats

    async def fetch_info(self, url: str) -> dict:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._extract_info, url)

    def get_status_snapshot(self, task_id: Optional[str] = None) -> dict:
        task = self._find_task(task_id) if task_id else self._select_status_task()
        active = [self._task_to_payload(item) for item in self.active_tasks.values()]

        return {
            "queue_size": self.queue.qsize(),
            "active_downloads": len(self.active_tasks),
            "download_dir": str(self.download_dir),
            "task": self._task_to_payload(task) if task else None,
            "active_tasks": active,
        }

    async def process_queue(self):
        workers = [asyncio.create_task(self._worker(index)) for index in range(self.MAX_CONCURRENT)]
        await asyncio.gather(*workers, return_exceptions=True)

    def cancel_task(self, task_id: str) -> bool:
        task = self.active_tasks.get(task_id)
        if not task:
            return False

        task.cancel_requested = True

        if task.task_kind == "convert":
            if task.status == "Queued":
                self.active_tasks.pop(task_id, None)
                task.status = "Cancelled"
                logger.info("Cancelled queued conversion [%s]", task_id)
                return True

            task.status = "Cancelled"
            process = self._conversion_processes.get(task_id)
            if process and process.poll() is None:
                self._terminate_process(process)
            logger.info("Cancellation requested for conversion [%s]", task_id)
            return True

        self.active_tasks.pop(task_id, None)
        task.status = "Cancelled"
        self._remember_completed(task)
        logger.info("Cancelled download [%s]", task_id)
        return True

    @property
    def is_paused(self) -> bool:
        """Check if downloads are globally paused."""
        return self._is_paused

    def pause_all(self):
        """Pause all active downloads by setting pause flag."""
        self._is_paused = True
        for task in self.active_tasks.values():
            if task.status in ("Downloading", "Queued"):
                task.status = "Paused"
        self._push_event("all_paused")
        logger.info("All downloads paused")

    def resume_all(self):
        """Resume all paused downloads by re-queuing them."""
        self._is_paused = False
        paused_tasks = [t for t in self.active_tasks.values() if t.status == "Paused"]
        for task in paused_tasks:
            task.status = "Queued"
            task.cancel_requested = False
            # Re-add to queue
            self.queue.put_nowait(task)
        self._push_event("all_resumed")
        logger.info("Resumed %d downloads", len(paused_tasks))

    def set_speed_limit(self, task_id: str, limit_kb: Optional[int]) -> bool:
        """Set speed limit for a specific task (KB/s, None = unlimited)."""
        task = self.active_tasks.get(task_id)
        if not task:
            return False
        task.speed_limit = limit_kb
        return True

    def set_global_speed_limit(self, limit_kb: Optional[int]):
        """Set speed limit for all active downloads."""
        for task in self.active_tasks.values():
            task.speed_limit = limit_kb
        self._push_event("speed_limit_changed", limit=limit_kb)
        logger.info("Global speed limit set to %s KB/s", limit_kb)

    def shutdown(self):
        self._shutdown = True
        for process in list(self._conversion_processes.values()):
            if process and process.poll() is None:
                self._terminate_process(process)
        logger.info("DownloadManager shutdown requested")

    async def _worker(self, worker_id: int):
        logger.debug("Worker-%s started", worker_id)
        while not self._shutdown:
            # Check for global pause state
            if self._is_paused:
                await asyncio.sleep(1)
                continue
            
            try:
                task = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if task.status == "Cancelled" or task.cancel_requested:
                self.queue.task_done()
                continue

            async with self.semaphore:
                await self._process_task(task)

            self.queue.task_done()

        logger.debug("Worker-%s stopped", worker_id)

    async def _process_task(self, task: DownloadTask):
        try:
            if task.cancel_requested:
                raise ConversionCancelledError("Task cancelled before start")

            if task.task_kind == "convert":
                task.status = "Converting"
                task.speed = "--"
                self._push_event("task_started", task_id=task.task_id, title=task.title, task_kind=task.task_kind)
                await self._convert_local_file(task)
            else:
                task.status = "Downloading"
                self._push_event("task_started", task_id=task.task_id, title=task.title, task_kind=task.task_kind)
                if yt_dlp is not None:
                    await self._download_via_library(task)
                elif self._ytdlp_binary:
                    await self._download_via_binary(task)
                else:
                    raise RuntimeError(
                        "Neither yt-dlp library nor binary is available. Install yt-dlp with 'pip install yt-dlp'."
                    )

            if task.cancel_requested:
                raise ConversionCancelledError("Task cancelled")

            task.status = "Completed"
            task.progress = 100.0
            self._push_event("task_completed", task_id=task.task_id, title=task.title, task_kind=task.task_kind)
            logger.info("Completed [%s] %s", task.task_id, task.title)
        except ConversionCancelledError:
            task.status = "Cancelled"
            task.error = None
            if task.task_kind == "convert":
                self._remove_partial_output(task)
            self._push_event("task_cancelled", task_id=task.task_id, title=task.title, task_kind=task.task_kind)
            logger.info("Cancelled [%s] %s", task.task_id, task.title)
        except asyncio.CancelledError:
            task.status = "Cancelled"
            task.error = None
            if task.task_kind == "convert":
                self._remove_partial_output(task)
            self._push_event("task_cancelled", task_id=task.task_id, title=task.title, task_kind=task.task_kind)
            logger.info("Cancelled [%s] %s", task.task_id, task.title)
        except Exception as exc:
            task.status = "Failed"
            task.error = str(exc)
            if task.task_kind == "convert":
                self._remove_partial_output(task)
            self._push_event(
                "task_failed",
                task_id=task.task_id,
                title=task.title,
                task_kind=task.task_kind,
                error=str(exc),
            )
            logger.error("Failed [%s] %s: %s", task.task_id, task.title, exc, exc_info=True)
        finally:
            if task.status == "Completed":
                self._persist_history_record(task)
                self._log_analytics(task)
            self._remember_completed(task)
            self.active_tasks.pop(task.task_id, None)
            self._conversion_processes.pop(task.task_id, None)

    async def _convert_local_file(self, task: DownloadTask):
        loop = asyncio.get_event_loop()

        def _run_conversion() -> Path:
            if not task.source_path:
                raise RuntimeError("Missing source path for conversion task.")

            def _on_process(process: subprocess.Popen, output_path: Path):
                task.file_path = str(output_path)
                self._conversion_processes[task.task_id] = process

            def _on_progress(progress: float, speed: str):
                task.progress = progress
                task.speed = speed or "--"

            return self.converter.convert(
                source_path=task.source_path,
                output_format=task.output_format or task.format_type,
                preset_key=task.preset_key or "",
                output_dir=self.download_dir,
                progress_callback=_on_progress,
                process_callback=_on_process,
                cancel_check=lambda: task.cancel_requested,
            )

        output_path = await loop.run_in_executor(None, _run_conversion)
        task.file_path = str(output_path)
        task.progress = 100.0

    async def _download_via_library(self, task: DownloadTask):
        opts = self._build_ydl_options(task)

        def _progress_hook(data: dict):
            if data["status"] == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                downloaded = data.get("downloaded_bytes")
                if downloaded and total:
                    task.progress = downloaded / total * 100
                elif "_percent_str" in data:
                    try:
                        task.progress = float(str(data["_percent_str"]).strip().rstrip("%"))
                    except ValueError:
                        pass
                task.speed = data.get("_speed_str", "--")
                task.eta = data.get("_eta_str", "--")
            elif data["status"] == "finished":
                task.status = "Processing"
                task.progress = 100.0
                task.file_path = data.get("filename")

        opts["progress_hooks"] = [_progress_hook]
        loop = asyncio.get_event_loop()
        
        # Wrap download in FFmpeg semaphore for post-processing throttling
        async with self.ffmpeg_semaphore:
            try:
                await loop.run_in_executor(None, self._run_ydl, task.url, opts)
            except Exception as exc:
                # Log warning but don't fail - download succeeded, post-processing may have issues
                logger.warning("Download completed but post-processing had issues: %s", exc)

    def _run_ydl(self, url: str, opts: dict):
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([url])

    async def _download_via_binary(self, task: DownloadTask):
        logger.info("Using yt-dlp binary for [%s]", task.task_id)
        cmd = self._build_binary_command(task)
        loop = asyncio.get_event_loop()

        def _run_binary():
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=str(self.download_dir),
            )
            if result.returncode != 0:
                raise RuntimeError(result.stderr[:500] or "yt-dlp binary failed")

        # Wrap download in FFmpeg semaphore for post-processing throttling
        async with self.ffmpeg_semaphore:
            try:
                await loop.run_in_executor(None, _run_binary)
            except Exception as exc:
                # Log warning but don't fail - download succeeded, post-processing may have issues
                logger.warning("Download completed but post-processing had issues: %s", exc)
        task.progress = 100.0

    def _build_binary_command(self, task: DownloadTask) -> list[str]:
        cmd = [self._ytdlp_binary]

        # Add stealth headers for the binary
        headers = self._get_stealth_headers()
        for key, value in headers.items():
            cmd += ["--http-header", f"{key}:{value}"]

        # Add browser cookies if enabled - with robust error handling
        if self.config.get("browser_cookies", False):
            browser = self.config.get("browser", "chrome")
            try:
                cmd += ["--cookies-from-browser", browser]
            except Exception as exc:
                logger.warning("Failed to configure browser cookies for %s: %s. Download will proceed without cookies.", browser, exc)

        if task.download_type == "audio":
            cmd += ["-x", "--audio-format", task.format_type, "--audio-quality", task.quality]
        else:
            if task.legacy_mode:
                cmd += [
                    "-f",
                    self._build_legacy_format_selector(task.quality),
                    "--merge-output-format",
                    "mp4",
                ]
            elif task.quality == "F-video":
                cmd += [
                    "--no-post-overwrites",
                    "--no-thumbnail",
                    "--no-metadata",
                    "--no-embed-metadata",
                    "--no-embed-thumbnail",
                    "--no-subtitles",
                    "--no-embed-subs",
                ]
                cmd += [
                    "-f",
                    (
                        "bestvideo[height<=240][ext=mp4]+bestaudio[ext=m4a]/"
                        "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/"
                        "best[height<=360][ext=mp4]/bestvideo[height<=360]+bestaudio/"
                        "bestvideo[height<=420]+bestaudio/bestvideo+bestaudio/best"
                    ),
                ]
                cmd += [
                    "--postprocessor-args",
                    "-vf",
                    "scale=320:240:force_original_aspect_ratio=decrease,pad=320:240:(ow-iw)/2:(oh-ih)/2:black",
                    "-r",
                    "15",
                    "-c:v",
                    "libx264",
                    "-profile:v",
                    "baseline",
                    "-level",
                    "3.0",
                    "-preset",
                    "veryfast",
                    "-b:v",
                    "220k",
                    "-maxrate",
                    "240k",
                    "-bufsize",
                    "480k",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-ac",
                    "1",
                    "-ar",
                    "22050",
                    "-b:a",
                    "48k",
                    "-movflags",
                    "+faststart",
                    "--merge-output-format",
                    "mp4",
                ]
            elif task.quality == "best":
                # Resilient "best" format selector for binary
                cmd += ["-f", "bv*+ba/b"]
                cmd += ["--merge-output-format", task.format_type]
            else:
                # Standard quality selection with fallback chain
                height = task.quality.replace("p", "")
                cmd += ["-f", f"bestvideo[height<={height}]+bestaudio/best"]
                cmd += ["--merge-output-format", task.format_type]

        if task.download_subtitles:
            cmd += ["--write-subs", "--write-auto-subs", "--sub-langs", "all"]
            if task.download_type == "video":
                cmd += ["--embed-subs"]

        if task.embed_metadata:
            cmd += ["--add-metadata", "--embed-metadata", "--write-thumbnail", "--embed-thumbnail"]

        if self._ffmpeg_path:
            cmd += ["--ffmpeg-location", str(Path(self._ffmpeg_path).parent)]

        cmd += ["-o", "%(title)s.%(ext)s"]
        if not task.is_playlist:
            cmd += ["--no-playlist"]
        cmd.append(task.url)
        return cmd

    def _build_ydl_options(self, task: DownloadTask) -> dict:
        # For playlists, create a folder named after the playlist title
        if task.is_playlist:
            out_template = str(self.download_dir / "%(playlist_title)s/%(title)s.%(ext)s")
        else:
            out_template = str(self.download_dir / "%(title)s.%(ext)s")

        opts: dict = {
            "outtmpl": out_template,
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "extract_flat": False,
            "logger": None,
            "noplaylist": not task.is_playlist,
            "writethumbnail": task.embed_metadata,
        }

        # Add permanent stealth headers
        opts["http_headers"] = self._get_stealth_headers()

        # Add browser cookies if enabled - with robust error handling
        if self.config.get("browser_cookies", False):
            browser = self.config.get("browser", "chrome")
            try:
                # Try to extract cookies from browser - this may fail if browser DB is locked
                opts["cookiesfrombrowser"] = (browser,)
                logger.info("Browser cookies enabled for: %s", browser)
            except Exception as exc:
                # Log warning but don't fail - download will proceed without cookies
                logger.warning("Failed to configure browser cookies for %s: %s. Download will proceed without cookies.", browser, exc)
                # Remove the option to prevent download failure
                opts.pop("cookiesfrombrowser", None)

        if self._ffmpeg_path:
            opts["ffmpeg_location"] = str(Path(self._ffmpeg_path).parent)

        if task.download_subtitles:
            opts["writesubtitles"] = True
            opts["writeautomaticsub"] = True
            opts["subtitleslangs"] = ["all"]
            if task.download_type == "video":
                opts["embedsubtitles"] = True

        postprocessors: list[dict] = []

        if task.download_type == "audio":
            opts["format"] = "bestaudio/best"
            postprocessors.append(
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": task.format_type,
                    "preferredquality": task.quality,
                }
            )
        else:
            if task.legacy_mode:
                opts["format"] = self._build_legacy_format_selector(task.quality)
                opts["merge_output_format"] = "mp4"
                postprocessors.append({"key": "FFmpegVideoConvertor", "preferedformat": "mp4"})
            elif task.quality == "F-video":
                opts["embedsubtitles"] = False
                opts["writeautomaticsub"] = False
                opts["writesubtitles"] = False
                opts["subtitleslangs"] = ["null"]
                opts["format"] = (
                    "bestvideo[height<=240][ext=mp4]+bestaudio[ext=m4a]/"
                    "bestvideo[height<=360][ext=mp4]+bestaudio[ext=m4a]/"
                    "best[height<=360][ext=mp4]/bestvideo[height<=360]+bestaudio/"
                    "bestvideo[height<=420]+bestaudio/bestvideo+bestaudio/best"
                )
                opts["postprocessor_args"] = [
                    "-vf",
                    "scale=320:240:force_original_aspect_ratio=decrease,pad=320:240:(ow-iw)/2:(oh-ih)/2:black",
                    "-r",
                    "15",
                    "-c:v",
                    "libx264",
                    "-profile:v",
                    "baseline",
                    "-level",
                    "3.0",
                    "-preset",
                    "veryfast",
                    "-b:v",
                    "220k",
                    "-maxrate",
                    "240k",
                    "-bufsize",
                    "480k",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-ac",
                    "1",
                    "-ar",
                    "22050",
                    "-b:a",
                    "48k",
                    "-movflags",
                    "+faststart",
                ]
                opts["merge_output_format"] = "mp4"
            elif task.quality == "best":
                # Resilient "best" format selector - bypass restrictive codec overrides
                opts["format"] = "bv*+ba/b"
                opts["merge_output_format"] = task.format_type
            else:
                # Standard quality selection with fallback chain
                height = task.quality.replace("p", "")
                opts["format"] = f"bestvideo[height<={height}]+bestaudio/best[height<={height}]"
                opts["merge_output_format"] = task.format_type

        # Intelligent metadata/thumbnail embedding
        if task.embed_metadata:
            # Check if format supports embedding
            format_lower = task.format_type.lower()
            if format_lower in SUPPORTED_METADATA_FORMATS:
                postprocessors.append({"key": "FFmpegMetadata"})
                postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})
            else:
                # For unsupported formats, log a warning but don't fail
                logger.info(
                    "Skipping metadata/thumbnail embedding for unsupported format: %s",
                    format_lower
                )

        if postprocessors:
            opts["postprocessors"] = postprocessors

        return opts

    def _get_stealth_headers(self) -> dict:
        """Return permanent stealth headers to bypass basic anti-bot protections."""
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Sec-CH-UA": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-CH-UA-Mobile": "?0",
            "Sec-CH-UA-Platform": '"Windows"',
        }

    def _extract_info(self, url: str) -> dict:
        if yt_dlp is None and not self._ytdlp_binary:
            raise RuntimeError("yt-dlp is not available for metadata lookups.")

        if yt_dlp is not None:
            with yt_dlp.YoutubeDL(
                {
                    "quiet": True,
                    "skip_download": True,
                    "extract_flat": False,
                    "noplaylist": False,
                    "no_warnings": True,
                    "http_headers": self._get_stealth_headers(),
                }
            ) as ydl:
                info = ydl.extract_info(url, download=False)
        else:
            cmd = [self._ytdlp_binary, "--dump-single-json", "--no-warnings", url]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
            if result.returncode != 0:
                raise RuntimeError(result.stderr[:300] or "yt-dlp metadata request failed")
            import json

            info = json.loads(result.stdout)

        return self._normalize_info_payload(url, info or {})

    def _normalize_info_payload(self, url: str, info: dict) -> dict:
        entries = info.get("entries") or []
        first_entry = entries[0] if entries and isinstance(entries[0], dict) else None
        source = info if info.get("title") else (first_entry or {})
        thumbnails = source.get("thumbnails") or info.get("thumbnails") or []
        best_thumb = self._pick_best_thumbnail(thumbnails) or source.get("thumbnail") or info.get("thumbnail")
        duration = source.get("duration") or info.get("duration")
        webpage_url = info.get("webpage_url") or source.get("webpage_url") or url
        extractor = info.get("extractor_key") or info.get("extractor") or source.get("extractor")

        return {
            "url": webpage_url,
            "title": source.get("title") or info.get("title") or "Untitled",
            "duration": duration,
            "duration_string": self._format_duration(duration),
            "thumbnail": best_thumb,
            "extractor": extractor,
            "is_playlist": bool(entries) or info.get("_type") == "playlist",
            "playlist_count": len(entries) if isinstance(entries, list) else 0,
            "uploader": source.get("uploader") or info.get("uploader"),
        }

    def _pick_best_thumbnail(self, thumbnails: list[dict]) -> Optional[str]:
        candidates = [item for item in thumbnails if isinstance(item, dict) and item.get("url")]
        if not candidates:
            return None
        ranked = sorted(
            candidates,
            key=lambda item: (item.get("width", 0) * item.get("height", 0), item.get("preference", 0)),
            reverse=True,
        )
        return ranked[0].get("url")

    def _find_task(self, task_id: Optional[str]) -> Optional[DownloadTask]:
        if not task_id:
            return None
        if task_id in self.active_tasks:
            return self.active_tasks[task_id]
        for task in reversed(self.completed_tasks):
            if task.task_id == task_id:
                return task
        return None

    def _select_status_task(self) -> Optional[DownloadTask]:
        if self.active_tasks:
            return sorted(self.active_tasks.values(), key=lambda item: item.created_at)[0]
        return self.completed_tasks[-1] if self.completed_tasks else None

    def _task_to_payload(self, task: Optional[DownloadTask]) -> Optional[dict]:
        if task is None:
            return None

        payload = asdict(task)
        payload["created_at"] = task.created_at.isoformat()
        payload["progress"] = round(float(task.progress or 0.0), 1)
        return payload

    def _remember_completed(self, task: DownloadTask) -> None:
        self.completed_tasks.append(task)
        if len(self.completed_tasks) > self.HISTORY_LIMIT:
            self.completed_tasks = self.completed_tasks[-self.HISTORY_LIMIT :]

    def _push_event(self, event_type: str, **payload) -> None:
        event = {
            "type": event_type,
            "timestamp": datetime.now().isoformat(),
            **payload,
        }
        with self._event_lock:
            self._events.append(event)

    def _refresh_ytdlp_version(self) -> None:
        if yt_dlp is not None:
            try:
                import importlib

                importlib.reload(yt_dlp.version)
                self.ytdlp_version = yt_dlp.version.__version__
                return
            except Exception as exc:
                logger.debug("Could not refresh yt-dlp version from library: %s", exc)

        if self._ytdlp_binary:
            try:
                result = subprocess.run(
                    [self._ytdlp_binary, "--version"],
                    capture_output=True,
                    text=True,
                    timeout=20,
                )
                if result.returncode == 0 and result.stdout.strip():
                    self.ytdlp_version = result.stdout.strip().splitlines()[0]
            except Exception as exc:
                logger.debug("Could not refresh yt-dlp version from binary: %s", exc)

    def _init_history_db(self) -> None:
        with self._db_lock:
            with sqlite3.connect(self._history_db_path) as conn:
                # Create table if it doesn't exist
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS download_history (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT,
                        url TEXT NOT NULL,
                        title TEXT NOT NULL,
                        filepath TEXT,
                        size_bytes INTEGER DEFAULT 0,
                        completed_at TEXT NOT NULL,
                        file_type TEXT DEFAULT 'video',
                        status TEXT DEFAULT 'completed'
                    )
                    """
                )
                
                # Migration: Add missing columns to existing table
                self._migrate_history_table(conn)
                
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_download_history_completed_at ON download_history(completed_at DESC)"
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_download_history_title ON download_history(title)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_download_history_file_type ON download_history(file_type)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_download_history_status ON download_history(status)")
                conn.commit()

    def _migrate_history_table(self, conn) -> None:
        """Migrate existing history table to add missing columns."""
        try:
            # Check if file_type column exists
            cursor = conn.execute("PRAGMA table_info(download_history)")
            columns = [row[1] for row in cursor.fetchall()]
            
            # Add file_type column if missing
            if 'file_type' not in columns:
                conn.execute("ALTER TABLE download_history ADD COLUMN file_type TEXT DEFAULT 'video'")
                logger.info("Migrated history table: added file_type column")
            
            # Add status column if missing
            if 'status' not in columns:
                conn.execute("ALTER TABLE download_history ADD COLUMN status TEXT DEFAULT 'completed'")
                logger.info("Migrated history table: added status column")
        except Exception as exc:
            logger.debug("Could not migrate history table: %s", exc)

    def _init_analytics_db(self) -> None:
        """Initialize the analytics_logs table for Phase 3."""
        with self._db_lock:
            with sqlite3.connect(self._history_db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS analytics_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp TEXT NOT NULL,
                        file_format TEXT NOT NULL,
                        is_playlist_item INTEGER DEFAULT 0,
                        target_folder_path TEXT
                    )
                    """
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_analytics_timestamp ON analytics_logs(timestamp DESC)"
                )
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_analytics_format ON analytics_logs(file_format)"
                )
                conn.commit()

    def _migrate_legacy_history_db(self) -> None:
        if self._history_db_path.exists() or not self._legacy_history_db_path.exists():
            return
        try:
            self._history_db_path.write_bytes(self._legacy_history_db_path.read_bytes())
            logger.info("Migrated history DB to %s", self._history_db_path)
        except Exception as exc:
            logger.warning("Could not migrate legacy history DB: %s", exc)

    def _persist_history_record(self, task: DownloadTask) -> None:
        file_path = task.file_path or ""
        size_bytes = 0
        if file_path:
            try:
                candidate = Path(file_path)
                if candidate.exists() and candidate.is_file():
                    size_bytes = candidate.stat().st_size
            except Exception as exc:
                logger.debug("Could not read file size for history [%s]: %s", task.task_id, exc)

        with self._db_lock:
            with sqlite3.connect(self._history_db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO download_history (task_id, url, title, filepath, size_bytes, completed_at, file_type, status)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task.task_id,
                        task.url,
                        task.title or "Untitled",
                        file_path,
                        int(size_bytes),
                        datetime.now().isoformat(timespec="seconds"),
                        task.file_type,
                        "completed",
                    ),
                )
                conn.commit()

    def _log_analytics(self, task: DownloadTask) -> None:
        """Log analytics data for successful downloads (Phase 3)."""
        if not task.file_path:
            return
            
        try:
            file_path = Path(task.file_path)
            target_folder = str(file_path.parent) if file_path.parent else str(self.download_dir)
            
            with self._db_lock:
                with sqlite3.connect(self._history_db_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO analytics_logs (timestamp, file_format, is_playlist_item, target_folder_path)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            datetime.now().isoformat(timespec="seconds"),
                            task.format_type.lower(),
                            1 if task.is_playlist else 0,
                            target_folder,
                        ),
                    )
                    conn.commit()
        except Exception as exc:
            logger.debug("Could not log analytics for task [%s]: %s", task.task_id, exc)

    def _remove_partial_output(self, task: DownloadTask):
        if not task.file_path:
            return
        try:
            partial = Path(task.file_path)
            if partial.exists() and partial.is_file():
                partial.unlink()
        except Exception as exc:
            logger.debug("Could not remove partial output for %s: %s", task.task_id, exc)

    @staticmethod
    def _terminate_process(process: subprocess.Popen):
        try:
            process.terminate()
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
        except Exception:
            pass

    @staticmethod
    def _strip_playlist_params(url: str) -> str:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        params.pop("list", None)
        params.pop("index", None)
        clean_query = urlencode(params, doseq=True)
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                clean_query,
                parsed.fragment,
            )
        )

    @staticmethod
    def _format_duration(seconds: Optional[int]) -> Optional[str]:
        if seconds is None:
            return None
        total = int(seconds)
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{secs:02d}"
        return f"{minutes}:{secs:02d}"

    @staticmethod
    def _build_legacy_format_selector(quality: str) -> str:
        if quality == "best":
            height_filter = ""
        elif quality.endswith("p"):
            height_filter = f"[height<={quality[:-1]}]"
        else:
            height_filter = ""
        return (
            f"bestvideo[vcodec*=avc1][ext=mp4]{height_filter}+bestaudio[ext=m4a]/"
            f"best[ext=mp4]{height_filter}/best[vcodec*=avc1]{height_filter}/best"
        )