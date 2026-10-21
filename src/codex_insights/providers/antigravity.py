"""Allowlisted Antigravity public JSONL steps, independent of Claude's schema."""
import json
from pathlib import Path

from ..codec import digest, timestamp
from .transcripts import TranscriptParser, counter

HISTORY_MODE = "antigravity_steps"


def read_metadata(directory, path):
    source = Path(directory) / "bridge/transcript-metadata.json"
    try:
        if source.stat().st_size > 1024 * 1024:
            return {}
        value = json.loads(source.read_text(encoding="utf-8")).get(digest(str(path)), {})
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, AttributeError):
        return {}


def step_usage(event):
    inputs, reads, outputs = (counter(event.get(k)) for k in ("input_tokens", "cache_read_tokens", "output_tokens"))
    normalized_input = inputs + reads if inputs is not None and reads is not None else None
    return {"input_tokens": normalized_input, "cached_input_tokens": reads,
            "cache_write_input_tokens": None, "output_tokens": outputs,
            "reasoning_output_tokens": counter(event.get("thinking_tokens")),
            "total_tokens": normalized_input + outputs if normalized_input is not None and outputs is not None else None}


def merge_usage(left, right):
    result = {k: max(v for v in (value, right.get(k)) if v is not None)
              if value is not None or right.get(k) is not None else None for k, value in left.items()}
    if result['input_tokens'] is not None and result['output_tokens'] is not None:
        result['total_tokens'] = result['input_tokens'] + result['output_tokens']
    return result


class AntigravityParser(TranscriptParser):
    VERSION = 3

    def __init__(self, provider="antigravity", state=None, path=None, metadata=None):
        super().__init__(provider, state, path)
        self.metadata = metadata or {}

    def consume_event(self, event, end_offset):
        if "created_at" not in event:
            return super().consume_event(event, end_offset)  # Compatible older public JSONL.
        at = timestamp(event.get("created_at"))
        index = counter(event.get("step_index"))
        if at is None or index is None or self.path is None or len(self.path.parents) < 3:
            return
        sid = self.path.parents[2].name
        identity = digest(["antigravity", sid, index, at])
        kind = event.get("type")
        role = "user" if kind == "USER_INPUT" else "assistant" if kind == "PLANNER_RESPONSE" else "activity"
        model = self.metadata.get("modelName")
        model = model[:200] if isinstance(model, str) else None
        envelope = {"timestamp": at, "sessionId": sid, "type": role, "uuid": identity,
                    "message": {"id": identity, "model": model}}
        super().consume_event(envelope, end_offset)
        fact = self.state["fact"]
        if fact is None:
            return
        fact["history_mode"] = HISTORY_MODE
        if fact['project_label'] == 'Unassigned':
            fact['project_label'] = 'Unknown workspace'
        project = self.metadata.get("project")
        if isinstance(project, dict) and isinstance(project.get("project_id"), str) and isinstance(project.get("project_label"), str):
            fact.update({k: project[k] for k in ("project_id", "project_label")})
        if kind != "PLANNER_RESPONSE" and not any(k in event for k in ("input_tokens", "cache_read_tokens", "output_tokens")):
            return
        usage = step_usage(event)
        rid = digest(["antigravity", identity])
        previous = self.state["responses"].get(rid)
        if previous:
            usage = merge_usage(usage, previous['last_usage'])
        self.state["responses"][rid] = {"timestamp": at, "ordinal": self.state["ordinal"] - 1,
            "end_byte_offset": end_offset, "response_id": rid, "last_usage": usage,
            "model": model if isinstance(model, str) else None, "cache_creation": None}
