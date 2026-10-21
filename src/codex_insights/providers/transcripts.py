"""Sanitized incremental Claude-compatible transcripts, including subagent files.

Original Antigravity binary archives use the separate legacy snapshot reader.
Public JSONL can establish activity; assistant message.usage establishes tokens.
"""
import hashlib
import json
from pathlib import Path

from ..codec import digest, timestamp
from ..copy_proofs import observe_record, fact_proofs
from ..parser import project_identity


def counter(value):
    return value if type(value) is int and value >= 0 else None


def usage_record(value):
    if not isinstance(value, dict):
        return None
    required = ("input_tokens", "output_tokens")
    if any(counter(value.get(k)) is None for k in required):
        return None
    # Cache fields are optional in the API usage schema and mean zero if absent.
    keys = ("cache_read_input_tokens", "cache_creation_input_tokens")
    if any(counter(value.get(k, 0)) is None for k in keys):
        return None
    reads, writes = (value.get(k, 0) for k in keys)
    inputs = value["input_tokens"] + reads + writes
    return {"input_tokens": inputs, "cached_input_tokens": reads,
            "cache_write_input_tokens": writes, "output_tokens": value["output_tokens"],
            "reasoning_output_tokens": 0, "total_tokens": inputs + value["output_tokens"]}


class TranscriptParser:
    VERSION = 3

    def __init__(self, provider, state=None, path=None, bridge=False):
        self.provider = provider
        self.bridge = bridge
        self.path = Path(path) if path else None
        self.state = state or {"version": self.VERSION, "offset": 0, "ordinal": 0, "hash": "",
                               "proofs": {}, "fact": None, "parse_errors": 0,
                               "record_hash": "", "record_proofs": {},
                               "responses": {}, "messages_seen": []}
        if provider == 'claude_code' and state is None:
            from .claude_identity import PARSER_VERSION
            self.state['version'] = PARSER_VERSION

    def consume(self, raw, end_offset):
        s = self.state
        s["offset"], s["ordinal"] = end_offset, s["ordinal"] + 1
        s["hash"] = hashlib.sha256(s["hash"].encode() + raw).hexdigest()
        s["proofs"][str(end_offset)] = s["hash"]
        try:
            e = json.loads(raw)
            if not isinstance(e, dict):
                raise ValueError()
        except (ValueError, UnicodeError):
            s["parse_errors"] += 1
            observe_record(s, None, raw)
            return
        observe_record(s, e)
        self.consume_event(e, end_offset)

    def consume_event(self, e, end_offset):
        s = self.state
        t = timestamp(e.get("timestamp"))
        if not t:
            return
        if self.bridge and e.get("bridge_schema") != 1:
            return
        message = e.get("message") if isinstance(e.get("message"), dict) else {}
        resolved = None
        if self.provider == 'claude_code':
            from .claude_identity import resolve
            resolved = resolve(e, self.path, s.get('claude_identity'))
            if resolved is None:
                if e.get('type') in {'assistant', 'user'}:
                    from .claude_identity import IdentityError
                    raise IdentityError('missing_session_or_agent_id')
                return
            s['claude_identity'] = resolved
        sid = e.get("sessionId") or e.get("conversationId") or e.get("session_id")
        subagent = self.path and self.path.parent.name == "subagents"
        if subagent:
            sid = self.path.stem
        if not sid and self.provider == "antigravity" and self.path:
            sid = self.path.parents[2].name
        if not isinstance(sid, str) or not sid or len(sid) > 400:
            if resolved is None:
                return
        if resolved:
            sid = resolved['suffix']
            subagent = resolved['agent_id'] is not None
        if s["fact"] is None:
            identity = self.provider + ":" + sid
            s["fact"] = {"provider": self.provider, "id": identity,
                "segment_id": digest([self.provider, sid, "hook" if self.bridge else "transcript"]), "metadata_timestamp": t,
                **(e["project"] if self.bridge else project_identity({"cwd": e.get("cwd", "")})),
                "session_source": "spawned_subagent" if subagent else "top_level",
                "parent_session_id": self.provider + ":" + str(e.get("sessionId")) if subagent and e.get("sessionId") else None,
                "spawn_timestamp": t, "raw_token_trace": [], "messages": [], "change_events": [],
                "activity": [], "tools": {}, "contexts": []}
            if resolved:
                s['fact']['parent_session_id'] = resolved['parent_session_id']
        f = s["fact"]
        model = message.get("model") or e.get("modelName")
        model = model[:200] if isinstance(model, str) else None
        f["activity"].append(t)
        if model:
            f["contexts"].append({"timestamp": t, "model": model})
        if e.get("cwd"):
            f.update(project_identity({"cwd": e["cwd"]}))
        if self.bridge and isinstance(e.get("edit"), dict):
            edit = dict(e["edit"])
            edit.update(timestamp=t, resolved_at=t)
            f["change_events"].append(edit)
        role = e.get("type") or message.get("role")
        if role in {"user", "assistant"}:
            mid = e.get("uuid") or message.get("id")
            if isinstance(mid, str):
                sig = digest([self.provider, role, mid])
                if sig not in s["messages_seen"]:
                    s["messages_seen"].append(sig)
                    f["messages"].append({"timestamp": t, "role": role, "signature": sig, "model": model})
        from .edits import observe
        if self.provider == "claude_code":
            observe(s, message.get("content"), role, t, model)
        usage = usage_record(message.get("usage")) if role == "assistant" else None
        mid = message.get("id")
        if usage is not None and isinstance(mid, str) and mid:
            # Request/message identity is stable across copied histories. Fragments
            # are snapshots of one response, not independent increments.
            rid = digest([self.provider, mid])
            previous = s["responses"].get(rid)
            if previous:
                usage = {k: max(v, previous["last_usage"][k]) for k, v in usage.items()}
                usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
            from .claude_pricing import pricing_metadata
            metadata = pricing_metadata(message["usage"]) if self.provider == "claude_code" else {}
            # A later streaming envelope can omit metadata already established
            # by this response. Missing values never erase a logged modifier.
            if previous:
                metadata = {**{k: previous[k] for k in ("service_tier", "speed", "inference_geo") if k in previous}, **metadata}
            creation = self.cache_creation(message.get("usage", {}))
            if previous and (creation is None or sum(creation.values()) != usage["cache_write_input_tokens"]):
                earlier = previous.get("cache_creation")
                if earlier is not None and sum(earlier.values()) == usage["cache_write_input_tokens"]:
                    creation = earlier
            s["responses"][rid] = {"timestamp": previous["timestamp"] if previous else t,
                "ordinal": s["ordinal"] - 1, "end_byte_offset": end_offset,
                "response_id": rid, "last_usage": usage, "model": model or (previous or {}).get("model"),
                "cache_creation": creation, **metadata}

    @staticmethod
    def cache_creation(usage):
        value = usage.get("cache_creation")
        if not isinstance(value, dict):
            return None
        keys = ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens")
        return {k: value[k] for k in keys} if all(counter(value.get(k)) is not None for k in keys) else None

    def checkpoint(self):
        return self.state

    def fact(self):
        if self.state["fact"] is None:
            return None
        s = self.state
        return {**s["fact"], "raw_token_trace": list(s["responses"].values()),
                "prefix_hash": s["hash"], "byte_count": s["offset"], "record_count": s["ordinal"],
                "proofs": s["proofs"], "parse_errors": s["parse_errors"], **fact_proofs(s)}
