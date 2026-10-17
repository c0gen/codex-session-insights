"""Plan allowance through the unmodified official Antigravity CLI, never private RPC."""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from .account_polling import PollingCache
from .account_rpc import AllowanceError
from .cli_usage import UsageCommand
from .providers.allowances import number, reset

ARGUMENTS = ("-p", "/usage", "--output-format", "json")
MIN_VERSION = (1, 1, 11)  # Google's August 7 release introduced read-only print commands.


def find_agy():
    found = shutil.which("agy.exe" if os.name == "nt" else "agy")
    if found:
        return found
    candidate = (Path.home() / "AppData/Local/agy/bin/agy.exe" if os.name == "nt"
                 else Path.home() / ".local/bin/agy")
    return str(candidate) if candidate.is_file() else None


def normalize_report(report):
    """Contract captured from official CLI 1.3.5; retain only quota metadata."""
    if not isinstance(report, dict):
        raise AllowanceError("invalid_report", "Antigravity CLI returned an unsupported usage report. Update agy and refresh.")
    command = report.get("command")
    if report.get("status") != "SUCCESS" or not isinstance(command, dict) or command.get("name") not in {"usage", "quota"}:
        raise AllowanceError("no_report", "No Antigravity quota report. Open agy and complete its native sign-in, then refresh.")
    # An ordinary agent result must never be interpreted as a quota report.
    usage = report.get('usage')
    if type(report.get("num_turns")) is not int or report['num_turns'] != 0 or not isinstance(usage, dict) or any(type(v) is not int or v != 0 for v in usage.values()):
        raise AllowanceError("invalid_report", "Antigravity CLI did not return a read-only quota report. Update agy and refresh.")
    data = command.get("data")
    groups = data.get("groups") if isinstance(data, dict) else None
    if not isinstance(groups, list):
        raise AllowanceError("no_limits", "Antigravity CLI reported no personal-plan quotas for this sign-in.")
    buckets, seen = [], set()
    for group in groups[:32]:
        if not isinstance(group, dict) or not isinstance(group.get("buckets"), list):
            continue
        label = group.get("name")
        label = label[:100] if isinstance(label, str) else None
        for row in group["buckets"][:32]:
            if not isinstance(row, dict):
                continue
            key = row.get("id")
            remaining = number(row.get("remaining_fraction"), high=1)
            if not isinstance(key, str) or not key or len(key) > 100 or key in seen or remaining is None:
                continue
            seen.add(key)
            buckets.append({"id": key, "kind": {"weekly": "seven_day", "5h": "five_hour"}.get(row.get("window"), key),
                "scope_label": label, "unit": "percent", "remaining_percent": remaining * 100,
                "used": None, "limit": None, "resets_at": reset(row.get("reset_time"))})
            if len(buckets) == 32:
                return {"buckets": buckets}
    return {"buckets": buckets}


class AntigravityUsageProvider(UsageCommand):
    label = "Antigravity CLI"
    missing_code = "missing_agy"
    removed_environment = ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GEMINI_BASE_URL")

    def __init__(self, workspace, executable=None, timeout=30, discover=find_agy, popen=subprocess.Popen):
        super().__init__(workspace, executable, timeout, discover, popen)

    def fetch(self, changed=None):
        executable = self.executable or self.discover()
        if not executable:
            raise AllowanceError("missing_agy", "Install the official Antigravity CLI (agy), sign in there, and refresh.")
        version = self._run([executable, "--version"], 10).decode("utf-8", "replace").strip()
        match = re.fullmatch(r"(?:agy\s+)?v?(\d+)\.(\d+)\.(\d+)(?:[\s+-].*)?", version)
        if not match or tuple(map(int, match.groups())) < MIN_VERSION or self.last_returncode != 0:
            raise AllowanceError("unsupported_agy", "Update Antigravity CLI to 1.1.11 or newer before checking quotas.")
        raw = self._run([executable, *ARGUMENTS], self.timeout)
        try:
            report = json.loads(raw)
        except (ValueError, UnicodeError):
            raise AllowanceError("no_report", "Antigravity CLI returned no quota JSON. Open agy to sign in, then refresh.") from None
        if self.last_returncode != 0:
            raise AllowanceError("no_report", "Antigravity CLI could not check quotas. Open agy to check its sign-in, then refresh.")
        return normalize_report(report)


class AntigravityUsage(PollingCache):
    def __init__(self, directory, provider=None, enabled=False, allowed=True, clock=time.time, interval=300, max_backoff=1800):
        provider = provider or AntigravityUsageProvider(Path(directory) / "antigravity-usage")
        super().__init__(provider, provider.fetch, lambda value: value, lambda value: bool(value["buckets"]),
            {"buckets": []}, enabled=enabled, allowed=allowed, clock=clock, interval=interval,
            max_backoff=max_backoff, backoff_base=interval, missing_code="no_limits", missing_message="Antigravity CLI reported no plan quotas for this sign-in.")
