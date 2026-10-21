"""Local-only provider adapters. Application identity never comes from model names."""
from dataclasses import dataclass
from pathlib import Path

from ..parser import PARSER_VERSION, SessionParser
from .transcripts import TranscriptParser
from .claude_identity import PARSER_VERSION as CLAUDE_PARSER_VERSION

LABELS = {"codex": "Codex", "claude_code": "Claude Code", "antigravity": "Antigravity"}


@dataclass(frozen=True)
class Adapter:
    provider: str
    version: int

    def snapshot_reader(self, root, profile, format='antigravity_legacy'):
        raise ValueError('Encrypted Antigravity archive collection is disabled. Use public transcripts and official hooks.')

    def parser(self, state=None, path=None, kind="folder", metadata=None):
        if self.provider == "codex":
            return SessionParser(state)
        bridge = kind == "bridge" and Path(path).parent.name == "events"
        if self.provider == 'antigravity' and not bridge:
            from .antigravity import AntigravityParser
            return AntigravityParser(self.provider, state, path, metadata)
        result = TranscriptParser(self.provider, state, path, bridge=bridge)
        result.state['version'] = self.version
        return result

    def discover(self, root, kind="folder"):
        root = Path(root)
        if kind == "bridge":
            yield from sorted(root.glob("*.jsonl"))
            import json
            references = root.parent / "transcript-references.json"
            try:
                if references.stat().st_size <= 4 * 1024 * 1024:
                    value = json.loads(references.read_text(encoding="utf-8"))
                    if isinstance(value, dict):
                        for reference in sorted(set(value.values())):
                            path = Path(reference)
                            if path.is_absolute() and path.name == "transcript.jsonl" and path.parent.name == "logs" and path.parent.parent.name == ".system_generated":
                                yield path
            except (OSError, ValueError, TypeError):
                pass
        elif self.provider == "antigravity":
            # Explicit documented hidden directory; never sweep workspace JSONL.
            yield from sorted(root.glob("*/.system_generated/logs/transcript.jsonl"))
        elif self.provider == "claude_code":
            yield from sorted(root.rglob("*.jsonl"))
        else:
            import os
            def failed(error):
                raise error
            for base, dirs, names in os.walk(root, onerror=failed):
                dirs[:] = [d for d in dirs if not d.startswith(".") or d == ".codex"]
                for name in sorted(names):
                    if name.endswith(".jsonl") and not name.startswith("._"):
                        yield Path(base) / name

    @property
    def capabilities(self):
        return {"history": True, "tokens": "recognized_records", "allowance":
                "status_line" if self.provider != "codex" else "official_client",
                "edits": "verified_only", "network": False}


ADAPTERS = {p: Adapter(p, PARSER_VERSION if p == "codex" else
                       CLAUDE_PARSER_VERSION if p == 'claude_code' else TranscriptParser.VERSION) for p in LABELS}


def adapter(provider="codex"):
    try:
        return ADAPTERS[provider]
    except KeyError:
        raise ValueError("Unsupported provider") from None
