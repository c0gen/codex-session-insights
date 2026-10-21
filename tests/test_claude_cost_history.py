"""Claude repricing, source upgrades and portable pricing metadata."""
from copy import deepcopy
import hashlib
import json
import zipfile

import pytest

from codex_insights import projection
from codex_insights.codec import pack, unpack
from codex_insights.ingestion import refresh
from codex_insights.providers import adapter
from codex_insights.providers.transcripts import TranscriptParser
from codex_insights.queries import dashboard
from codex_insights.storage import Store
from codex_insights.transfers import export_snapshot, import_snapshot, validate_fact
from codex_insights.widget_queries import WidgetSummaries
from conftest import log, token


def line(sid="main", mid="response", model="claude-opus-5-5", **usage_patch):
    usage = {"input_tokens": 1_000_000, "cache_read_input_tokens": 200_000,
             "cache_creation_input_tokens": 300_000, "output_tokens": 100_000,
             "cache_creation": {"ephemeral_5m_input_tokens": 200_000, "ephemeral_1h_input_tokens": 100_000},
             **usage_patch}
    return (json.dumps({"type": "assistant", "timestamp": "2026-10-04T12:00:00Z",
                       "sessionId": sid, "uuid": mid, "cwd": "C:/private/project",
                       "message": {"id": mid, "model": model, "usage": usage,
                                   "content": [{"type": "text", "text": "PRIVATE_RESPONSE"}]}}) + "\n").encode()


def indexed(tmp_path, content=None):
    root = tmp_path / "claude"
    root.mkdir()
    path = root / "main.jsonl"
    path.write_bytes(content or line())
    store = Store(tmp_path / "data")
    store.set_setting("timezone", "UTC")
    source = store.add_source(root, provider="claude_code")
    refresh(store)
    return store, root, path, source


def test_streaming_metadata_is_sanitized_and_survives_omitted_fields(tmp_path):
    first = line(speed="fast", inference_geo="us", service_tier="standard")
    fragment = line(output_tokens=120_000, cache_creation=None)
    parser = TranscriptParser("claude_code", path=tmp_path / "main.jsonl")
    parser.consume(first, len(first))
    parser = adapter("claude_code").parser(parser.checkpoint(), tmp_path / "main.jsonl")
    parser.consume(fragment, len(first + fragment))
    fact = parser.fact()
    trace = fact["raw_token_trace"]
    assert len(trace) == 1
    assert trace[0]["speed"] == "fast" and trace[0]["inference_geo"] == "us"
    assert trace[0]["service_tier"] == "standard"
    assert trace[0]["last_usage"]["output_tokens"] == 120_000
    assert trace[0]["cache_creation"]["ephemeral_1h_input_tokens"] == 100_000
    validate_fact(fact)
    assert "PRIVATE_RESPONSE" not in json.dumps(parser.checkpoint(), default=str)
    parser.consume(line(speed={"private": "PRIVATE_METADATA"}), 99999)
    assert parser.fact()["raw_token_trace"][0]["speed"] == "unknown"
    assert "PRIVATE_METADATA" not in json.dumps(parser.checkpoint(), default=str)


def test_cost_views_reconcile_fragments_copies_subagents_and_provider_filters(tmp_path):
    first = line(speed="fast", inference_geo="us", service_tier="standard", output_tokens=50_000)
    store, root, path, _ = indexed(tmp_path, first + line(output_tokens=100_000))
    # Equal token counts: use the copy with logged pricing evidence even if a
    # different segment owns the lexically first response ID.
    (root / "copy.jsonl").write_bytes(line(sid="copy"))
    child = root / "main" / "subagents" / "agent-a.jsonl"
    child.parent.mkdir(parents=True)
    child.write_bytes(line(mid="child-response", model="claude-sonnet-5-5"))
    codex = tmp_path / "codex"
    codex.mkdir()
    (codex / "session.jsonl").write_bytes(log() + token(100))
    store.add_source(codex)
    refresh(store)
    claude = dashboard(store, {"provider": "claude_code"})
    assert claude["summary"]["total_tokens"] == 3_200_000
    assert claude["summary"]["cost"] == 21.17
    assert claude["summary"]["priced_percent"] == 100
    assert sum(row["cost"] for row in claude["models"]) == pytest.approx(21.168)
    assert sum(row["cost"] for row in claude["projects"]) == pytest.approx(21.168)
    assert claude["timeline"][0]["cost"] == pytest.approx(21.168)
    assert dashboard(store, {"provider": "codex"})["summary"]["total_tokens"] == 110
    assert WidgetSummaries(store).read()["all_time"]["cost"] == dashboard(store)["summary"]["cost"]
    assert refresh(store)["bytes_read"] == 0
    assert dashboard(store, {"provider": "claude_code", "model": "claude-sonnet-5-5"})["summary"]["cost"] == 3.92


def make_old_index(store):
    """Simulate a v1 parser/v4 projection without rewriting the input log."""
    with store.connect() as db:
        for table in ("candidates", "canonical"):
            for row in db.execute("SELECT rowid,fact FROM " + table).fetchall():
                fact = unpack(row["fact"])
                for item in fact["raw_token_trace"]:
                    for key in ("service_tier", "speed", "inference_geo"):
                        item.pop(key, None)
                db.execute("UPDATE " + table + " SET fact=? WHERE rowid=?", (pack(fact), row["rowid"]))
        # Pre-v6 indexes had no retained variant table; remove today's richer
        # evidence so the fixture actually represents that historical index.
        db.execute("DELETE FROM history_variants")
        db.execute("UPDATE files SET parser_version=1")
        db.execute("UPDATE candidates SET parser_version=1")
        db.execute("UPDATE records SET cost=NULL,priced=0,cache_discount=NULL,cache_priced=0")
        db.execute("UPDATE metric_buckets SET cost=NULL,priced=0,cache_discount=NULL,cache_priced=0")
        db.execute("UPDATE settings SET value='4' WHERE key='projection_version'")


def test_offline_repricing_then_local_metadata_backfill_is_automatic(tmp_path):
    content = line(speed="fast", inference_geo="us", service_tier="standard")
    store, root, path, _ = indexed(tmp_path, content)
    make_old_index(store)
    assert dashboard(store)["summary"]["estimated_cost"] is None
    offline = root.with_name("offline")
    root.rename(offline)
    revision = store.setting("data_revision")
    assert refresh(store)["bytes_read"] == 0
    assert dashboard(store)["summary"]["cost"] == 7.84  # disclosed Standard/global default
    assert store.setting("projection_version") == projection.PROJECTION_VERSION
    assert store.setting("data_revision") == revision + 1
    assert not projection.ensure_projection(store)
    offline.rename(root)
    assert refresh(store)["bytes_read"] == len(content)
    assert dashboard(store)["summary"]["cost"] == 17.25
    assert path.read_bytes() == content
    assert refresh(store)["bytes_read"] == 0


def test_v6_roundtrip_preserves_modifiers_and_old_metadata_is_rejected(tmp_path):
    store, _, _, _ = indexed(tmp_path, line(speed="fast", inference_geo="us", service_tier="standard"))
    snapshot = tmp_path / "claude.codex-insights"
    export_snapshot(store, snapshot)
    target = Store(tmp_path / "target")
    import_snapshot(target, snapshot)
    assert dashboard(target)["summary"]["cost"] == 17.25
    with zipfile.ZipFile(snapshot) as bundle:
        assert json.loads(bundle.read("manifest.json"))["format_version"] == 6
    with target.connect() as db:
        fact = unpack(db.execute("SELECT fact FROM canonical").fetchone()[0])
    assert fact["raw_token_trace"][0]["inference_geo"] == "us"
    fact.pop("record_hash", None)
    fact.pop("record_proofs", None)
    for version in (2, 3, 4):
        with pytest.raises(ValueError, match="requires transfer v5"):
            validate_fact(deepcopy(fact), version)
    for key in ("speed", "inference_geo", "service_tier"):
        invalid = deepcopy(fact)
        invalid["raw_token_trace"][0][key] = {"prompt": "PRIVATE"}
        with pytest.raises(ValueError):
            validate_fact(invalid)


@pytest.mark.parametrize("version", [2, 3, 4])
def test_old_claude_transfers_still_import_and_reprice(tmp_path, version):
    store, _, _, _ = indexed(tmp_path)
    snapshot = tmp_path / "current.codex-insights"
    export_snapshot(store, snapshot)
    with zipfile.ZipFile(snapshot) as bundle:
        manifest = json.loads(bundle.read("manifest.json"))
        facts = bundle.read("facts.jsonl")
    from conftest import legacy_records
    facts = legacy_records(facts)
    manifest["format_version"] = version
    manifest["facts_sha256"] = hashlib.sha256(facts).hexdigest()
    older = tmp_path / "older.codex-insights"
    with zipfile.ZipFile(older, "w") as bundle:
        bundle.writestr("manifest.json", json.dumps(manifest))
        bundle.writestr("facts.jsonl", facts)
    target = Store(tmp_path / "target")
    assert import_snapshot(target, older)["status"] == "imported"
    assert dashboard(target)["summary"]["cost"] == 7.84


def test_unknown_and_missing_duration_reduce_cost_coverage(tmp_path):
    content = line() + line(mid="unknown", model="claude-future") + line(mid="missing", cache_creation=None)
    store, _, _, _ = indexed(tmp_path, content)
    summary = dashboard(store)["summary"]
    assert summary["cost"] == 7.84
    assert summary["priced_percent"] == 33.3
