"""
Windows Registry Auto-Start Setup for Burraq
Registers the Burraq server to start automatically on Windows boot.
"""

from __future__ import annotations

import os
import platform
import sys
from pathlib import Path

if platform.system() != "Windows":
    print("Auto-start is only supported on Windows.")
    sys.exit(0)

import winreg


def get_python_executable() -> str:
    """Get the path to the Python executable."""
    return sys.executable


def get_script_path() -> str:
    """Get the path to the main.py script.
    
    In PyInstaller frozen mode, the executable IS the script.
    In development mode, returns the path to main.py.
    """
    if getattr(sys, 'frozen', False):
        # In PyInstaller bundle, sys.executable is the .exe itself
        return sys.executable
    return str(Path(__file__).parent / "main.py")


def register_startup(enabled: bool = True) -> bool:
    """
    Register or unregister Burraq from Windows startup.
    
    Args:
        enabled: True to register, False to unregister
        
    Returns:
        True if successful, False otherwise
    """
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "Burraq"
    
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_SET_VALUE) as key:
            if enabled:
                # Create command: pythonw -c "import subprocess; subprocess.run(['python', 'path/to/main.py', '--hidden'])"
                # Use pythonw to run without console window
                pythonw = sys.executable.replace("python.exe", "pythonw.exe")
                if not Path(pythonw).exists():
                    pythonw = sys.executable
                
                command = f'"{pythonw}" "{get_script_path()}" --hidden'
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, command)
                print(f"✓ Burraq registered for auto-start")
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                    print(f"✓ Burraq unregistered from auto-start")
                except FileNotFoundError:
                    print(f"ℹ Burraq was not registered")
        return True
    except Exception as e:
        print(f"✗ Failed to {'register' if enabled else 'unregister'} auto-start: {e}")
        return False


def is_registered() -> bool:
    """Check if Burraq is registered for auto-start."""
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    app_name = "Burraq"
    
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, app_name)
            return bool(value)
    except FileNotFoundError:
        return False
    except Exception:
        return False


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Burraq Windows Auto-Start Setup")
    parser.add_argument("--enable", action="store_true", help="Enable auto-start on boot")
    parser.add_argument("--disable", action="store_true", help="Disable auto-start on boot")
    parser.add_argument("--status", action="store_true", help="Check auto-start status")
    
    args = parser.parse_args()
    
    if args.status:
        status = "enabled" if is_registered() else "disabled"
        print(f"Burraq auto-start is {status}")
    elif args.enable:
        register_startup(True)
    elif args.disable:
        register_startup(False)
    else:
        # Default: show status
        status = "enabled" if is_registered() else "disabled"
        print(f"Burraq auto-start is {status}")
        print("Use --enable to register or --disable to unregister")