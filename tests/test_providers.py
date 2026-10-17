"""Synthetic provider accounting, migration and local bridge contracts."""
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from codex_insights.codec import unpack
from codex_insights.ingestion import refresh
from codex_insights.projection import rebuild_projection
from codex_insights.providers import adapter
from codex_insights.providers.allowances import read
from codex_insights.providers.bridge import receive
from codex_insights.providers.pricing import estimate
from codex_insights.providers.setup import Setup
from codex_insights.providers.transcripts import TranscriptParser, usage_record
from codex_insights.queries import dashboard
from codex_insights.storage import Store
from codex_insights.transfers import export_snapshot, import_snapshot, validate_fact
from conftest import log, token

NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)


def line(sid="s", mid="m", output=10, **extra):
    return (json.dumps({"sessionId": sid, "timestamp": NOW.isoformat(), "type": "assistant",
        "cwd": "C:/private/project", "requestId": "request", "uuid": mid,
        "message": {"id": mid, "model": "claude-sonnet-4-6", "content": [{"type": "text", "text": "PRIVATE_RESPONSE"}],
            "usage": {"input_tokens": 100, "output_tokens": output,
                "cache_read_input_tokens": 20, "cache_creation_input_tokens": 30,
                "cache_creation": {"ephemeral_5m_input_tokens": 30, "ephemeral_1h_input_tokens": 0}}}, **extra}) + "\n").encode()


def source(store, root, provider="claude_code"):
    root.mkdir(parents=True, exist_ok=True)
    return store.add_source(root, provider=provider)


def test_fragments_copies_subagents_provider_collision_and_filters(tmp_path):
    store = Store(tmp_path / "data")
    store.set_setting("timezone", "UTC")
    root = tmp_path / "claude"
    source(store, root)
    content = line() + line(output=15)
    (root / "s.jsonl").write_bytes(content)
    # Same response copied into an independently named session is not added twice.
    (root / "copy.jsonl").write_bytes(line(sid="copy", output=15))
    agents = root / "s/subagents"
    agents.mkdir(parents=True)
    (agents / "agent-a.jsonl").write_bytes(line(mid="agent-message"))
    codex = tmp_path / "codex"
    source(store, codex, "codex")
    (codex / "s.jsonl").write_bytes(log("s") + token(100))
    gravity = tmp_path / "brain"
    source(store, gravity, "antigravity")
    transcript = gravity / "s/.system_generated/logs/transcript.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(line())  # Claude model inside Antigravity remains Antigravity.
    result = refresh(store)
    assert result["errors"] == 0
    assert dashboard(store, {"provider": "codex"})["summary"]["total_tokens"] == 110
    claude = dashboard(store, {"provider": "claude_code"})
    assert claude["summary"]["total_tokens"] == 325
    assert claude["summary"]["input_tokens"] == 300
    assert claude["summary"]["cached_tokens"] == 40
    assert claude["summary"]["cache_write_tokens"] == 60
    assert any(row["name"] == "spawned_subagent" for row in claude["agents"])
    assert dashboard(store, {"provider": "antigravity"})["summary"]["total_tokens"] == 160
    assert dashboard(store)["summary"]["total_tokens"] == 595
    with store.connect() as db:
        assert {r[0] for r in db.execute("SELECT DISTINCT provider FROM metric_buckets")} == {"codex", "claude_code", "antigravity"}
        assert b"PRIVATE_RESPONSE" not in b"".join(r[0] for r in db.execute("SELECT state FROM files"))
    assert refresh(store)["bytes_read"] == 0
    rebuild_projection(store)
    assert dashboard(store)["summary"]["total_tokens"] == 595


def test_missing_counters_explicit_zero_hidden_discovery_and_incomplete_line(tmp_path):
    store = Store(tmp_path / "data")
    root = tmp_path / "brain"
    source(store, root, "antigravity")
    path = root / "s/.system_generated/logs/transcript.jsonl"
    path.parent.mkdir(parents=True)
    missing = line(message={"id": "m", "model": "unknown", "content": []})
    path.write_bytes(missing + b"{\"timestamp\":")
    (root / "unrelated.jsonl").write_bytes(line())
    assert refresh(store)["files"] == 1
    data = dashboard(store)
    assert data["summary"]["total_tokens"] == 0
    assert data["summary"]["analyzed_tokens"] is None
    assert data["coverage"]["tokens"]["state"] == "unavailable"
    assert refresh(store)["bytes_read"] == 0
    path.write_bytes(line(message={"id": "m", "usage": {"input_tokens": 0, "output_tokens": 0}}))
    refresh(store, rebuild=True)
    # Canonical facts only accept proven extension/equal-byte histories. Use a
    # fresh source for this independent zero record rather than rewriting history.
    second = root / "zero/.system_generated/logs/transcript.jsonl"
    second.parent.mkdir(parents=True)
    second.write_bytes(line(sid="zero", message={"id": "zero-m", "usage": {"input_tokens": 0, "output_tokens": 0}}))
    refresh(store)
    assert dashboard(store)["coverage"]["tokens"]["state"] == "partial"
    assert dashboard(store)["summary"]["analyzed_tokens"] == 0


@pytest.mark.parametrize("value", [None, {}, {"input_tokens": 1}, {"input_tokens": True, "output_tokens": 2},
    {"input_tokens": -1, "output_tokens": 2}, {"input_tokens": 1, "output_tokens": 2, "cache_read_input_tokens": "3"}])
def test_invalid_usage_is_unavailable(value):
    assert usage_record(value) is None


def test_mixed_transfer_roundtrip_and_privacy(tmp_path):
    store = Store(tmp_path / "data")
    root = tmp_path / "claude"
    source(store, root)
    (root / "s.jsonl").write_bytes(line())
    codex = tmp_path / "codex"
    source(store, codex, "codex")
    (codex / "s.jsonl").write_bytes(log("s") + token(100))
    refresh(store)
    receive(store.directory, "claude_code", "status", {"rate_limits": {"five_hour": {"used_percentage": 55}}, "prompt": "PRIVATE_PROMPT"}, now=NOW)
    archive = tmp_path / "usage.codex-insights"
    export_snapshot(store, archive)
    with zipfile.ZipFile(archive) as bundle:
        assert json.loads(bundle.read("manifest.json"))["format_version"] == 5
        facts = bundle.read("facts.jsonl")
        for marker in (b"PRIVATE", b"C:/private", b"rate_limits", b"used_percentage"):
            assert marker not in facts
    target = Store(tmp_path / "target")
    import_snapshot(target, archive)
    assert dashboard(target)["summary"]["total_tokens"] == 270
    assert import_snapshot(target, archive)["status"] == "unchanged"
    assert dashboard(target, {"provider": "claude_code"})["summary"]["total_tokens"] == 160


def test_v1_remains_codex_and_exporter_identity_survives(tmp_path):
    store = Store(tmp_path / "data")
    root = tmp_path / "codex"
    source(store, root, "codex")
    (root / "s.jsonl").write_bytes(log("s") + token(100))
    refresh(store)
    original = store.setting("exporter_id")
    archive = tmp_path / "v2.zip"
    export_snapshot(store, archive)
    with zipfile.ZipFile(archive) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        facts = bundle.read("facts.jsonl")
    manifest["format_version"] = 1
    v1 = tmp_path / "v1.zip"
    with zipfile.ZipFile(v1, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest))
        bundle.writestr("facts.jsonl", facts)
    target = Store(tmp_path / "target")
    import_snapshot(target, v1)
    assert dashboard(target, {"provider": "codex"})["summary"]["total_tokens"] == 110
    assert Store(store.directory).setting("exporter_id") == original


def test_import_rejects_sensitive_nested_cache_fields_and_namespace(tmp_path):
    parser = TranscriptParser("claude_code", path=tmp_path / "s.jsonl")
    content = line()
    parser.consume(content, len(content))
    fact = parser.fact()
    assert validate_fact(fact)
    fact["raw_token_trace"][0]["cache_creation"]["prompt"] = "PRIVATE"
    with pytest.raises(ValueError, match="cache creation"):
        validate_fact(fact)
    del fact["raw_token_trace"][0]["cache_creation"]["prompt"]
    fact["provider"] = "antigravity"
    with pytest.raises(ValueError, match="namespace"):
        validate_fact(fact)


def test_allowance_zero_staleness_units_absent_and_repeated_snapshots(tmp_path):
    directory = tmp_path / "data"
    payload = {"rate_limits": {"five_hour": {"used_percentage": 0, "resets_at": NOW.timestamp() + 60},
        "seven_day": {"used_percentage": 100}, "spend_limit": {"used_usd": 0, "limit_usd": 10}},
        "context_window": {"total_input_tokens": 99999}, "prompt": "PRIVATE"}
    for _ in range(3):
        receive(directory, "claude_code", "status", payload, now=NOW)
    current = read(directory, NOW.timestamp())[0]
    assert current["status"] == "available"
    assert [b["remaining_percent"] for b in current["buckets"]] == [100, 0, None]
    assert current["buckets"][2]["unit"] == "usd" and current["buckets"][2]["used"] == 0
    assert read(directory, NOW.timestamp() + 61)[0]["status"] == "stale"
    assert read(directory, NOW.timestamp() + 301)[0]["status"] == "stale"
    assert read(directory, NOW.timestamp())[1]["status"] == "unavailable"
    receive(directory, "antigravity", "status", {"quota": {"gemini-weekly": {"remaining_fraction": 0, "reset_time": NOW.isoformat()}}}, now=NOW)
    snapshot = read(directory, NOW.timestamp())[1]
    assert snapshot["buckets"][0]["remaining_percent"] == 0 and snapshot["status"] == "stale"
    assert "PRIVATE" not in (directory / "bridge/claude_code-allowance.json").read_text()
    receive(directory, "claude_code", "status", {}, now=NOW)
    assert read(directory, NOW.timestamp())[0]["status"] == "unavailable"


def test_hook_privacy_confirmed_failed_edits_concurrent_clients(tmp_path):
    directory = tmp_path / "data"
    payload = {"conversationId": "s", "workspacePaths": ["C:/private/project"], "modelName": "unknown",
        "transcriptPath": "C:/private/transcript.jsonl", "stepIdx": 1, "error": "",
        "toolCall": {"name": "replace_file_content", "args": {"TargetContent": "a", "ReplacementContent": "b\nc", "AllowMultiple": False}},
        "prompt": "PRIVATE", "credentials": "SECRET"}
    receive(directory, "antigravity", "hook", payload, "PostToolUse", NOW)
    # Simulate restarted concurrent clients; no writes should be lost or corrupt.
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda i: receive(directory, "antigravity", "hook", {**payload, "stepIdx": i + 2, "error": "failed"}, "PostToolUse", NOW), range(12)))
    events = list((directory / "bridge/events").glob("*.jsonl"))
    content = events[0].read_bytes()
    assert len(content.splitlines()) == 13
    for marker in (b"PRIVATE", b"SECRET", b"C:/private", b"toolCall", b"ReplacementContent"):
        assert marker not in content
    store = Store(directory)
    store.add_source(directory / "bridge/events", provider="antigravity", kind="bridge")
    refresh(store)
    value = dashboard(store)
    assert value["summary"]["lines_added"] == 2 and value["summary"]["lines_removed"] == 1
    assert value["summary"]["analyzed_tokens"] is None


@pytest.mark.parametrize("target", ["claude_code", "antigravity", "antigravity_cli"])
def test_setup_preserves_and_restores_only_owned_fields(tmp_path, target):
    setup = Setup(tmp_path / "data", home=tmp_path / "home", command=["synthetic-bridge"])
    config = setup.path(target)
    config.parent.mkdir(parents=True)
    initial = {"existing-hook": {"PostInvocation": [{"command": "original"}]}} if target == "antigravity" else {"statusLine": {"type": "command", "command": "original", "padding": 2}}
    initial["unrelated"] = "keep"
    config.write_text(json.dumps(initial))
    assert not setup.preview(target)["installed"]
    assert setup.update(target, "install")["installed"]
    assert setup.update(target, "install")["installed"]  # Idempotent.
    setup.update(target, "disable")
    assert json.loads(config.read_text()) == initial
    setup.update(target, "install")
    changed = json.loads(config.read_text())
    changed["codex-session-insights" if target == "antigravity" else "statusLine"] = {"user": "changed"}
    config.write_text(json.dumps(changed))
    setup.update(target, "uninstall")
    assert json.loads(config.read_text()) == changed


def test_claude_edit_results_confirm_and_fail_without_retaining_arguments(tmp_path):
    parser = TranscriptParser("claude_code", path=tmp_path / "s.jsonl")
    for identifier, failed in (("success", False), ("failed", True)):
        call = line(mid=identifier, message={"id": identifier, "content": [{"type": "tool_use", "id": identifier,
            "name": "Edit", "input": {"old_string": "PRIVATE_OLD", "new_string": "PRIVATE_NEW\nmore"}}]})
        parser.consume(call, parser.state["offset"] + len(call))
        result = line(mid=identifier + "-result", type="user", message={"content": [{"type": "tool_result", "tool_use_id": identifier, "is_error": failed}]})
        parser.consume(result, parser.state["offset"] + len(result))
    edits = parser.fact()["change_events"]
    assert [e["outcome"] for e in edits] == ["confirmed", "failed"]
    assert edits[0]["added"] == 2 and edits[0]["removed"] == 1
    assert "PRIVATE" not in str(parser.checkpoint())


def test_pricing_unknown_missing_cache_inputs_and_dated_rates():
    usage = usage_record({"input_tokens": 100, "output_tokens": 10, "cache_read_input_tokens": 20, "cache_creation_input_tokens": 30})
    item = {"model": "claude-sonnet-4-6", "usage": usage, "timestamp": NOW}
    assert estimate(item) is None
    item["cache_creation"] = {"ephemeral_5m_input_tokens": 20, "ephemeral_1h_input_tokens": 10}
    assert estimate(item)["usd"] == pytest.approx((300 + 6 + 75 + 60 + 150) / 1e6)
    assert estimate({**item, "model": "unknown"}) is None
    assert estimate({**item, "timestamp": datetime(2026, 1, 1, tzinfo=timezone.utc)}) is None


def test_adapter_no_provider_network_imports():
    root = Path(__file__).parents[1] / "src/codex_insights/providers"
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(imported in text for imported in ("import requests", "import httpx", "import urllib.request", "import socket"))
    assert adapter("antigravity").capabilities["network"] is False


def test_hook_discovers_only_documented_referenced_transcript(tmp_path):
    directory = tmp_path / "data"
    transcript = tmp_path / "custom-brain/s/.system_generated/logs/transcript.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(line())
    receive(directory, "antigravity", "status", {"transcript_path": str(transcript)}, now=NOW)
    store = Store(directory)
    store.add_source(directory / "bridge/events", provider="antigravity", kind="bridge")
    assert refresh(store)["errors"] == 0
    assert dashboard(store)["summary"]["total_tokens"] == 160
    receive(directory, "antigravity", "status", {"transcript_path": str(tmp_path / "unrelated.jsonl")}, now=NOW)
    registry = (directory / "bridge/transcript-references.json").read_text()
    assert "unrelated.jsonl" not in registry


def test_unknown_bridge_schema_and_corrupt_snapshots_are_ignored(tmp_path):
    receive(tmp_path, "claude_code", "status", {"bridge_schema": 999, "rate_limits": {"five_hour": {"used_percentage": 50}}}, now=NOW)
    assert read(tmp_path)[0]["status"] == "unavailable"
    bridge = tmp_path / "bridge"
    bridge.mkdir(exist_ok=True)
    (bridge / "claude_code-allowance.json").write_text('[]')
    assert read(tmp_path)[0]["status"] == "unavailable"


def test_codex_account_burn_does_not_include_other_provider_tokens(tmp_path):
    from codex_insights.local_token_burn import LocalTokenBurn
    store = Store(tmp_path / "data")
    codex = tmp_path / "codex"
    source(store, codex, "codex")
    claude = tmp_path / "claude"
    source(store, claude)
    (claude / "s.jsonl").write_bytes(line())
    refresh(store)
    with store.connect() as db:
        db.execute("UPDATE sources SET updated=?,status='Ready'", (NOW.isoformat(),))
    value = LocalTokenBurn(store, clock=lambda: NOW.timestamp()).read()
    assert value["value"] == 0


def test_additive_provider_schema_migration_retains_codex_accounting(tmp_path):
    store = Store(tmp_path / "data")
    root = tmp_path / "codex"
    source(store, root, "codex")
    (root / "s.jsonl").write_bytes(log("s") + token(100))
    refresh(store)
    exporter = store.setting("exporter_id")
    with store.connect() as db:
        db.execute("DROP INDEX records_provider")
        for table in ("sources", "records", "candidates", "canonical", "metric_buckets"):
            db.execute("ALTER TABLE " + table + " DROP COLUMN provider")
        db.execute("UPDATE settings SET value='2' WHERE key='projection_version'")
    migrated = Store(store.directory)
    refresh(migrated)
    assert dashboard(migrated, {"provider": "codex"})["summary"]["total_tokens"] == 110
    assert migrated.setting("exporter_id") == exporter


def test_artifact_only_brain_folder_reports_missing_history(tmp_path):
    store = Store(tmp_path / "data")
    brain = tmp_path / "brain"
    source_id = source(store, brain, "antigravity")
    artifacts = brain / "conversation"
    artifacts.mkdir()
    (artifacts / "walkthrough.md").write_text("PRIVATE_ARTIFACT")
    assert refresh(store)["files"] == 0
    value = next(s for s in store.sources() if s["id"] == source_id)
    assert value["status"] == "No supported history"
    assert "saved artifacts" in value["detail"] and "passive Antigravity bridge" in value["detail"]
    assert dashboard(store)["summary"]["chats"] == 0
    assert "PRIVATE_ARTIFACT" not in value["detail"]
    transcript = artifacts / ".system_generated/logs/transcript.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_bytes(line())
    refresh(store)
    value = next(s for s in store.sources() if s["id"] == source_id)
    assert value["status"] == "Ready" and value["detail"] == ""
