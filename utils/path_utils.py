from __future__ import annotations

import os
import re
import sys


def get_base_path(script_file: str | None = None):
    """Get the base path for the application, working in both development and PyInstaller bundle."""
    if getattr(sys, 'frozen', False):
        # Running as PyInstaller bundle
        return os.path.dirname(sys.executable)
    else:
        # Running as normal Python script
        return os.path.dirname(os.path.abspath(script_file or __file__))


def _safe_path_part(value, fallback="default"):
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or "").strip())
    return safe.strip("._") or fallback
