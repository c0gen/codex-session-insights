"""Locate a bundled headless bridge without importing desktop dependencies."""
import os
import sys
from pathlib import Path


def default_command():
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-m", "codex_insights.providers.bridge"], None
    if sys.platform == "darwin":
        resources = os.environ.get("RESOURCEPATH")
        directory = Path(resources).resolve().parent / "MacOS" if resources else Path(sys.executable).resolve().parent
        executable = directory / "bridge_entry"
        return [str(executable)], executable
    if sys.platform == "win32":
        return [str(Path(sys.executable).with_name("CodexInsightsBridge.exe"))], None
    return [sys.executable], None


def require_helper(executable):
    if executable is not None and (not executable.is_file() or not os.access(executable, os.X_OK)):
        raise ValueError("The bundled provider bridge is missing or not executable. Reinstall the complete Mac exporter app. Session indexing and export remain available.")
