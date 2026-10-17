"""Read one allowlisted sidebar key, retaining no titles or step payloads."""
import base64
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urlparse
from uuid import UUID

from ...parser import project_identity
from .discovery import LegacyError, signature
from .wire import message

INDEX_KEY = "antigravityUnifiedStateSync.trajectorySummaries"


def first(values, number, default=None):
    return values.get(number, [default])[0]


def time_value(raw):
    if raw is None:
        return None
    values = message(raw)
    seconds, nanos = first(values, 1), first(values, 2, 0)
    if type(seconds) is not int or type(nanos) is not int or not 0 <= nanos < 1000000000:
        raise LegacyError("invalid_timestamp")
    try:
        return datetime.fromtimestamp(seconds, timezone.utc).replace(microsecond=nanos // 1000)
    except (ValueError, OverflowError, OSError):
        raise LegacyError("invalid_timestamp") from None


def workspace(raw):
    values = message(raw or b"")
    uri = first(values, 1, b"").decode("utf-8")
    parsed = urlparse(uri)
    if parsed.scheme != "file":
        return project_identity({})
    cwd = unquote(parsed.path).lstrip("/")
    git = message(first(values, 3, b""))
    remote = first(git, 2, b"").decode("utf-8")
    return project_identity({"cwd": cwd, "git": {"repository_url": remote}})


def read_index(profile):
    path = Path(profile) / "User/globalStorage/state.vscdb"
    if not path.is_file():
        raise LegacyError("profile_index_missing")
    before = signature(path.stat())
    # Immutable read-only mode prevents SQLite from creating journals or shared
    # memory beside the user's profile. Do not silently ignore a live WAL.
    wal = path.with_name(path.name + '-wal')
    if wal.exists() and wal.stat().st_size:
        raise LegacyError('profile_index_busy')
    db = sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=2)
    try:
        db.execute("PRAGMA query_only=ON")
        row = db.execute("SELECT CASE WHEN length(value)<=16777216 THEN value END FROM ItemTable WHERE key=?", (INDEX_KEY,)).fetchone()
    finally:
        db.close()
    if signature(path.stat()) != before:
        raise LegacyError('profile_index_changed_during_read')
    if not row or row[0] is None:
        raise LegacyError("profile_index_missing")
    try:
        raw = base64.b64decode(row[0], validate=True)
        root = message(raw)
        if set(root) - {1} or len(root.get(1, [])) > 10000:
            raise LegacyError("unsupported_index")
        entries = {}
        for encoded in root.get(1, []):
            entry = message(encoded)
            sid = first(entry, 1, b"").decode("ascii")
            if str(UUID(sid)) != sid:
                raise LegacyError("invalid_index_identity")
            wrapper = message(first(entry, 2, b""))
            decoded = base64.b64decode(first(wrapper, 1, b""), validate=True)
            from .schema import validate
            unknown = set(validate(decoded, 'exa.jetski_cortex_pb.CascadeTrajectorySummary'))
            if unknown - {('exa.cortex_pb.CascadeToolConfig', n) for n in (24,26,27)}:
                raise LegacyError('unsupported_index_schema')
            payload = message(decoded)
            trajectory_id = first(payload, 4, b"").decode("ascii")
            if str(UUID(trajectory_id)) != trajectory_id or sid in entries:
                raise LegacyError("invalid_index_identity")
            # Installed CascadeTrajectorySummary confirms 3=last_modified_time,
            # 7=created_time. The community schema reverses these timestamps.
            entries[sid] = {"trajectory_id": trajectory_id, "created_at": time_value(first(payload, 7)),
                "updated_at": time_value(first(payload, 3)), **workspace(first(payload, 9))}
        return entries
    except (ValueError, TypeError, UnicodeError):
        raise LegacyError("invalid_index") from None
