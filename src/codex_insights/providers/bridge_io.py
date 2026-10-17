"""Bounded private local writes, serialized across short-lived bridge processes."""
import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

MAX_INPUT = 1024 * 1024
MAX_HISTORY = 8 * 1024 * 1024


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".bridge-")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@contextmanager
def locked(directory):
    directory = Path(directory)
    if not directory.exists():
        from ..account_storage import protect_directory
        protect_directory(directory)
    # OS advisory locks release on process exit, including crashed clients.
    with (directory / ".lock").open("a+b") as stream:
        stream.seek(0)
        stream.write(b"0")
        stream.flush()
        deadline = time.monotonic() + 1
        while True:
            try:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("Bridge busy") from None
                time.sleep(.02)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def write_json(path, value):
    atomic_write(path, json.dumps(value, separators=(",", ":")).encode("utf-8"))
