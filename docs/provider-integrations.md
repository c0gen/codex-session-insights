# Local provider integrations

Reviewed on **2026-10-14**. Antigravity collection uses documented local interfaces and the installed, unmodified official CLI. No direct authenticated provider requests, credential extraction, private RPC, or encrypted archive collection are performed by Insights.

## Antigravity usage and allowance

The public transcript location is `brain/<conversationId>/.system_generated/logs/transcript.jsonl`, under `~/.gemini/antigravity`, `antigravity-cli`, or `antigravity-ide`. The parser recognizes `created_at`, `step_index`, `type`, and the recorded top-level `input_tokens`, `cache_read_tokens`, and `output_tokens`. Input includes recorded uncached input plus cache reads. Total adds recorded output once. Missing components remain unavailable; cache-write counts and reasoning text are never inferred. Numeric thinking counts are used only when explicitly recorded. Unknown models remain unpriced.

Observation identity includes the conversation, step index and recorded creation time. Repeated snapshots do not increment usage; rewritten or compacted logs retain previously observed steps and reconcile matching identities. Parser/checkpoint version 2 rereads files previously skipped by the Claude-shaped parser. Claude Code and older supported public JSONL remain compatible. No prompts, responses, raw errors, tool arguments, or transcript contents enter facts.

[Official hooks](https://www.antigravity.google/docs/hooks) receive passive `PostInvocation` and `PostToolUse` handlers returning `{}`. They register only the documented transcript path and sanitized project/model metadata. Windows commands use an encoded PowerShell launcher and direct process arguments to preserve spaces, quotes and Unicode. Setup updates only owned entries, retains the original setting for uninstall, and leaves user-modified hooks intact. Existing status-line output is forwarded.

**Check Antigravity allowance** runs the official `agy -p /usage --output-format json`. CLI versions older than 1.1.11 or unknown versions are rejected before `/usage` is invoked. Google's [changelog](https://www.antigravity.google/docs/changelog?tab=cli) documents these read-only commands as requiring no model turn, quota spending or saved conversation. The structured quota contract was captured from official CLI **1.3.5**: `command.name=usage`, `command.data.groups[].buckets[]`, including `id`, `window`, `remaining_fraction`, and `reset_time`. The sanitized test fixture retains only quota metadata and zero-turn usage; account identity, conversation identifiers, descriptions and response text are excluded.

Use Google's [official installation and sign-in](https://www.antigravity.google/docs/cli/install/). The Windows fallback path is `~/AppData/Local/agy/bin/agy.exe`; macOS/Linux use `~/.local/bin/agy`. The CLI owns authentication. Insights removes API-key environment overrides and never reads credentials. Checks run every five minutes while enabled, with a 30-second timeout, manual refresh, and backoff to 30 minutes. Demo and exporter modes cannot fetch quotas. Readings stay in memory and are excluded from SQLite, reports and transfers.

The optional [CLI status line](https://www.antigravity.google/docs/cli/statusline) remains supported. The newest successful CLI check or status-line reading wins. Buckets retain their identities and group labels. Zero means exhausted; missing means unavailable. Failed checks retain the prior reading with its age; crossing a reset hides the old percentage without assuming replenishment. Dashboard and widget use the same cache. Refresh all refreshes enabled Claude and Antigravity checks.

## Other providers and portable data

Claude Code retains the documented status-line and optional official `/usage` integration. Codex account collection and accounting remain unchanged. Provider identity is independent of model identity: Claude models used in Antigravity remain Antigravity usage.

Transfers now use **v6** to preserve optional Claude speed and inference-geography enums alongside service tier, cache-write durations, nullable public Antigravity components and step identities. Claude parser version 2 backfills this metadata on the next scan; projection version 5 reprices stored history even when source folders are offline. Opus 5.5 and Sonnet 5.5 use verified launch-date token prices; unlogged modifiers assume Standard/global. Imports from v1, v2, v3, v4 and v5 remain accepted, including previously indexed encrypted-archive facts. [Legacy archive collection](antigravity-legacy.md) is disabled at source setup, refresh, reader, key-access and diagnostic entry points. Existing indexed history and original files remain intact.

The consumer [Antigravity terms](https://www.antigravity.google/terms) and [Google terms](https://policies.google.com/terms?hl=en-US) apply to personal accounts. Documented hooks and CLI commands are the integration basis; this is not a contractual assurance from Google.

## Validation

Run `scripts/check.ps1` for Python, frontend data checks and production dashboard/widget builds. `tests/test_antigravity_public.py`, `test_antigravity_usage.py`, and `test_provider_windows_launcher.py` cover native record shapes, nullable/zero counters, deduplication, rewritten logs, private transfers, native Windows quoting/stdin/stdout, owned upgrades, CLI version gates, quota errors and stale readings. The legacy compatibility tests preserve previously accepted accounting without enabling archive collection.

Before live parser migration, `scripts/audit_antigravity_index.py` backs up the index and verifies the copy. If SQLite reports corruption, it preserves an explicitly unverified evidence copy and never resets the live index. Validate the integration in a separate index until recovery is completed.
