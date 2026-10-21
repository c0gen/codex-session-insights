# Startup and live-rate release work

Implementation and local validation: October 21, 2026. Windows is the performance priority. Mac compatibility is retained; execution and performance certification on Mac hardware remain pending.

## Behavior and compatibility

The native window and local asset server open before database initialization, migration backups, and projection upgrades. A compatible `overview-cache.json` supplies the last successful aggregate overview, visibly dated while new results load. It excludes account responses and credentials, and removes source paths and diagnostic details. Filters, source inclusion, pricing, timezone, local date, and projection/schema context invalidate incompatible snapshots. Account-provider refresh intervals remain unchanged.

The live entry bundle is 307.71 kB (105.14 kB gzip), down from approximately 1.37 MB. The 1.067 MB gallery chunk and its assets load when Visualizations opens. A separate report build embeds gallery dependencies into standalone HTML; offline reports retain all exhibits and fallbacks.

The visible dashboard polls one `live_status` response every two seconds and suspends polling when hidden. Account, allowance, rate, and desktop updates change their panels without rebuilding the dashboard. Usage and project details load when those tabs open. Analytics are cached by data revision, filters, timezone, date, source health, and accounting context. Previously loaded compatible views remain available during asynchronous recalculation with a timestamped notice. Failed refreshes retain previous results with retry available. Full dashboard responses remain synchronous for CLI, reports, and compatibility callers.

Diagnostic reads use small session metadata and overlap summaries. Filtered diagnostics select matching session IDs first. Dashboard and rate queries do not read historical facts or parser checkpoints. Codex updates project affected sessions, descendants, and accounting dependencies. Other providers maintain response-ownership claims and revisit competing histories when ownership changes.

There is still one owning writer. Parsing, discovery queue construction, projection, imports, Claude recovery, and rebuilds yield between committed batches. Watcher events retain five-second coalescing; fallback discovery retains its 30-second interval. Rebuilds use a restartable shadow projection. Imports and recovery use private preparation databases, catch up local Codex changes, and publish totals and checkpoints atomically. Incompatible preferences or unrelated histories accepted after a restart invalidate paused preparation. Failures/cancellation preserve accepted data. Staging needs additional disk space; the preceding metric generation is reclaimed at the next preparation.

Live coverage separately reports the last successful check, live pending work, historical pending work, and delay reasons. Historical bounds require validated timestamps for every physical record and the exact parsed file size/mtime. Changed or watcher-reported files lose old bounds. Unknown timestamps, incomplete records, failures, offline sources, and unresolved histories cannot certify complete coverage. Pricing gaps affect dollar burn only. Five-minute calculation, local Codex scope, and stale/unavailable semantics remain intact. Waiting and stale readings also carry current indexing progress.

### Release-review corrections

Reprojection settings and source mutations record a durable request in their transaction. Startup and headless queries resume that request even when the projection version is current. Compatible staging progress survives interruption; changed targets restart staging. Accepted timezone and pricing remain active for live work until atomic publication accepts the target configuration, metrics, version, and revision. Legacy staging with unverifiable prior configuration displays an updating state until recovery completes.

Analytics capture their revision, accounting context, filters, local date, and source health in the same read transaction. Exact-current entries and the latest compatible completed result are separate: continuous writes no longer prevent completed results from advancing the overview. Generation and query ordering prevent older completions replacing newer results, including the aggregate startup snapshot. Incompatible views and configurations remain isolated; caches and retry errors are bounded.

Source verification and finalization run incrementally during normal scans, cooperative maintenance, and recovery. Each discovery generation finalizes independently once its file and projection work completes. Unchanged reconnected folders can become Ready during another job; cancellation, incomplete discovery, or newer errors prevent stale finalization. Ready still does not certify Complete coverage. Finished generations perform no repeated idle verification.

Transient indexing and refresh notices occupy a fixed bottom-right panel instead of moving dashboard content. Completed job and refresh notices remain readable for five seconds; completed jobs can also be dismissed.

## Modules and interfaces

| Responsibility | Module |
|---|---|
| Early shell/background initialization | `deferred_engine.py` |
| Aggregate query/startup caches and transaction identity | `dashboard_cache.py`, `query_snapshot.py` |
| Session diagnostics, overlaps, ownership, change journal | `hot_metadata.py` |
| Owning-writer live interleaving | `cooperative.py`, `index_scan.py`, `index_file.py` |
| Restartable projection generations and durable configuration | `staged_projection.py`, `projection_state.py` |
| Incremental source verification/readiness | `source_finalization.py` |
| Private import/recovery preparation/publication | `isolated_jobs.py` |
| Durable time evidence/cached coverage | `index_health.py`, `burn_coverage.py` |
| SQLite selection/release gate | `sqlite_bootstrap.py`, `sqlite_runtime.py` |

`bootstrap` returns readiness, initialization errors, and an optional dated cached overview. `live_status` returns readiness, data revision in job status, indexing progress, coverage/freshness, cached provider readings, lightweight account totals, and desktop state. Full account history is included only when requested. Full `dashboard` and transfer formats remain supported. `_view` selects reduced interactive data; `_background` allows compatible previous results during recalculation; `_retry` retries a failed calculation.

Both lightweight responses optionally include `projection: {pending, readable}`. Snapshot identity remains internal; the public analytics fields `revision`, `generated_at`, and `analytics_refreshing` are preserved. Startup snapshot format version 2 invalidates earlier incompatible cache files and retains the aggregate-only privacy allowlist.

## SQLite packaging gate

Windows and Mac release scripts require SQLite **3.51.3 or later** before packaging and invoke the packaged executable to check the library it actually loads afterward. Direct Windows app-spec builds also enforce the minimum. This follows SQLite's [WAL-reset bug advisory](https://www.sqlite.org/wal.html#walresetbug); it does not establish the cause of the earlier index incident.

Provision a trusted Windows x64 DLL with:

```powershell
.venv/Scripts/python.exe scripts/prepare_sqlite_runtime.py <trusted-sqlite3.dll>
.venv/Scripts/python.exe scripts/check_sqlite_runtime.py
```

The preparer verifies exports/version and writes version, source ID, and SHA-256 under `.local-data/sqlite-runtime/`. Packaging verifies the hash and substitutes this DLL for Python's older DLL. Machine-wide Python remains unchanged. The tested package loads SQLite **3.53.1**, SHA-256 `fcb5037bce6ad124d304352e215a756dfcb9256796c5d0caa8a148d5dea056ca`, provisioned from the trusted installed Codex workspace dependency runtime. On Mac, use Python linked to a supported SQLite; both pre- and post-build gates must pass.

Recovery remains explicit. Preserved evidence and the uncertified recovery candidate were not modified or promoted. Benchmarks use disposable copies. Migration backups remain conditional on an actual upgrade; routine launch does not perform recovery or a full integrity audit.

## Local validation

The complete Python suite passed **618 tests**, followed by all nine frontend data checks and production app/report/widget builds. The three review failures were first reproduced with deterministic regression tests. Added lifecycle tests cover interruption before staging, during projection, and before publication, current-version startup recovery, configuration changes, live appends, and atomic acceptance. Cache tests cover consecutive writes during queries, snapshot identity, older concurrent completions, and incompatible configuration. Source tests cover independent readiness, cancellation, offline/newer errors, incomplete tails, bounded verification, and idle idempotence. Existing accounting, coverage, transfer, and release-performance regressions pass. Browser checks, packaged transfer/review/recovery smoke checks, and native tray/widget checks also passed; earlier offline gallery/PNG validation remains recorded under `.local-data/token-worlds-qa`.

| Measurement | Result | Scope |
|---|---:|---|
| Native shown event | p95 1.844 s | Five rebuilt packaged launches; isolated synthetic data; hidden smoke window |
| Cached overview visible | p95 183 ms | Five production Edge loads; mocked initialization/API delay |
| Startup bundle | 307.71 kB | Production entry JS; gallery requested on navigation |
| Cached overview query | p95 2.3 ms | Disposable preserved-index copy |
| Startup snapshot read | p95 14.4 ms | Same copy |
| Live-rate read | p95 1.0 ms | Same copy, warmed coverage cache |
| Fresh overview calculation | p95 1.154 s | Five runs; 9,385 sessions, 1,153,726 records |
| Full compatibility dashboard | p95 5.011 s | Same fixture; original diagnostic path exceeded 45 s |
| Codex dependency expansion | 1 session | Inspected update previously expanded to 54 |

These runs do not flush the operating-system disk cache. One-time small-summary initialization on the copied index took 15.834 seconds in the background; startup snapshot display does not wait for it.

Each live workload used 10,000 physical historical files, 600 additional mixed-provider sessions, and 20 continuous usage appends:

| Concurrent work | Watcher p95 | Fallback p95 |
|---|---:|---:|
| Projection rebuild | 4.875 s | 30.343 s |
| Import | Superseded | Superseded |
| Forced file backfill | 4.953 s | 9.156 s |

The original import measurement used synthetic session fingerprints rejected by transfer validation, so it did not establish latency during a valid import. The corrected fixture validates facts before running and fails immediately if the maintenance job fails. New reconnect workloads use 2,400 additional mixed-provider sessions, 10,000 physical historical files, and 20 appends. Both watcher and fallback runs require the reconnected source to become Ready before unrelated maintenance ends:

| Concurrent work with disconnect/reconnect | Watcher p95 | Fallback p95 |
|---|---:|---:|
| Validated import | 5.438 s | 27.047 s |
| Projection rebuild | 4.140 s | 30.141 s |

Production browser checks also verify unchanged dashboard position while notices appear, five-second completion readability, displayed totals advancing through three refreshes during continuous writes, and the legacy projection updating state recovering. Evidence is in `.local-data/review-ui-02`, `.local-data/review-native-startup`, `.local-data/review-reconnect-import-02`, and `.local-data/review-reconnect-rebuild-04`. The rebuilt Windows package passes transfer/recovery smoke checks and all 19 native tray/widget checks; its actual SQLite runtime is 3.53.1.

These times measure appends reaching queryable usage, with the final five-minute rate verified. They do **not** measure a physical displayed pixel. Two-second browser polling was tested separately. Native widget checks cover tray/relaunch, 100–200% scaling, populated metrics/accounts, recovery, menus, sizing, and quitting during work. Results and screenshots are under `.local-data/release-*` and `.local-data/token-worlds-qa`.

Reproduce checks with new output directories:

```powershell
.venv/Scripts/python.exe scripts/qa_live_burn.py --output .local-data/new-live-check --workload backfill
.venv/Scripts/python.exe scripts/qa_live_burn.py --output .local-data/new-import-check --workload import
.venv/Scripts/python.exe scripts/qa_live_burn.py --output .local-data/new-rebuild-check --workload rebuild
.venv/Scripts/python.exe scripts/qa_live_burn.py --output .local-data/new-reconnect-check --workload import --reconnect
node scripts/qa_release_performance.mjs .local-data/new-ui-check
.venv/Scripts/python.exe scripts/benchmark_startup.py dist/CodexSessionInsights/CodexSessionInsights.exe --output .local-data/new-startup-check
.venv/Scripts/python.exe scripts/benchmark_release.py --fixture <preserved-index> --output .local-data/new-index-check
```

The fixture benchmark normally uses SQLite backup. `--offline-fixture` requires a closed file with no WAL and verifies unchanged size/mtime during copying. `--reuse-copy` remeasures an existing separate benchmark directory. Never point outputs at accepted data or recovery evidence.

## Remaining release gates

- Fresh large-index analytics still exceed the one-second p95 target. Compatible cached responses are immediate; a new filter or revision needs calculation.
- Certify visible packaged startup, cached overview, and actual displayed rate latency together on a representative Windows SSD, including large individual logs, sustained appends, and all maintenance modes. The native shown-event and browser checks above measure separate parts of that path.
- Run the Mac package, compatibility checks, and actual SQLite gate on Mac hardware. Equivalent Mac performance certification remains deferred.
- Complete the independent history/metadata audit before considering recovery-candidate promotion.
