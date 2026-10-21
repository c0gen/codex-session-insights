"""Load the project-prepared Windows SQLite before Python imports sqlite3."""
import ctypes
import os
from pathlib import Path
import sys

_library = None


def configure():
    global _library
    if sys.platform != 'win32' or _library is not None:
        return
    if getattr(sys, 'frozen', False):
        library = Path(sys._MEIPASS) / 'sqlite3.dll'
    else:
        library = Path(os.environ.get('CODEX_INSIGHTS_SQLITE_DLL',
            Path(__file__).resolve().parents[2] / '.local-data' / 'sqlite-runtime' / 'sqlite3.dll'))
    if library.is_file():
        _library = ctypes.WinDLL(str(library.resolve()))
