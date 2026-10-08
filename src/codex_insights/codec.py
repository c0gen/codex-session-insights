"""Portable JSON encoding for timestamped facts; never pickle source data."""
import hashlib
import json
import zlib
from datetime import datetime, timezone


def timestamp(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.replace(tzinfo=dt.tzinfo or timezone.utc).astimezone(timezone.utc)
    except ValueError:
        return None


def _default(value):
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, set):
        return sorted(value)
    raise TypeError(type(value).__name__)


def _hook(value):
    if set(value) == {"$datetime"}:
        result = timestamp(value["$datetime"])
        if result is None:
            raise ValueError("Invalid fact timestamp")
        return result
    return value


def dumps(value):
    return json.dumps(value, default=_default, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def loads(value):
    return json.loads(value, object_hook=_hook)


def pack(value):
    return zlib.compress(dumps(value).encode("utf-8"), 3)


def unpack(value):
    return loads(zlib.decompress(value).decode("utf-8"))


def digest(value):
    return hashlib.sha256(dumps(value).encode("utf-8", errors="surrogatepass")).hexdigest()
