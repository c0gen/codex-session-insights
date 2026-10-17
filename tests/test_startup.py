"""Windowed executables must report failures even without terminal streams."""
import sys

from codex_insights import cli, desktop, launcher


def test_windowed_startup_failure_is_logged_and_displayed(tmp_path, monkeypatch):
    def fail(_):
        raise ImportError("Native startup dependency could not be loaded")
    messages = []
    monkeypatch.setattr(cli, "main", fail)
    monkeypatch.setattr(launcher, "show_startup_error", lambda error, path: messages.append((str(error), path)))
    with monkeypatch.context() as frozen:
        frozen.setattr(sys, "stdout", None)
        frozen.setattr(sys, "stderr", None)
        assert launcher.launch(["--data-dir", str(tmp_path)]) == 1
    content = (tmp_path / "startup.log").read_text(encoding="utf-8")
    assert "Traceback" in content and "Native startup dependency" in content
    assert len(messages) == 1 and messages[0][1] == tmp_path / "startup.log"


def test_headless_failure_reports_error_without_a_desktop_dialog(tmp_path, monkeypatch):
    def fail(_):
        raise ValueError("Invalid snapshot")
    monkeypatch.setattr(cli, "main", fail)
    monkeypatch.setattr(launcher, "show_startup_error", lambda *_: (_ for _ in ()).throw(AssertionError("Unexpected dialog")))
    assert launcher.launch(["--data-dir", str(tmp_path), "import", "example.codex-insights"]) == 1
    assert "Invalid snapshot" in (tmp_path / "startup.log").read_text(encoding="utf-8")


def test_prerequisite_diagnostics_never_initialize_or_scan_the_index(monkeypatch):
    def unexpected(*_):
        raise AssertionError("Diagnostics should not read sessions or create an index")
    monkeypatch.setattr(cli, "Engine", unexpected)
    monkeypatch.setattr(desktop, "diagnose", lambda: {"ok": True})
    assert cli.main(["--diagnose"]) == 0
