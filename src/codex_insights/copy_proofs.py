"""Ordered JSON proofs, independent of whitespace and object key ordering."""
import hashlib

from .codec import digest


def observe_record(state, event, raw=None):
    # Old checkpoints must be reparsed; a suffix cannot prove an entire history.
    if "record_hash" not in state:
        return
    value = ["invalid", hashlib.sha256(raw).hexdigest()] if raw is not None else ["json", event]
    state["record_hash"] = digest([state["record_hash"], value])
    state["record_proofs"][str(state["ordinal"])] = state["record_hash"]


def fact_proofs(state):
    return {key: state[key] for key in ("record_hash", "record_proofs") if key in state}
