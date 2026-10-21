# Local burn coverage and recovery

Local token and API-equivalent dollar burn keep the five-minute event-time window,
including idle time. Enabled local Codex folders are included; imports and dashboard
filters do not change the calculation. Missing prices affect dollar coverage only.

## Indexing and coverage

`live_index.py` deduplicates changed file paths (including move destinations),
coalesces updates for five seconds, and schedules discovery independently every
30 seconds. Continuous appends cannot keep postponing the first queued update.
`index_scan.py` cooperatively schedules recent paths ahead of historical work.
`index_file.py` reads to a captured byte boundary, yields during parsing, and
publishes each completed file through the existing reconciliation and projection
transactions. Standalone scans finish their captured inventory; the running app
continues fallback discovery. One indexing worker owns writes.

Coverage version 1 adds source checks, pending paths, file coverage, and retry
metadata without replacing existing checkpoints or history. Upgraded indexes are
unverified until checked. Coverage advances after projection commits. Every source
is evaluated separately; a healthy source cannot mask another source's gap.

Errors are excluded from the window only with validated event-time evidence for
every physical record. File modification time determines scheduling priority,
never measurement completeness. Unknown relevance, parse gaps, incomplete tails,
and unresolved history conflicts remain incomplete. This deliberately favors an
honest Partial reading over an unjustified Complete reading.

Access/read failures retry after 5, 30, 120, then 300 seconds, including unchanged
files. Deterministic failures retry after file/parser changes or explicit refresh.
Successful ingestion clears errors. Existing session-context model/tier attribution
and dated pricing are reused; unpriced usage is never assigned zero cost.

Overview and Accounts share labels, explanations, and links to Sources diagnostics.
Polling preserves keyboard focus. Database read failures retain a previous reading
as stale, or show unavailable if none exists.

## Validation (2026-10-20)

- Full Python suite: 575 passed before the final interrupted-copy regression was
  added; 25 focused tests passed after the final changes, including that regression.
- Frontend production and widget builds passed. The existing large-chunk warning
  remains.
- Headless Edge checks passed for matching warnings, source navigation, focus
  retention, pricing/idle/unavailable states, and narrow layouts. Screenshots were
  inspected.
- `scripts/qa_live_burn.py`, 10,000 already indexed historical files and 20 active
  updates: watcher p95 4.937 seconds (max 5.140); fallback p95 30.406 seconds
  (max 30.610). Both meet the 10/35-second targets. Cooperative interruption during
  historical parsing is also covered by unit tests; the benchmark is not a claim
  about arbitrary disk speeds or first-time migrations.

Local validation artifacts are under `.local-data/partial-*`.

## Default-index recovery: promotion blocked

The running GUI used `%LOCALAPPDATA%/Codex Session Insights`. Live reads reproduced
SQLite's malformed-database error. The GUI was closed through its ordinary quit
command before preserving evidence. After shutdown, no WAL remained. The main
database, both backups, imported snapshots, and root JSON preferences were copied
to `.local-data/partial-recovery/evidence` and retained unchanged.

Full integrity checks passed for both backups and the post-shutdown main database.
The main database contained older history (October 8) than the newest backup
(October 20). This does not establish the cause of the original live error or
certify incident-time history and choices.

`scripts/prepare_index_recovery.py` built a separate candidate from the newest
verified backup and replayed available logs using existing reconciliation. The
candidate passes integrity checks. Preservation comparison could not certify 27
facts from each newer backup; the October 19 backup has different desktop preferences,
and the older main database has a different exporter identity. Therefore **no live
replacement or rollout was performed**. The GUI remains
closed. The report is `.local-data/partial-recovery/candidate/recovery-report.json`.

The comparison checks retained fact evidence, imported-only histories, project
memberships, review choices, and user settings. Unverified examples are listed in
the report; counts alone do not prove those facts were lost. Interrupted preparation
is marked and existing destination directories are never overwritten. Promotion
must remain blocked until every history/metadata discrepancy is accounted for,
incident-time choices are verified, and a rollback copy is retained.
