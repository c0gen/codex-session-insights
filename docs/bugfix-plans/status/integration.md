# Six-bug integration acceptance

Completed October 10, 2026 (America/New_York). All six reviewed bugs pass combined acceptance. The four implementation chats and the separate local token burn chat finished before final integration validation. Existing uncommitted work was preserved; no commit, release, or publication was made.

| Bug | Result | Acceptance evidence |
| --- | --- | --- |
| B1: shorter copies replace fuller history | PASS | 330 tokens retained in either filename order, exact copies, append, restart and unchanged refresh. Divergent copies preserve accepted history and expose persistent diagnostics. Old checkpoints recover on reparse; source disable/enable/forget and portable transfers remain covered. |
| B2: independent child counters excluded as replay | PASS | Parent response at second 3 and independent child response at second 6 total 220. Preserved pre-spawn and aligned prefixes still deduplicate. Missing origin evidence stays uncertain. Existing local, offline and imported raw facts reproject automatically. |
| B3: incomplete account identities miscounted as certain | PASS | Only confirmed account IDs deduplicate. Unresolved connection counters remain available with identity_complete=false and an unverified warning. Fake RPC tests cover successful history after failed/timed-out allowance reads, same-email workspaces, identity transitions and privacy. Built headline tests cover unresolved-to-confirmed deduplication. |
| B4: persisted invalid dates trap startup | PASS | Invalid JSON/shape, empty/invalid/reversed dates recover to All time. Rejected/failed requests do not replace valid saved filters. Production UI and controller tests pass. |
| B5: HTML export uses unapplied filters | PASS | Export freezes applied filters when its dialog opens. Draft edits, pending requests, out-of-order responses and later modal-time completions cannot change them. Summary image applied-filter tests and standalone report checks pass. |
| B6: malformed nested payload stops scan | PASS | Malformed git, subagent/thread_spawn, settings and token structures fail per file, retain earlier accepted facts, and allow the healthy 110-token session to index. Diagnostics, unchanged-error suppression and manual retry pass; unrelated programming errors still propagate. |

## Existing-index correction

Parser version 3 revisits stale physical-file checkpoints once. Offline/disabled sources retain accepted contributions, and their checkpoints stay eligible for reparse when the source returns/is enabled. Transactional checkpoints and the durable projection queue retain restart/cancellation behavior. No original logs are modified.

Projection version 1 independently upgrades stored facts, including imported facts and offline local sources. In one SQLite transaction it reselects canonical sources, rebuilds records and metric buckets, updates replay diagnostics, clears fulfilled queue entries, increments data_revision, and finally writes the version. Failure rolls back the records, diagnostics, revision and version together; reopening retries. No snapshot reimport is required when the necessary raw facts already exist. Both repeated import of an unchanged snapshot and direct refresh perform the upgrade check.

GUI/exporter/serve startup defers the expensive correction until the window/server is available. The native window shows cached results with an Updating usage index banner, then receives corrected results through the normal revision update. Headless commands and ordinary Engine construction upgrade before returning query output. Synthetic tests explicitly block maintenance to verify that the GUI can still answer dashboard queries, then release it and verify 110 becomes 220.

The user's report that GUI launch stayed busy without a window exposed a pre-window maintenance path introduced during integration. That work now runs after native load. Native logs verify window creation/show/load while the upgrade job is still running. This was validated on synthetic data; the user's actual running process and real index were not modified.

## Validation

- Full final Python suite: `.venv/Scripts/python.exe -m pytest -q --basetemp=.local-data/integration-final-startup-01a128d4` — **258 passed in 51.82s**. Includes six new upgrade/startup tests and all account, local burn-rate, ingestion, replay, source/transfer, desktop, widget and summary-image tests.
- Production frontend: `npm run build` in `frontend` — TypeScript, dashboard Vite build and widget Vite build passed.
- `node scripts/qa_token_activity_data.mjs` — passed calendar gaps, leap years, DST, range and shared summary-image date checks.
- `node scripts/qa_filter_state_unit.mjs` and `node scripts/qa_account_identity.mjs` — passed.
- Headless Edge against production assets and an isolated demo server: `qa_ui.mjs` with an actual standalone HTML report; `qa_filter_state.mjs` using the production URL; `qa_token_kpi.mjs`; `qa_summary_images.mjs`; `qa_accounts.mjs`; `qa_live_updates.mjs`; `qa_merges_allowance.mjs`; and `qa_widget.mjs` — all passed.
- Windows native prerequisite check and hidden demo GUI smoke — passed. Updated native smoke confirms Overview, canvas, bridge and a running maintenance job together.
- `./scripts/check_desktop.ps1 -WidgetOnly` — passed normal native startup, tray close/reopen, relaunch activation, settings, all metric combinations, native widget scaling from 100–200%, account rows, menus, positioning, tray failure recovery and clean exit. Image clipboard checks were intentionally skipped.
- Relevant diff whitespace check — passed. Final dashboard screenshot inspected; QA artifacts are under `.local-data/integration-01a128d4`, and native controller evidence is under `.local-data/desktop-check-4b1ee89878ae4203aee884d310500bd3`.

Initial sandbox restrictions prevented Vite realpath resolution and browser access to the sandboxed server. Approved local retries resolved those environment failures. One new KPI expectation was corrected from `1.0K` to the existing `1K` format. A summary-image fixture declaring custom dates without start/end was corrected to satisfy the validated response contract. All final runs above passed after those adjustments. Both isolated demo servers and all native test processes exited; `docs/dashboard.png` was not overwritten by integration.

## Changed files

Implementation-owner changes are detailed in [ingestion.json](ingestion.json), [replay.json](replay.json), [accounts.json](accounts.json), and [filters.json](filters.json). They cover the storage/parser, replay reconciler, account identity/provider/aggregation/headline, filter controller/main UI, and their focused tests.

Integration changed:

- `src/codex_insights/projection.py`: versioned atomic upgrade and progress callback.
- `src/codex_insights/service.py`, `cli.py`, `ingestion.py`, `transfers.py`: GUI/CLI/refresh/import upgrade entry points and deferred native maintenance.
- `frontend/src/account-types.ts`, `token-kpi.ts`: explicit identity coverage contract.
- `tests/test_projection_upgrade.py`, `tests/test_account_totals.py`: upgrade, rollback, offline/import, GUI/CLI and explicit confirmed-identity fixtures.
- `scripts/qa_filter_state.mjs`: optional production-server URL.
- `scripts/qa_token_kpi.mjs`: confirmed coverage metadata and unresolved-to-confirmed UI transition.
- `scripts/qa_summary_images.mjs`: valid custom-range fixture.
- `docs/release-notes.md` and this acceptance report.

## Remaining limits

- A previously exported snapshot that omitted a longer history cannot reconstruct missing events; it needs the originating files or a corrected export. Stored replay facts need no replacement snapshot.
- Copy-conflict warnings deliberately persist after a divergent file disappears; forgetting its source removes the warning. Snapshots export accepted facts, not local conflict metadata or private physical paths.
- Without a stable server account ID, identity remains unverified. A history read may wait for its identity probe timeout, but successful history is still retained and published without stale identity proof.
- HTML reports capture applied filters and query the index at export time; they do not freeze the entire displayed data revision while the dialog is open.
- GUI cached totals may be shown during the visible upgrade job. Final corrected records become visible after its atomic commit.
- Windows source-mode native behavior was tested. Packaged EXE behavior, macOS packages, and persistent native image clipboard behavior were not validated in this pass. No real account provider, real credentials, original session logs, or real user index was used for acceptance.
- Optional notify_andy tools were unavailable; no external notification was sent.
