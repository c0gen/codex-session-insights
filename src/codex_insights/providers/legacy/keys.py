"""Retired key-access entry points; constants validate existing portable provenance."""
from contextlib import contextmanager
from .discovery import LegacyError

READER_SHA256 = "48216be7ac2a66fd2d7021a3fde8db35f60ddb9cef6b652729ec38dbd7932637"
DECODER_VERSION = "antigravity-go-48216be7-v1"


@contextmanager
def reader_key(reader=None):
    raise LegacyError("legacy_collection_disabled")
    yield


@contextmanager
def windows_profile_key(profile):
    raise LegacyError("legacy_collection_disabled")
    yield
