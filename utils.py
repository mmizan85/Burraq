"""
Burraq utility functions.
Handles path resolution, dependency detection, formatting, configuration,
and yt-dlp update helpers.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# ── PyInstaller Resource Path Resolution ─────────────────────────────────────

def get_resource_path(relative_path: str) -> Path:
    """
    Get absolute path to a resource file/directory.
    Works for both development and PyInstaller --onefile --noconsole modes.

    In a PyInstaller bundle, assets are extracted to sys._MEIPASS.
    In development, paths are relative to this file's parent directory.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Running inside a PyInstaller bundle
        return Path(sys._MEIPASS) / relative_path
    # Running in normal Python development mode
    return Path(__file__).parent / relative_path


def get_data_path(relative_path: str) -> Path:
    """
    Get a writable path for runtime data files (config, DB, logs, PID).
    In development, uses the project directory.
    In frozen mode, uses %APPDATA%/Burraq to ensure write permissions.

    This is critical because inside a PyInstaller --onefile bundle,
    sys._MEIPASS is read-only and files cannot be written there.
    """
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        # Use %APPDATA%/Burraq for writable runtime data
        appdata = os.environ.get("APPDATA") or os.environ.get("LOCALAPPDATA") or str(Path.home())
        data_dir = Path(appdata) / "Burraq"
    else:
        # Development mode: use the project directory
        data_dir = Path(__file__).parent

    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir / relative_path


# ── Configuration File Path (writable runtime data) ──────────────────────────
CONFIG_FILE = get_data_path("Burraq_config.json")


def load_config() -> dict:
    """Load persistent configuration from disk."""
    defaults = {
        "download_dir": None,
        "max_concurrent": 3,
        "show_ui": True,
        "log_level": "INFO",
        "auto_update_ytdlp": True,
    }
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
                defaults.update(saved)
        except Exception:
            pass
    return defaults


def save_config(config: dict) -> None:
    """Persist configuration to disk."""
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as handle:
            json.dump(config, handle, indent=2)
    except Exception as exc:
        logger.warning("Could not save config: %s", exc)


def _coerce_path(value: object) -> Optional[Path]:
    """Best-effort coercion of a config/arg value into a Path."""
    if value is None:
        return None
    if isinstance(value, Path):
        return value
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        return Path(s)
    return None


def _candidate_download_dirs() -> list[Path]:
    """
    Return a list of candidate directories, in priority order.
    Must be resilient on Windows where Path.home() / ~/Downloads can be unwritable.
    """
    candidates: list[Path] = []

    # Prefer explicit user dirs when available
    userprofile = _coerce_path(os.environ.get("USERPROFILE"))
    appdata = _coerce_path(os.environ.get("APPDATA"))
    home = Path.home()

    if userprofile:
        candidates.append(userprofile / "Downloads" / "Burraq")
    if appdata:
        candidates.append(appdata / "Burraq" / "Downloads")
        candidates.append(appdata / "Burraq")
    # Also try home-based default (may still be unwritable, but kept as a candidate)
    candidates.append(home / "Downloads" / "Burraq")

    # App-local fallback (current working directory)
    candidates.append(Path.cwd() / "Burraq_downloads")

    # Finally, temp-based fallback
    try:
        import tempfile

        candidates.append(Path(tempfile.gettempdir()) / "Burraq_downloads")
    except Exception:
        pass

    # De-duplicate while preserving order
    seen: set[Path] = set()
    out: list[Path] = []
    for c in candidates:
        try:
            c = c.expanduser()
        except Exception:
            pass
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _ensure_dir(path: Path) -> Path:
    """
    Ensure `path` exists as a directory.

    If the path is invalid/uncreatable, raise an exception so the caller can try a fallback.
    """
    path = path.expanduser()
    # If it's an existing file, treat as invalid.
    if path.exists() and not path.is_dir():
        raise NotADirectoryError(str(path))
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_download_directory(override: Optional[str] = None) -> Path:
    """
    Return the download directory.

    Priority:
      1. CLI --path argument
      2. Saved config value
      3. OS-default (with robust Windows-safe fallbacks)
    """
    config = load_config()

    override_path = _coerce_path(override) if override is not None else None
    config_path = _coerce_path(config.get("download_dir")) if config else None

    # Build ordered candidate list: explicit choices first, then safe defaults.
    candidates: list[Path] = []
    if override_path is not None:
        candidates.append(override_path)
    if config_path is not None:
        candidates.append(config_path)
    candidates.extend(_candidate_download_dirs())

    last_exc: Optional[BaseException] = None
    for p in candidates:
        try:
            return _ensure_dir(p)
        except (PermissionError, NotADirectoryError, OSError) as exc:
            last_exc = exc
            logger.warning("Download directory not usable (%s): %s", type(exc).__name__, p)
            continue

    # If all candidates fail, re-raise the last exception to surface a clear error.
    if last_exc is not None:
        raise last_exc
    # Should be unreachable, but keep mypy/linters happy.
    raise RuntimeError("No download directory candidates available")


def set_download_directory(new_path: str) -> Path:
    """Persist a new download directory and return it."""
    config = load_config()
    config["download_dir"] = str(new_path)
    save_config(config)
    path = Path(new_path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _find_tool(name: str) -> Optional[str]:
    """Locate an external tool such as ffmpeg or yt-dlp."""
    found = shutil.which(name)
    if found:
        return found

    script_dir = Path(__file__).parent
    candidates = [script_dir / name, script_dir / f"{name}.exe"]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def find_ffmpeg() -> Tuple[Optional[str], str]:
    """Find ffmpeg on the system."""
    path = _find_tool("ffmpeg")
    if path:
        return path, f"ffmpeg found: {path}"
    return None, "ffmpeg NOT found - install from https://ffmpeg.org or place the binary next to server files"


def find_ytdlp_binary() -> Tuple[Optional[str], str]:
    """Find the standalone yt-dlp binary on the system."""
    path = _find_tool("yt-dlp")
    if path:
        return path, f"yt-dlp binary found: {path}"
    return None, "yt-dlp binary NOT found - will use the Python library if available"


def auto_update_ytdlp() -> dict:
    """
    Update yt-dlp using both the Python package installer and the standalone
    binary updater when present.
    """
    result = {
        "success": False,
        "library_updated": False,
        "binary_updated": False,
        "messages": [],
    }

    try:
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "-U",
                "yt-dlp",
                "--disable-pip-version-check",
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if proc.returncode == 0:
            result["success"] = True
            result["library_updated"] = True
            result["messages"].append("yt-dlp Python package updated.")
        else:
            stderr = (proc.stderr or "").strip()[:220]
            result["messages"].append(stderr or "yt-dlp Python package update failed.")
    except Exception as exc:
        result["messages"].append(f"yt-dlp package update error: {exc}")

    binary_path, _ = find_ytdlp_binary()
    if binary_path:
        try:
            proc = subprocess.run(
                [binary_path, "-U"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if proc.returncode == 0:
                result["success"] = True
                result["binary_updated"] = True
                stdout = (proc.stdout or "").strip().splitlines()
                result["messages"].append(stdout[-1] if stdout else "yt-dlp binary update completed.")
            else:
                stderr = (proc.stderr or "").strip()[:220]
                result["messages"].append(stderr or "yt-dlp binary update failed.")
        except Exception as exc:
            result["messages"].append(f"yt-dlp binary update error: {exc}")

    if not result["messages"]:
        result["messages"].append("No yt-dlp installation was found to update.")

    logger.info("auto_update_ytdlp: %s", " | ".join(result["messages"]))
    return result


def check_dependencies() -> dict:
    """Return dependency status information."""
    status = {}

    try:
        import yt_dlp as _ydl

        status["yt_dlp_library"] = _ydl.version.__version__
    except Exception:
        status["yt_dlp_library"] = False

    ytdlp_path, _ = find_ytdlp_binary()
    status["yt_dlp_binary"] = ytdlp_path or False

    ffmpeg_path, _ = find_ffmpeg()
    status["ffmpeg"] = ffmpeg_path or False

    for pkg, module in [("fastapi", "fastapi"), ("uvicorn", "uvicorn"), ("rich", "rich")]:
        try:
            __import__(module)
            status[pkg] = True
        except ImportError:
            status[pkg] = False

    return status


def format_size(bytes_size: int) -> str:
    """Convert bytes to a human-readable string."""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"


def format_time(seconds: int) -> str:
    """Convert seconds to a compact human-readable duration string."""
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"


def sanitize_filename(filename: str) -> str:
    """Strip characters that are invalid in file names on any OS."""
    for ch in '<>:"/\\|?*':
        filename = filename.replace(ch, "_")
    filename = filename.strip(". ")
    return filename[:200]


def print_dependency_status() -> bool:
    """Print a formatted dependency status table."""
    print("\nChecking Dependencies...")
    print("=" * 55)

    deps = check_dependencies()
    all_ok = True

    rows = [
        ("yt-dlp library", deps["yt_dlp_library"]),
        ("yt-dlp binary", deps["yt_dlp_binary"]),
        ("ffmpeg", deps["ffmpeg"]),
        ("fastapi", deps["fastapi"]),
        ("uvicorn", deps["uvicorn"]),
        ("rich", deps["rich"]),
    ]

    for name, value in rows:
        if value:
            label = f"OK {value}" if isinstance(value, str) else "OK"
        else:
            label = "Not found"
            if name in ("yt-dlp library", "fastapi", "uvicorn", "rich"):
                all_ok = False
        print(f"  {name:<20} {label}")

    if not all_ok:
        print("\nInstall missing Python packages: pip install -r requirements.txt")
        print("Install ffmpeg from: https://ffmpeg.org/download.html")

    print("=" * 55)
    print()
    return all_ok
