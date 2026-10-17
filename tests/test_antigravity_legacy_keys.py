"""Retired key access must fail before inspecting a profile or executable."""
import pytest
from codex_insights.providers.legacy.discovery import LegacyError
from codex_insights.providers.legacy.keys import reader_key, windows_profile_key


@pytest.mark.parametrize("open_key", [reader_key, windows_profile_key])
def test_key_access_is_disabled_without_reading_any_files(open_key, tmp_path):
    marker = tmp_path / "Local State"
    marker.write_text("PRIVATE_CONTENT")
    with pytest.raises(LegacyError, match="legacy_collection_disabled"):
        with open_key(tmp_path):
            pytest.fail("retired collectors must not yield keys")
    assert marker.read_text() == "PRIVATE_CONTENT"
