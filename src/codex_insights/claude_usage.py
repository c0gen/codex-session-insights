"""Claude plan limits read through the installed, unmodified Claude Code.

Claude Code signs in on its own. This module never reads Claude credentials,
calls Anthropic endpoints itself, or requests a model turn: `/usage` is a local
command whose documented SDK result carries a structured `usage_report`.
Readings stay in memory and never enter SQLite, snapshots, or reports.
"""
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import time

from .cli_usage import UsageCommand
from .account_polling import PollingCache
from .account_rpc import AllowanceError
from .codec import timestamp
from .providers.bridge_io import MAX_INPUT

# No transcript (it would be indexed as a session) and no user hooks, MCP
# servers or plugins on every poll.
ARGUMENTS = ("-p", "/usage", "--output-format", "stream-json", "--verbose",
             "--no-session-persistence", "--safe-mode")
# Keys that would switch the child away from the user's own Claude sign-in.
REMOVED_ENVIRONMENT = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_OAUTH_TOKEN")
MAX_ROWS = 32


def find_claude():
    found = shutil.which("claude.exe" if os.name == "nt" else "claude")
    if found:
        return found
    # Documented native-installer location, often missing from PATH.
    candidate = Path.home() / ".local" / "bin" / ("claude.exe" if os.name == "nt" else "claude")
    return str(candidate) if candidate.is_file() else None


def _text(value, limit):
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def _scope_label(scope):
    if not isinstance(scope, dict):
        return None
    for key in ("model", "surface"):
        item = scope.get(key)
        label = _text(item.get("display_name"), 100) if isinstance(item, dict) else None
        if label:
            return label
    return None


def find_report(output):
    """Return the documented `usage_report` from stream-json output, or None."""
    for line in output.splitlines():
        try:
            value = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            continue
        if not isinstance(value, dict) or value.get("type") != "assistant":
            continue
        message = value.get("message")
        report = value.get("usage_report")
        if report is None and isinstance(message, dict):
            report = message.get("usage_report")
        if isinstance(report, dict):
            return report
    return None


def normalize_report(report):
    """Allowlist only limit rows; drop message text, costs and identity."""
    if not isinstance(report, dict):
        raise AllowanceError("no_report", "Claude Code returned no usage report. Run `claude update`, then refresh.")
    limits = report.get("rate_limits")
    rows = limits.get("limits") if isinstance(limits, dict) else None
    if not isinstance(rows, list):
        raise AllowanceError("no_limits", "Claude Code returned no plan limits. Sign in to Claude Code with a Pro or Max plan, then refresh.")
    buckets, seen = [], set()
    for row in rows[:MAX_ROWS]:
        if not isinstance(row, dict):
            continue
        kind = _text(row.get("kind"), 64)
        percent = row.get("percent")
        if not kind or type(percent) not in (int, float) or not math.isfinite(percent) or percent < 0:
            continue
        label = _scope_label(row.get("scope"))
        identifier = kind if label is None else f"{kind}:{label}"
        if identifier in seen:
            continue
        seen.add(identifier)
        reset = timestamp(row.get("resets_at"))
        buckets.append({"id": identifier, "kind": kind, "group": _text(row.get("group"), 64),
                        "scope_label": label, "unit": "percent",
                        "remaining_percent": max(0, 100 - min(100, percent)), "used": None, "limit": None,
                        "resets_at": reset.timestamp() if reset else None,
                        "severity": _text(row.get("severity"), 32), "is_active": row.get("is_active") is True})
    return {"buckets": buckets}


class ClaudeUsageProvider(UsageCommand):
    label = "Claude Code"
    removed_environment = REMOVED_ENVIRONMENT
    missing_code = "missing_claude"

    def __init__(self, workspace, executable=None, timeout=30, discover=find_claude, popen=subprocess.Popen):
        super().__init__(workspace, executable, timeout, discover, popen)

    def version(self, executable):
        try:
            text = self._run([executable, "--version"], 10).decode("utf-8", "replace")
        except AllowanceError:
            return None
        return _text(text.splitlines()[0] if text else "", 60)

    def fetch(self, changed=None):
        executable = self.executable or self.discover()
        if not executable:
            raise AllowanceError("missing_claude", "Install Claude Code or add it to PATH, then refresh.")
        from .account_storage import protect_directory
        protect_directory(self.workspace)
        report = find_report(self._run([executable, *ARGUMENTS], self.timeout))
        if report is None:
            version = self.version(executable)
            raise AllowanceError("no_report", f"{version or 'This Claude Code version'} returned no usage report. "
                                 "Run `claude update` and sign in with a Pro or Max plan, then refresh.")
        return report



class ClaudeUsage(PollingCache):
    def __init__(self, directory, provider=None, enabled=False, allowed=True, clock=time.time,
                 interval=300, max_backoff=1800):
        provider = provider or ClaudeUsageProvider(Path(directory) / "claude-usage")
        # Retries never run `claude` more often than a healthy check does.
        super().__init__(provider, provider.fetch, normalize_report, lambda value: bool(value["buckets"]),
                         {"buckets": []}, enabled=enabled, allowed=allowed, clock=clock, interval=interval,
                         max_backoff=max_backoff, backoff_base=interval, missing_code="no_limits",
                         missing_message="Claude Code reported no plan limits for this sign-in.")
