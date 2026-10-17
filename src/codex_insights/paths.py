"""User data locations shared by the CLI and early startup diagnostics."""
import os
import platform
from pathlib import Path


def default_directory():
    override = os.environ.get("CODEX_INSIGHTS_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Codex Session Insights"
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "Codex Session Insights"
