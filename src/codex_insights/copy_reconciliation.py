"""Evidence-based comparison and durable selection of complete history variants."""
from .codec import digest


def variant_id(fact):
    return digest([fact.get("provider", "codex"), fact["segment_id"], fact["byte_count"], fact["prefix_hash"]])


def same_family(left, right):
    keys = ("id", "segment_id", "parent_session_id", "session_source", "history_mode", "history_base")
    return (left.get("provider", "codex") == right.get("provider", "codex")
            and all(left.get(key) == right.get(key) for key in keys))


def covers(longer, shorter):
    """An entire history, never matching aggregate counters, proves coverage."""
    if not same_family(longer, shorter):
        return False
    if longer.get("snapshot_mode") == shorter.get("snapshot_mode") == "complete_binary":
        from .providers.legacy.snapshots import compatible
        return compatible(longer, shorter) and _size(longer) >= _size(shorter)
    if longer.get("history_mode") == shorter.get("history_mode") == "antigravity_steps":
        from .providers.public_snapshots import compatible
        return compatible(longer, shorter) and _size(longer) >= _size(shorter)
    if (longer["byte_count"] == shorter["byte_count"] and longer["prefix_hash"] == shorter["prefix_hash"]):
        return True
    if longer.get("proofs", {}).get(str(shorter["byte_count"])) == shorter["prefix_hash"]:
        return True
    return bool(shorter.get("record_hash") and longer.get("record_proofs", {}).get(
        str(shorter["record_count"])) == shorter["record_hash"])


def _size(fact):
    return (len(fact.get("raw_token_trace", [])), len(fact.get("messages", [])),
            len(fact.get("change_events", [])), fact["record_count"])


def compatible(left, right):
    return covers(left, right) or covers(right, left)


def evidence_revision(variants, pending=()):
    return digest([sorted((v["source_id"], v["variant_id"], digest(v["fact"])) for v in variants), sorted(pending)])


def select(variants, previous=None, decision=None, pending=False):
    """Keep accepted history on disagreement; allow only verified extensions."""
    ordered = sorted(variants, key=lambda v: (-v["fact"]["record_count"], -v.get("parser_version", 0),
                                             v["source_id"], v["variant_id"]))
    if not ordered:
        return None, "awaiting_verification" if pending else "verified"
    winner = next((v for v in ordered if previous and v["source_id"] == previous["source_id"]
                   and v["variant_id"] == previous["variant_id"]), None)
    if winner is None:
        winner = next((v for v in ordered if previous and previous.get("fact")
                       and covers(v["fact"], previous["fact"])), ordered[0])
    selected = None
    if decision:
        selected = next((v for v in ordered if v["variant_id"] == decision.get("selected")), None)
        if selected is None:
            original = next((f for f in decision.get("reviewed", []) if variant_id(f) == decision.get("selected")), None)
            if original:
                selected = next((v for v in ordered if covers(v["fact"], original)), None)
        if selected:
            winner = selected
    # Equivalent serialization keeps the current winner and its byte boundaries.
    for candidate in ordered:
        if covers(candidate["fact"], winner["fact"]) and not covers(winner["fact"], candidate["fact"]):
            winner = candidate
    divergent = [v for v in ordered if not compatible(v["fact"], winner["fact"])]
    reviewed = (decision or {}).get("reviewed", [])
    # Known rejected histories stay reviewed, but extensions of rejected branches
    # carry new potentially excluded activity and must reopen the conflict.
    resolved = bool(selected and all(any(covers(old, v["fact"]) for old in reviewed) for v in divergent))
    state = "manually_resolved" if resolved else "needs_review" if divergent else "verified"
    if pending and not resolved:
        state = "awaiting_verification"
    return winner, state
