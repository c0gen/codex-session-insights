# Claude history recovery (0.1.6)

Version 0.1.6 fixes Claude sub-agent histories that earlier exporters could group with their parent or with another parent's agent. Recovery runs automatically during refresh, with a separate SQLite backup and restartable staging. Keep the existing data directory: it contains checkpoints and alternatives that older exports omitted.

The **Claude history recovery** panel in Sources reports newly included responses/tokens and the actual before/after change in accounted usage. **Review conflicts** distinguishes agent identity verification from genuine disagreements. Alternative-only tokens are deduplicated against accepted responses, but remain potentially excluded usage until their identity is verified. Do not add the recorded counters of every conflicting version together.

## Audit and recover the Intel Mac

Close the existing exporter before collecting the baseline. Build 0.1.6 on the Intel Mac using the source archive and the existing `scripts/build_mac.sh` instructions. The build includes the packaged identity-recovery smoke test and native exporter launch validation. No native Intel Mac binary can be built or validated on Windows.

From the extracted source folder, with x86_64 Python 3.11+ and Node installed:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,mac-build]'
npm ci --prefix frontend
bash scripts/build_mac.sh
```

With the source installed in its virtual environment, run these commands from the source folder. Honor `CODEX_INSIGHTS_DATA_DIR` if this Mac uses a custom location; otherwise use the directory below.

```sh
index="$HOME/Library/Application Support/Codex Session Insights"
.venv/bin/python -m codex_insights --data-dir "$index" diagnose-history --output before-claude-recovery.json
.venv/bin/python -m codex_insights --data-dir "$index" scan
.venv/bin/python -m codex_insights --data-dir "$index" diagnose-history --output after-claude-recovery.json
.venv/bin/python -m codex_insights --data-dir "$index" export --output recovered-mac.codex-insights
```

`diagnose-history` opens no app/index manager, performs no migrations, and writes no logs or sidecars beside the original database. For a database with committed WAL pages it reads a temporary copy in bounded memory, checks that the original files stayed stable, and discards the copy. If the index changes, close the app and retry. Diagnostic reports may contain local file locations; usage snapshots exclude those locations and conversation content.

The backup is `insights.before-claude-identity-v1.sqlite3` beside the index. It includes committed WAL data and is verified before recovery starts. The app deletes it 14 days after every recovery has completed; a later recovery creates and verifies a new backup first. A backup failure stops recovery. Existing backups, logs, source settings, exporter ID and export revision are preserved. Cancellation leaves accepted accounting intact; completed staging resumes on the next refresh.

Compare the two diagnostic reports by provider and reason. Verify each original conflict is either separated into proven parent/agent histories, still represented by retained divergent versions, or explicitly awaiting original evidence. A lower warning count alone does not establish complete recovery. Newly included tokens and the net accounted-token change are separate measures because responses already counted elsewhere stay deduplicated.

For offline or unreadable sources, reconnect the original logs and refresh. Agent identity cannot be inferred from matching aggregate token counters. Earlier choices spanning separate agents are archived and reopened; valid choices within one logical history are retained.

## Replace the Windows import

Install the Windows 0.1.6 build, then import `recovered-mac.codex-insights`. Keep the Mac's existing exporter identity: the higher snapshot revision atomically replaces that Mac's previous imported contribution. Reimporting the same snapshot is a no-op. A snapshot contains only locally observed histories; imported-only facts are not re-exported.

Transfer format stays at v6, and v1–v6 imports remain supported. Older recognized agent identities can be upgraded from structured facts, but v1–v5 snapshots never contained rejected alternatives. Complete recovery of those alternatives must happen against the Mac's original index/checkpoints/logs, followed by a fresh export. The recovery panel flags that limitation.

The local `claude_history_recovery` API returns persisted source recovery reports. `history_conflicts` adds classification, parent identity, reason codes, alternative-only response/token counts and disputed-counter counts. Both APIs remain read-only; refresh performs automatic recovery.
