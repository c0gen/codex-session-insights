"""Release gates verify the SQLite actually loaded by each shipped executable."""
import sqlite3

MINIMUM = (3, 51, 3)


def diagnostic():
    return {'version': sqlite3.sqlite_version, 'minimum': '.'.join(map(str, MINIMUM)),
            'supported': sqlite3.sqlite_version_info >= MINIMUM}


def require_supported():
    value = diagnostic()
    if not value['supported']:
        raise RuntimeError(f"Release requires SQLite {value['minimum']} or later; this runtime loads {value['version']}. "
                           'Use the pinned release Python runtime before packaging.')
    return value
