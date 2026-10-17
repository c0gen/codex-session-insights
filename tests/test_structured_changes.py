import json
from datetime import timedelta

import pytest

from codex_insights.accounting.change_accounting import ChangeTracker, event_signature
from codex_insights.accounting.structured_changes import completed_stats, diff_lines, patch_fingerprint
from codex_insights.codec import pack, unpack
from codex_insights.parser import SessionParser, portable_fact
from codex_insights.transfers import validate_fact
from conftest import T, event, log


PATCH = "*** Begin Patch\n*** Update File: file.py\n@@\n-old\n+new\n+extra\n*** End Patch"
DIFF = "@@ -1 +1,2 @@\n-old\n+new\n+extra\n"


@pytest.mark.parametrize("second", [
    "@@\n-a\n-b\n+b\n+a\n",  # Ordered strings versus net-count tuples.
    "*** Move to: renamed.py\n@@\n-old\n+new\n",  # None versus a move path.
])
def test_repeated_patch_paths_have_comparable_fingerprints(indexed, second):
    from codex_insights.ingestion import refresh

    first = "*** Update File: file.py\n@@\n-old\n+new\n"
    other = "*** Update File: file.py\n" + second
    patch = "*** Begin Patch\n" + first + other + "*** End Patch"
    reversed_patch = "*** Begin Patch\n" + other + first + "*** End Patch"
    assert patch_fingerprint(patch) == patch_fingerprint(reversed_patch)
    store, root, _ = indexed
    (root / "repeated.jsonl").write_bytes(log() + event("response_item", call(patch=patch)))
    result = refresh(store)
    assert result["errors"] == 0
    assert result["changed_files"] == 1
    assert not store.sources()[0]["detail"]


def completion(identity="edit-1", status="completed", changes=None):
    return {"type": "item_completed", "item": {"type": "FileChange", "id": identity,
        "status": status, "changes": changes if changes is not None else {
            "file.py": {"type": "update", "unified_diff": DIFF, "move_path": None}}}}


def call(identity="call-1", patch=PATCH):
    return {"type": "custom_tool_call", "name": "exec", "call_id": identity,
            "input": "text(await tools.apply_patch(" + json.dumps(patch) + "));"}


def output(identity="call-1", text="{}"):
    return {"type": "custom_tool_call_output", "call_id": identity, "output": text}


def test_counts_moves_deletes_empty_and_headers():
    changes = {
        "new": {"type": "add", "content": "first\nlast"},
        "empty": {"type": "add", "content": ""},
        "gone": {"type": "delete", "content": "a\nb\n"},
        "old": {"type": "update", "move_path": "moved", "unified_diff":
            "--- old\n+++ moved\n@@ -1,2 +1,2 @@\n context\n---old\n+++new\n\\ No newline at end of file\n"},
        "rename": {"type": "update", "move_path": "renamed", "unified_diff": ""},
    }
    stats, _ = completed_stats(completion(changes=changes)["item"])
    assert (stats["added"], stats["removed"]) == (3, 3)
    assert {"old", "moved", "rename", "renamed"} <= set(stats["files"])
    assert "old" not in stats["result_files"]
    assert not stats["unknown_size"]


@pytest.mark.parametrize("diff", ["+no hunk", "@@ bad @@\n+line", "@@ -1 +1 @@\n+new\n",
    "@@ -0,0 +1 @@\n+a\n+b", "--- old\n+++ new", None])
def test_malformed_diffs_are_not_counted(diff):
    with pytest.raises(ValueError):
        diff_lines(diff)
    tracker = ChangeTracker()
    tracker.observe(completion(changes={"file.py": {"type": "update", "unified_diff": diff}}), T)
    assert tracker.events[0]["outcome"] == "unknown"
    assert not tracker.events[0]["supported"]
    assert tracker.events[0]["added"] == 0


@pytest.mark.parametrize("status,expected", [("completed", "confirmed"), ("failed", "failed"),
                                           ("declined", "failed"), ("inProgress", "unknown")])
def test_status_is_authoritative(status, expected):
    tracker = ChangeTracker()
    tracker.observe(call(), T)
    tracker.observe(completion(status=status), T + timedelta(seconds=2))
    tracker.observe(output(text="Success. Updated the following files:\nM file.py\n"), T + timedelta(seconds=3))
    assert len(tracker.events) == 1
    assert tracker.events[0]["outcome"] == expected


@pytest.mark.parametrize("legacy_first", [False, True])
def test_legacy_structured_and_duplicate_completion_count_once(legacy_first):
    tracker = ChangeTracker()
    tracker.observe(call(), T)
    signature = event_signature(tracker.events[0])
    result = output(text="Success. Updated the following files:\nM file.py\n")
    for pl in ([result, completion()] if legacy_first else [completion(), result]):
        tracker.observe(pl, T + timedelta(seconds=1))
    tracker.observe(completion(), T + timedelta(seconds=2))
    assert len(tracker.events) == 1
    assert event_signature(tracker.events[0]) == signature
    assert (tracker.events[0]["added"], tracker.events[0]["removed"]) == (2, 1)
    assert tracker.events[0]["outcome"] == "confirmed"


def test_repeated_identical_operations_and_multiple_patches():
    tracker = ChangeTracker()
    pl = call()
    pl["input"] *= 2
    tracker.observe(pl, T)
    tracker.observe(completion("first"), T)
    tracker.observe(completion("second"), T)
    tracker.observe(output(), T)
    tracker.observe(call("next-call"), T)
    tracker.observe(completion("third"), T)
    assert len(tracker.events) == 3
    assert all(e["outcome"] == "confirmed" for e in tracker.events)


def test_content_and_scope_prevent_filename_only_matching():
    tracker = ChangeTracker()
    tracker.observe(call(), T)
    other = completion(changes={"file.py": {"type": "update", "unified_diff": DIFF.replace("extra", "different")}})
    tracker.observe(other, T)
    assert len(tracker.events) == 2
    assert tracker.events[0]["outcome"] == "unknown"
    assert tracker.events[1]["outcome"] == "confirmed"
    tracker.observe(output(), T)
    tracker.observe(call("new-call", PATCH.replace("file.py", "elsewhere.py")), T)
    tracker.observe(completion("later"), T)
    assert tracker.events[0]["outcome"] == "unknown"
    assert tracker.events[-1]["call_id"] == "filechange:later"


def test_delete_confirmation_supplies_missing_size():
    tracker = ChangeTracker()
    tracker.observe(call(patch="*** Begin Patch\n*** Delete File: file.py\n*** End Patch"), T)
    tracker.observe(completion(changes={"file.py": {"type": "delete", "content": "old\nlines\n"}}), T)
    assert len(tracker.events) == 1
    assert tracker.events[0]["removed"] == 2
    assert not tracker.events[0]["unknown_size"]


def test_yield_checkpoint_relative_paths_model_and_private_export():
    parser = SessionParser()
    content = log() + event("response_item", call(), 5)
    content += event("response_item", output(text="Script running with cell ID work-1"), 6)
    offset = 0
    for raw in content.splitlines(keepends=True):
        offset += len(raw); parser.consume(raw, offset)
    parser = SessionParser(unpack(pack(parser.checkpoint())))
    absolute = completion(changes={"C:\\private\\work\\project\\file.py": {
        "type": "update", "unified_diff": DIFF, "move_path": None}})
    for raw in [event("response_item", {"type": "function_call", "name": "wait", "call_id": "wait-1",
                 "arguments": '{"cell_id":"work-1"}'}, 7), event("event_msg", absolute, 8),
                event("response_item", output("wait-1", "Script completed"), 9)]:
        offset += len(raw); parser.consume(raw, offset)
    parser = SessionParser(unpack(pack(parser.checkpoint())))
    raw = event("event_msg", absolute, 10)
    parser.consume(raw, offset + len(raw))
    fact = parser.fact()
    assert len(fact["change_events"]) == 1
    edit = fact["change_events"][0]
    assert edit["model"] == "gpt-5.3-codex"
    assert edit["timestamp"] == T + timedelta(seconds=5)
    assert edit["resolved_at"] == T + timedelta(seconds=8)
    portable = portable_fact(fact)
    validate_fact(portable)
    encoded = json.dumps(portable, default=str)
    assert "file.py" not in encoded and "private" not in encoded and DIFF not in encoded


def test_opaque_result_without_completion_stays_unknown():
    tracker = ChangeTracker()
    tracker.observe(call(), T)
    tracker.observe(output(), T)
    assert tracker.events[0]["outcome"] == "unknown"


def test_missing_identity_is_unmeasured():
    tracker = ChangeTracker()
    pl = completion()
    del pl["item"]["id"]
    tracker.observe(pl, T)
    assert tracker.events[0]["outcome"] == "unknown"


def test_diff_boundary_shifts_and_redundant_lines_match():
    patch = "*** Begin Patch\n*** Update File: file.py\n@@\n-same\n+same\n+\n+new\n*** End Patch"
    diff = "@@ -1 +1,3 @@\n same\n+new\n+\n"
    tracker = ChangeTracker()
    tracker.observe(call(patch=patch), T)
    tracker.observe(completion(changes={"file.py": {"type": "update", "unified_diff": diff}}), T)
    assert len(tracker.events) == 1
    assert (tracker.events[0]["added"], tracker.events[0]["removed"]) == (2, 0)


def test_overlapping_identical_calls_do_not_double_count_legacy_results():
    tracker = ChangeTracker()
    tracker.observe(call("first"), T)
    tracker.observe(call("second"), T)
    tracker.observe(completion(), T)
    for identity in ("first", "second"):
        tracker.observe(output(identity, "Success. Updated the following files:\nM file.py\n"), T)
    confirmed = [e for e in tracker.events if e["outcome"] == "confirmed"]
    assert len(confirmed) == 1
    assert confirmed[0]["call_id"] == "filechange:edit-1"
    assert sum(e["outcome"] == "unknown" for e in tracker.events) == 2


def test_multiple_distinct_patches_and_move_match_in_one_call():
    moved = "*** Begin Patch\n*** Update File: before.py\n*** Move to: after.py\n@@\n-old\n+new\n*** End Patch"
    tracker = ChangeTracker()
    pl = call()
    pl["input"] += call(patch=moved)["input"]
    tracker.observe(pl, T)
    tracker.observe(completion("move", changes={"before.py": {"type": "update", "move_path": "after.py",
        "unified_diff": "@@ -1 +1 @@\n-old\n+new\n"}}), T)
    tracker.observe(completion(), T)
    assert len(tracker.events) == 2
    assert all(e["outcome"] == "confirmed" for e in tracker.events)
