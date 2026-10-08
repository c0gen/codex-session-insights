"""Append-aware parser retaining accounting facts, never transcript text."""
import hashlib
import json
import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit, urlunsplit

from .accounting.change_accounting import ChangeTracker
from .accounting.pricing import normalize_service_tier
from .accounting.token_accounting import normalize_usage
from .codec import digest, timestamp

PARSER_VERSION = 1


def repository(value):
    text = str(value or "").strip()
    if text.startswith("git@"):
        text = "https://" + text[4:].replace(":", "/", 1)
    try:
        url = urlsplit(text)
        if url.scheme not in {"http", "https", "ssh"} or not url.hostname:
            return ""
        path = url.path.rstrip("/").removesuffix(".git")
        host = url.hostname.lower()
        if host == "github.com":
            path = path.lower()
        return urlunsplit(("https", host, path, "", ""))
    except ValueError:
        return ""


def project_identity(meta):
    git = meta.get("git") or {}
    remote = repository(git.get("repository_url") or git.get("remote_url") or git.get("remote"))
    cwd = str(meta.get("cwd") or "").replace("\\", "/").rstrip("/")
    label = remote.rsplit("/", 1)[-1] if remote else PurePosixPath(cwd).name or "Unassigned"
    return {"project_id": remote or "workspace:" + hashlib.sha256(cwd.encode()).hexdigest(), "project_label": label[:200]}


def source_kind(source):
    if isinstance(source, dict) and isinstance(source.get("subagent"), dict):
        return "spawned_subagent" if source["subagent"].get("thread_spawn") else "system_subagent"
    return "top_level"


def message_text(payload):
    for key in ("message", "text"):
        if isinstance(payload.get(key), str):
            return payload[key]
    return "\n".join(str(item.get("text", "")) for item in payload.get("content", []) if isinstance(item, dict))


class SessionParser:
    def __init__(self, state=None):
        self.state = state or {"version": PARSER_VERSION, "ordinal": 0, "hash": "", "offset": 0,
                               "fact": None, "model": None, "effort": None, "tier": None,
                               "messages_seen": [], "tracker": {"events": [], "pending": {}, "cells": {}, "waits": {}},
                               "boundaries": [], "record_boundaries": [], "proofs": {}, "parse_errors": 0}
        self.tracker = ChangeTracker()
        for key in ("events", "pending", "cells", "waits"):
            setattr(self.tracker, key, self.state["tracker"][key])
        self.seen = set(self.state["messages_seen"])

    def consume(self, raw, end_offset):
        self.state["offset"] = end_offset
        self.state["ordinal"] += 1
        self.state["hash"] = hashlib.sha256(self.state["hash"].encode() + raw).hexdigest()
        self.state["proofs"][str(end_offset)] = self.state["hash"]
        try:
            event = json.loads(raw)
        except (ValueError, UnicodeError):
            self.state["parse_errors"] += 1
            return
        if not isinstance(event, dict):
            self.state["parse_errors"] += 1
            return
        pl = event.get("payload")
        t = timestamp(event.get("timestamp"))
        if not isinstance(pl, dict):
            return
        top, kind = event.get("type"), pl.get("type")
        self.state["record_boundaries"].append([end_offset, event.get("ordinal", self.state["ordinal"] - 1)])
        if top == "session_meta" and self.state["fact"] is None:
            sid = str(pl.get("id") or "")
            if not sid or not t:
                return
            source = pl.get("source")
            spawn = ((source.get("subagent") or {}).get("thread_spawn") or {}) if isinstance(source, dict) else {}
            self.state["fact"] = {"id": sid, "segment_id": digest([sid, t]), "metadata_timestamp": t,
                **project_identity(pl), "session_source": source_kind(source),
                "parent_session_id": pl.get("forked_from_id") or pl.get("parent_thread_id") or spawn.get("parent_thread_id"),
                "spawn_timestamp": t, "history_mode": pl.get("history_mode"), "history_base": {key:pl["history_base"][key] for key in ("thread_id","end_byte_offset","end_ordinal_exclusive") if key in pl["history_base"]} if isinstance(pl.get("history_base"),dict) else pl.get("history_base"),
                "raw_token_trace": [], "messages": [], "change_events": [], "activity": [], "tools": {}, "contexts": []}
        fact = self.state["fact"]
        if fact is None:
            return
        if top == "turn_context" or kind == "thread_settings_applied":
            settings = pl.get("thread_settings") or pl.get("settings") or pl
            for key, state_key in (("model", "model"), ("effort", "effort"), ("reasoning_effort", "effort")):
                if key in settings:
                    self.state[state_key] = settings[key]
            for key in ("service_tier", "serviceTier"):
                if key in settings:
                    self.state["tier"] = normalize_service_tier(settings[key])
            if top == "turn_context" and t:
                fact["contexts"].append({"timestamp": t, "model": self.state["model"], "effort": self.state["effort"], "service_tier": self.state["tier"]})
                if isinstance(pl.get("git"), dict) and project_identity(pl)["project_id"].startswith("https:"):
                    fact.update(project_identity(pl))
        if t:
            previous_edits = len(self.tracker.events)
            self.tracker.observe(pl, t)
            for edit in self.tracker.events[previous_edits:]:
                edit["model"] = self.state["model"]
            if kind in {"function_call_output", "custom_tool_call_output"}:
                for edit in self.tracker.events:
                    if edit["outcome"] != "unknown" and not edit.get("resolved_at"):
                        edit["resolved_at"] = t
            fact["activity"].append(t)
        if kind == "token_count":
            info = pl.get("info") or {}
            if isinstance(info, dict) and t:
                cumulative, last = normalize_usage(info.get("total_token_usage")), normalize_usage(info.get("last_token_usage"))
                if cumulative is not None or last is not None:
                    fact["raw_token_trace"].append({"timestamp": t, "ordinal": event.get("ordinal", self.state["ordinal"] - 1),
                        "end_byte_offset": end_offset, "cumulative_usage": cumulative, "last_usage": last,
                        "model": self.state["model"], "effort": self.state["effort"], "service_tier": self.state["tier"],
                        "model_context_window": info.get("model_context_window")})
        if kind in {"user_message", "agent_message", "message"} and t:
            role = {"user_message": "user", "agent_message": "assistant"}.get(kind, pl.get("role"))
            if role in {"user", "assistant"}:
                sig = digest([role, t, message_text(pl)])
                if sig not in self.seen:
                    self.seen.add(sig)
                    fact["messages"].append({"timestamp": t, "role": role, "signature": sig, "model": self.state["model"]})
        if kind in {"function_call", "custom_tool_call"} and t:
            name = str(pl.get("name") or "unknown")[:200]
            fact["tools"][name] = fact["tools"].get(name, 0) + 1
        # Record settings/counters at physical boundaries for portable history-base seeds.
        if top == "turn_context" or kind in {"thread_settings_applied", "token_count"}:
            self.state["boundaries"].append({"end_byte_offset": end_offset, "ordinal": event.get("ordinal", self.state["ordinal"] - 1),
                "model": self.state["model"], "effort": self.state["effort"], "service_tier": self.state["tier"],
                "usage": (pl.get("info") or {}).get("total_token_usage") if kind == "token_count" else None})
        self.state["last_event_ordinal"] = event.get("ordinal", self.state["ordinal"] - 1)

    def checkpoint(self):
        self.state["messages_seen"] = sorted(self.seen)
        self.state["tracker"] = {key: getattr(self.tracker, key) for key in ("events", "pending", "cells", "waits")}
        return self.state

    def fact(self):
        fact = self.state["fact"]
        if fact is None:
            return None
        fact = dict(fact)
        fact.update(change_events=self.tracker.events, prefix_hash=self.state["hash"], byte_count=self.state["offset"],
                    record_count=self.state["ordinal"], boundaries=self.state["boundaries"],
                    last_event_ordinal=self.state.get("last_event_ordinal"), parse_errors=self.state["parse_errors"])
        fact.update(record_boundaries=self.state["record_boundaries"], proofs=self.state["proofs"])
        return fact


def portable_fact(fact):
    """Remove paths even when a patch had absolute filenames."""
    result = dict(fact)
    result["change_events"] = []
    for event in fact.get("change_events", []):
        item = dict(event)
        for key in ("files", "result_files"):
            item[key] = ["file:" + hashlib.sha256(str(p).encode()).hexdigest() for p in event.get(key, [])]
        result["change_events"].append(item)
    return result
