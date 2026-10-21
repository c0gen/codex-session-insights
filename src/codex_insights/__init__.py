"""Local Codex usage analytics. No conversation content is exported."""
__version__ = "0.1.6"

from .sqlite_bootstrap import configure as _configure_sqlite
_configure_sqlite()
