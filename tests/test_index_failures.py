import json
import re

from codex_insights import ingestion, index_failures, parser
from codex_insights.queries import dashboard
from codex_insights.report import export_html
from codex_insights.storage import Store
from conftest import event, log, token


def test_failed_signatures_survive_restart_retry_explicitly_and_preserve_history(indexed, monkeypatch):
    store, root, _ = indexed
    path = root / "chat.jsonl"
    path.write_bytes(log() + token(100))
    ingestion.refresh(store)
    with path.open("ab") as stream:
        stream.write(token(300, 6, last=200))
    original = parser.SessionParser.consume
    attempts = []

    def fail(self, raw, offset):
        attempts.append(offset)
        raise TypeError("PRIVATE PROMPT must not appear in diagnostics")

    monkeypatch.setattr(parser.SessionParser, "consume", fail)
    assert ingestion.refresh(store, automatic=True)["errors"] == 1
    assert dashboard(store)["summary"]["total_tokens"] == 110
    detail = store.sources()[0]["detail"]
    assert "TypeError" in detail and "indexing-errors.jsonl" in detail
    diagnostic = (store.directory / "indexing-errors.jsonl").read_text()
    assert "PRIVATE PROMPT" not in diagnostic and "raise TypeError" not in diagnostic
    entry = json.loads(diagnostic)
    assert entry["path"] == str(path)
    assert entry["frames"] and entry["byte_offset"] is not None

    restarted = Store(store.directory)
    assert ingestion.refresh(restarted, automatic=True)["skipped_errors"] == 1
    assert len(attempts) == 1
    assert ingestion.refresh(restarted)["errors"] == 1
    assert len(attempts) == 2
    with path.open("ab") as stream:
        stream.write(event("event_msg", {"type": "agent_message", "message": "PRIVATE RESPONSE"}, 7))
    assert ingestion.refresh(restarted, automatic=True)["errors"] == 1
    assert len(attempts) == 3

    for module in (parser, ingestion, index_failures):
        monkeypatch.setattr(module, "PARSER_VERSION", parser.PARSER_VERSION + 1 if module is parser else parser.PARSER_VERSION)
    assert ingestion.refresh(restarted, automatic=True)["errors"] == 1
    assert len(attempts) == 4
    monkeypatch.setattr(parser.SessionParser, "consume", original)
    assert ingestion.refresh(restarted)["errors"] == 0
    assert restarted.sources()[0]["detail"] == ""
    assert dashboard(restarted)["summary"]["total_tokens"] == 330
    with restarted.connect() as db:
        assert db.execute("SELECT count(*) FROM file_failures").fetchone()[0] == 0
    assert ingestion.refresh(restarted, automatic=True)["bytes_read"] == 0


def test_rebuild_retries_unchanged_failures_and_removed_files_clear_warnings(indexed, monkeypatch):
    store, root, sid = indexed
    path = root / "chat.jsonl"
    path.write_bytes(log() + token(100))
    original = parser.SessionParser.consume

    def fail(*args):
        raise TypeError("A bad record")

    monkeypatch.setattr(parser.SessionParser, "consume", fail)
    assert ingestion.refresh(store, automatic=True)["errors"] == 1
    monkeypatch.setattr(parser.SessionParser, "consume", original)
    assert ingestion.refresh(store, automatic=True, rebuild=True)["changed_files"] == 1
    assert not store.sources()[0]["detail"]
    with path.open("ab") as stream:
        stream.write(token(200, 5))
    monkeypatch.setattr(parser.SessionParser, "consume", fail)
    ingestion.refresh(store, automatic=True)
    assert store.sources()[0]["detail"]
    path.unlink()
    ingestion.refresh(store, automatic=True)
    assert not store.sources()[0]["detail"]
    assert dashboard(store)["summary"]["total_tokens"] == 110
    store.forget_source(sid)
    with store.connect() as db:
        assert not db.execute("SELECT 1 FROM file_failures").fetchone()


def test_named_reports_keep_the_warning_without_the_local_diagnostic_path(indexed, monkeypatch):
    store, root, _ = indexed
    (root / "chat.jsonl").write_bytes(log() + token(100))

    def fail(*args):
        raise TypeError("PRIVATE PROMPT")

    monkeypatch.setattr(parser.SessionParser, "consume", fail)
    ingestion.refresh(store, automatic=True)
    report = store.directory / "report.html"
    export_html(dashboard(store), report, anonymous=False)
    html = report.read_text(encoding="utf-8")
    value = json.loads(re.search(r"window.__INSIGHTS_REPORT__=(.*?);</script>", html)[1])
    assert "TypeError" in value["sources"][0]["detail"]
    assert "indexing-errors.jsonl" not in value["sources"][0]["detail"]
    assert value["sources"][0]["root"] is None
    assert "PRIVATE PROMPT" not in html


def test_unchanged_incomplete_tail_is_idle_until_the_writer_appends(indexed):
    store, root, _ = indexed
    path = root / "chat.jsonl"
    tail = token(300, 5, last=200)
    path.write_bytes(log() + token(100) + tail[:25])
    ingestion.refresh(store)
    idle = ingestion.refresh(store, automatic=True)
    assert idle["changed_files"] == idle["bytes_read"] == 0
    assert dashboard(store)["summary"]["total_tokens"] == 110
    with path.open("ab") as stream:
        stream.write(tail[25:])
    resumed = ingestion.refresh(store, automatic=True)
    assert resumed["changed_files"] == 1 and resumed["bytes_read"] == len(tail)
    assert dashboard(store)["summary"]["total_tokens"] == 330
