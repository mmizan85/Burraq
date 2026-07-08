"""
Burraq System Tray Integration
Provides Windows system tray icon with control options.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

try:
    import pystray
    from PIL import Image
    TRAY_AVAILABLE = True
except ImportError:
    TRAY_AVAILABLE = False
    pystray = None
    Image = None

logger = logging.getLogger(__name__)


class SystemTrayManager:
    """Manages the system tray icon and its menu actions."""

    def __init__(self, download_manager, icon_path: Optional[Path] = None, port: int = 9090):
        self.dm = download_manager
        # Use get_resource_path for icon resolution (works in both dev and PyInstaller modes)
        if icon_path is not None:
            self.icon_path = icon_path
        else:
            from utils import get_resource_path
            self.icon_path = get_resource_path("app_icon.ico")
        self.port = port
        self._tray_icon = None  # type: ignore
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def _load_icon(self) -> Optional[object]:
        """Load the tray icon image."""
        if not TRAY_AVAILABLE:
            return None
        try:
            if self.icon_path.exists():
                return Image.open(self.icon_path)
        except Exception as exc:
            logger.warning("Could not load tray icon: %s", exc)
        return None

    def _create_fallback_icon(self) -> Optional[object]:
        """Create a fallback icon if the main icon is not available."""
        if not TRAY_AVAILABLE:
            return None
        try:
            # Create a simple cyan-colored icon
            return Image.new("RGB", (64, 64), color=(0, 212, 255))
        except Exception as exc:
            logger.warning("Could not create fallback icon: %s", exc)
            return None

    def _open_dashboard(self, _icon, _item):
        """Open the web dashboard in the default browser."""
        try:
            webbrowser.open(f"http://localhost:{self.port}")
        except Exception as exc:
            logger.error("Failed to open dashboard: %s", exc)

    def _get_pause_text(self, _icon) -> str:
        """Dynamic menu text for pause/resume based on current state."""
        try:
            if self.dm.is_paused:
                return "▶️ Resume Downloads"
            return "⏸️ Pause Downloads"
        except Exception:
            return "⏸️ Pause Downloads"

    def _toggle_pause(self, _icon, _item):
        """Toggle pause/resume state."""
        try:
            if self.dm.is_paused:
                self.dm.resume_all()
            else:
                self.dm.pause_all()
        except Exception as exc:
            logger.error("Failed to toggle pause: %s", exc)

    def _clear_finished_tasks(self, _icon, _item):
        """Clear all completed tasks from memory."""
        try:
            self.dm.completed_tasks.clear()
            self.dm._push_event("tasks_cleared")
            logger.info("Cleared finished tasks via system tray")
        except Exception as exc:
            logger.error("Failed to clear tasks: %s", exc)

    def _exit_app(self, _icon, _item):
        """Exit the Burraq application."""
        try:
            self._stop_event.set()
            if self._tray_icon:
                self._tray_icon.stop()
            self.dm.shutdown()
            # Clean up PID file from writable AppData path
            from utils import get_data_path
            pid_file = get_data_path(".Burraq.pid")
            pid_file.unlink(missing_ok=True)
        except Exception as exc:
            logger.error("Error during exit: %s", exc)
        finally:
            # Use os._exit to ensure clean termination in --noconsole mode
            import os
            os._exit(0)

    def _create_menu(self) -> object:
        """Create the system tray menu with dynamic items."""
        if not TRAY_AVAILABLE:
            return None
        
        # Create menu with dynamic text using a callable
        # pystray calls the function to get the text when menu opens
        return pystray.Menu(
            pystray.MenuItem("Open Dashboard", self._open_dashboard),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                lambda icon: "▶️ Resume Downloads" if self.dm.is_paused else "⏸️ Pause Downloads",
                self._toggle_pause
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Clear Finished Tasks", self._clear_finished_tasks),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit Burraq", self._exit_app),
        )

    def run(self) -> bool:
        """Run the system tray icon in a daemon thread. Returns True if successful."""
        if not TRAY_AVAILABLE:
            logger.warning("pystray not available, running without system tray")
            return False

        icon_image = self._load_icon()
        if icon_image is None:
            icon_image = self._create_fallback_icon()

        if icon_image is None:
            logger.warning("Could not create system tray icon")
            return False

        try:
            self._tray_icon = pystray.Icon(
                "Burraq",
                icon_image,
                "Burraq Download Manager",
                menu=self._create_menu(),
            )
        except Exception as exc:
            logger.error("Failed to create system tray icon: %s", exc)
            return False

        def run_icon():
            try:
                # Micro-sleep to ensure Windows has fully allocated the virtual process thread identifier (PID)
                time.sleep(0.5)
                self._tray_icon.run()
            except Exception as exc:
                logger.error("System tray error: %s", exc)

        self._thread = threading.Thread(target=run_icon, daemon=True)
        self._thread.start()
        logger.info("System tray started")
        return True

    def stop(self):
        """Stop the system tray icon."""
        self._stop_event.set()
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception:
                pass
        logger.info("System tray stopped")