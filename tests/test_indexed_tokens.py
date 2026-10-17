import json

from codex_insights.ingestion import refresh
from codex_insights.projection import rebuild_projection
from codex_insights.queries import dashboard
from codex_insights.report import export_html
from codex_insights.storage import Store
from conftest import log, token


def transcript(sid, usage):
    return json.dumps({"sessionId": sid, "timestamp": "2026-10-11T12:00:00Z", "type": "assistant",
                       "requestId": sid, "uuid": sid, "message": {"id": sid, "model": "claude-sonnet-4-6", "usage": usage}}) + "\n"


def mixed_store(tmp_path):
    store = Store(tmp_path / "data")
    store.set_setting("timezone", "UTC")
    sources = {}
    for provider in ("codex", "claude_code", "antigravity"):
        root = tmp_path / provider
        root.mkdir()
        sources[provider] = store.add_source(root, provider=provider)
        path = root / "s.jsonl" if provider != "antigravity" else root / "s/.system_generated/logs/transcript.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        if provider == "codex":
            path.write_bytes(log("codex") + token(100))
        else:
            path.write_text(transcript(provider, {"input_tokens": 100, "output_tokens": 10,
                "cache_read_input_tokens": 20, "cache_creation_input_tokens": 30}), encoding="utf-8")
    refresh(store)
    return store, sources


def test_all_time_provider_totals_ignore_filters_and_match_both_storage_tables(tmp_path):
    store, sources = mixed_store(tmp_path)
    expected = {provider: {"total_tokens": total, "state": "complete", "sessions": 1}
                for provider, total in (("codex", 110), ("claude_code", 160), ("antigravity", 160))}
    for bucket_version in (1, 0):
        store.set_setting("bucket_version", bucket_version)
        assert dashboard(store)["indexed_token_totals"] == expected
        filtered = dashboard(store, {"range": "custom", "start": "2026-10-01", "end": "2026-10-01",
            "provider": "codex", "source_id": sources["codex"], "model": "gpt-5.3-codex"})
        assert filtered["summary"]["total_tokens"] == 110
        assert filtered["indexed_token_totals"] == expected
        assert dashboard(store, {"project_id": "not-a-project"})["indexed_token_totals"] == expected


def test_disabled_sources_are_excluded_without_changing_other_providers(tmp_path):
    store, sources = mixed_store(tmp_path)
    with store.lock, store.connect() as db:
        db.execute("UPDATE sources SET enabled=0 WHERE id=?", (sources["claude_code"],))
    rebuild_projection(store)
    totals = dashboard(store)["indexed_token_totals"]
    assert totals["claude_code"] == {"total_tokens": None, "state": "unavailable", "sessions": 0}
    assert totals["antigravity"]["total_tokens"] == 160
    assert totals["codex"]["total_tokens"] == 110


def test_missing_zero_partial_and_copied_provider_counters(tmp_path):
    store = Store(tmp_path / "data")
    root = tmp_path / "claude"
    root.mkdir()
    store.add_source(root, provider="claude_code")
    (root / "missing.jsonl").write_text(transcript("missing", {}), encoding="utf-8")
    refresh(store)
    assert dashboard(store)["indexed_token_totals"]["claude_code"] == {"total_tokens": None, "state": "unavailable", "sessions": 1}
    zero = transcript("zero", {"input_tokens": 0, "output_tokens": 0})
    (root / "zero.jsonl").write_text(zero, encoding="utf-8")
    refresh(store)
    total = dashboard(store)["indexed_token_totals"]["claude_code"]
    assert total["total_tokens"] == 0 and total["state"] == "partial"
    known = transcript("known", {"input_tokens": 100, "output_tokens": 10})
    (root / "known.jsonl").write_text(known, encoding="utf-8")
    (root / "copy.jsonl").write_text(known, encoding="utf-8")
    refresh(store)
    total = dashboard(store)["indexed_token_totals"]["claude_code"]
    assert total["total_tokens"] == 110 and total["state"] == "partial"


def test_filtered_offline_report_omits_global_totals(tmp_path, monkeypatch):
    store, _ = mixed_store(tmp_path)
    front = tmp_path / "ui"
    front.mkdir()
    (front / "index.html").write_text("<html><head></head><body></body></html>", encoding="utf-8")
    monkeypatch.setattr("codex_insights.report.ui_directory", lambda: front)
    report = tmp_path / "report.html"
    data = dashboard(store, {"provider": "codex"})
    export_html(data, report)
    assert "indexed_token_totals" not in report.read_text(encoding="utf-8")
    assert data["indexed_token_totals"]["claude_code"]["total_tokens"] == 160
