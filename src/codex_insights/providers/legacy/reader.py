"""Retired encrypted-archive entry points. Historical portable facts still work."""
from .discovery import LegacyError


class SnapshotReader:
    def __init__(self, root, profile, reader=None):
        pass

    def __enter__(self):
        raise LegacyError("legacy_collection_disabled")

    def __exit__(self, *args):
        pass

    def read(self, path):
        raise LegacyError("legacy_collection_disabled")


def census(root, profile, reader=None, cancel=None):
    return {"provider": "antigravity", "format": "antigravity_legacy", "status": "disabled",
            "diagnostic": "legacy_collection_disabled", "release_gate": False,
            "archives": [], "archive_count": 0,
            "counts": {"decoded": 0, "locked": 0, "corrupt": 0, "unsupported": 0}}
