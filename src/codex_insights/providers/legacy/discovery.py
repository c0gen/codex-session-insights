"""Recognized archive locations and stable, bounded complete snapshot reads."""
import hashlib
from pathlib import Path
from uuid import UUID

MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_ARCHIVES = 10000


class LegacyError(ValueError):
    """Only fixed diagnostic codes may be exposed to logs or the UI."""


def normalize_root(root):
    path = Path(root).expanduser().resolve()
    if path.name.lower() in ("brain", "conversations"):
        path = path.parent
    if not (path / "conversations").is_dir():
        raise LegacyError("archive_root_offline")
    return path


def discover(root):
    directory = normalize_root(root) / "conversations"
    paths = []
    for path in directory.iterdir():
        if path.suffix.lower() != ".pb" or not path.is_file() or path.is_symlink():
            continue
        try:
            if str(UUID(path.stem)) != path.stem.lower():
                continue
        except ValueError:
            continue
        paths.append(path)
        if len(paths) > MAX_ARCHIVES:
            raise LegacyError("archive_count_limit")
    return sorted(paths)


def signature(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def read_snapshot(path, limit=MAX_ARCHIVE_BYTES):
    path = Path(path)
    before = path.stat()
    if before.st_size > limit:
        raise LegacyError("snapshot_size_limit")
    with path.open("rb") as stream:
        import os
        opened = os.fstat(stream.fileno())
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
    if len(data) > limit:
        raise LegacyError("snapshot_size_limit")
    if not (signature(before) == signature(opened) == signature(after) == signature(path.stat())) or len(data) != before.st_size:
        raise LegacyError("snapshot_changed_during_read")
    return data, signature(before), hashlib.sha256(data).hexdigest()
