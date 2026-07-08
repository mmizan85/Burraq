#!/usr/bin/env python3
"""
Burraq - Universal Video Downloader v1.0

Usage
-----
  Burraq              Launch with system tray icon
  Burraq --hidden     Launch without console window (background mode)

PyInstaller --noconsole Safety
--------------------------------
This file implements the following protections for windowed (headless) mode:
  1. Win32 FreeConsole() detachment early in startup chain.
  2. SafeNullStream fallback for sys.stdout/sys.stderr when console handles are absent.
  3. All writable runtime data (logs, DB, config, PID) uses get_data_path()
     which resolves to %%APPDATA%%/Burraq in compiled mode.
  4. Static assets (HTML/CSS/JS) use get_resource_path() which resolves
     to sys._MEIPASS in compiled mode.
"""
import sys
import asyncio
import logging
import argparse
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: Win32 Subsystem & Handle Patching
# ═══════════════════════════════════════════════════════════════════════════════

# -- Win32 Console Detachment --------------------------------------------------
# Must execute BEFORE any I/O operations to prevent WinError 6 (Invalid Handle)
# and standard stream AttributeError failures in --noconsole environments.
_SafeNullStream = type("_SafeNullStream", (), {
    "write": lambda self, data: None,
    "flush": lambda self: None,
    "isatty": lambda self: False,
    "read": lambda self, size=1: "",
    "readline": lambda self, size=-1: "",
    "readlines": lambda self, hint=-1: [],
    "writelines": lambda self, lines: None,
    "close": lambda self: None,
    "closed": False,
    "mode": "w",
    "name": "<null>",
    "encoding": "utf-8",
    "errors": "strict",
    "newlines": None,
    "buffer": None,
    "raw": None,
    "line_buffering": False,
})()

# Free the console window if running in --noconsole / windowed mode.
# This prevents the ghost console window from appearing.
try:
    import ctypes
    kernel32 = ctypes.windll.kernel32
    # Check if we have a console attached (GetConsoleWindow != 0)
    if kernel32.GetConsoleWindow() and not sys.stdout:
        kernel32.FreeConsole()
except Exception:
    pass

# -- NullStream Safety for --noconsole Mode ------------------------------------
# When running with --noconsole, sys.stdout/sys.stderr may be None.
# Any code calling print() or sys.stdout.write() will crash with:
#   AttributeError: 'NoneType' object has no attribute 'write'
# Force assign dummy streams to prevent this.
if sys.stdout is None:
    sys.stdout = _SafeNullStream
if sys.stderr is None:
    sys.stderr = _SafeNullStream
if sys.stdin is None:
    sys.stdin = _SafeNullStream

sys.path.insert(0, str(Path(__file__).parent))

# -- Version -------------------------------------------------------------------
VERSION      = "1.0.0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9090


# -- Logging -------------------------------------------------------------------
def _init_logging(console=False, hidden=False):
    """Initialize logging with safe stream handling and AppData path for --noconsole."""
    from utils import get_data_path

    # Log file goes to writable AppData directory (not the read-only bundle path)
    log_path = get_data_path("Burraq.log")
    handlers = [logging.FileHandler(str(log_path), encoding="utf-8")]

    # Only add StreamHandler if console is True AND we have a real stdout
    # In --noconsole mode, sys.stdout is None and we use NullStream
    if console and not hidden:
        # Check if stdout is a real stream (not our NullStream)
        if hasattr(sys.stdout, 'write') and sys.stdout is not _SafeNullStream:
            handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        handlers=handlers, force=True)

    logger = logging.getLogger(__name__)
    logger.info("Log initialized at %s", log_path)


# -- Utility: download directory -----------------------------------------------
def _setup_dir():
    from utils import get_download_directory, set_download_directory
    return get_download_directory()


# ----------------------------------------------------------------------
# GUI MODE
# ----------------------------------------------------------------------

def run(show_ui=True, hidden=False):
    _init_logging(console=not hidden and show_ui, hidden=hidden)
    from utils import get_download_directory
    from download_manager import DownloadManager
    from system_tray import SystemTrayManager, TRAY_AVAILABLE

    dl_dir = _setup_dir()
    dm = DownloadManager(download_dir=dl_dir)

    async def _main():
        from server import create_app
        import uvicorn

        app = create_app(dm)
        config = uvicorn.Config(app, host=DEFAULT_HOST, port=DEFAULT_PORT,
                                log_level="critical", access_log=False)
        srv = uvicorn.Server(config)

        if show_ui and not hidden:
            _safe_print(f"\n  Burraq {VERSION} - CLI Server")
            _safe_print(f"  ⚡  http://{DEFAULT_HOST}:{DEFAULT_PORT}")
            _safe_print(f"  📁  {dl_dir}")
            _safe_print(f"  Press Ctrl+C to stop\n")

        # Start system tray in a separate thread
        tray = SystemTrayManager(dm, port=DEFAULT_PORT)
        tray_success = tray.run()

        if not tray_success and not hidden:
            _safe_print("  ⚠️  System tray unavailable, running in console mode")

        tasks = [
            asyncio.create_task(dm.process_queue()),
            asyncio.create_task(srv.serve()),
        ]

        try:
            await asyncio.gather(*tasks)
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            dm.shutdown()
            tray.stop()
            from utils import get_data_path
            pid_file = get_data_path(".Burraq.pid")
            pid_file.unlink(missing_ok=True)

    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        if show_ui and not hidden:
            from rich.console import Console
            _safe_rich_print(Console(), "\n[#ff4b4b]🛑 Operation cancelled. Exiting Burraq...[/]")


# ----------------------------------------------------------------------
# DAEMON MODE
# ----------------------------------------------------------------------

# (Reserved for future daemon/service mode)


# ----------------------------------------------------------------------
# ENTRY POINT
# ----------------------------------------------------------------------

def _safe_print(msg: str) -> None:
    """Print without risking AttributeError in --noconsole mode."""
    try:
        print(msg)
    except Exception:
        pass


def _safe_rich_print(console, msg: str) -> None:
    """Rich console print without risking AttributeError in --noconsole mode."""
    try:
        console.print(msg)
    except Exception:
        pass


def main():
    parser = argparse.ArgumentParser(description="Burraq Download Manager")
    parser.add_argument("--hidden", action="store_true", help="Run without console window")
    args = parser.parse_args()

    # Write PID file to writable AppData path (not read-only bundle path)
    from utils import get_data_path
    pid_file = get_data_path(".Burraq.pid")
    pid_file.write_text(str(1234))

    # -- System Tray (default) ----------------------------------------------
    try:
        import tkinter
        if args.hidden:
            # Hidden mode - no console, just system tray
            run(show_ui=False, hidden=True)
        else:
            run(show_ui=True, hidden=False)

    except ImportError:
        _safe_print(" tkinter not found - falling back to CLI mode")
        run(show_ui=True, hidden=args.hidden)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        from rich.console import Console
        _safe_rich_print(Console(), "\n[#ff4b4b]🛑 Operation cancelled. Exiting Burraq...[/]")
        sys.exit(0)