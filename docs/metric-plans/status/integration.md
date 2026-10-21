# Cache, reasoning and daily-session integration acceptance

Completed October 10, 2026 (America/New_York). All four metric groups are implemented, wired into Usage & Cost and standalone HTML reports, and verified. Both implementation owners finished before integration edited shared files. No commit, publication, release, reset, stash, live index, original log or credential change was made.

## Accepted behavior

| Metric | Result and independent evidence |
| --- | --- |
| Estimated cache discount | PASS. An independently generated parsed-log fixture with 600,000 cached reads at $2/$0.20 per million produced $1.08 in the backend and actual offline browser report. Independent numeric historical/tier/context/Fast cases produced $2.70, $2.16, $8.64, $2.16 and $5.832 respectively. Unknown, partial, no-cache, signed and tiny values, request boundaries, cache-write counterfactuals, and replay/copy reconciliation pass the focused suite. |
| Cache reuse rate | PASS. The independent 1,000,000-input fixture rendered 60%. Weighted aggregation, zero numerators, zero denominators, and invalid subsets with preserved raw counters pass. |
| Reasoning share | PASS. The independent 50,000-reasoning/200,000-output fixture rendered 25%. Reasoning remains a subset of output; weighted, zero and unavailable states pass. |
| Chats and agents per day | PASS. Independent copied/multi-day logs rendered Oct 1 counts of 1 main, 1 spawned and 1 system agent; Oct 2 zeroes; Oct 3 one main chat. The all-range distinct main total remained 1. Inherited pre-creation activity was excluded. Focused fixtures cover nested agents, forks, segments, copied sources, repeated records, both DST transitions, timezone rebuild, activity without tokens, canonical-source filters, merged projects, model/date filters, and imports. |

The built app was checked against actual synthetic backend API values, not only mocked interface fixtures. The independent log-to-index-to-report check verified exact cards and table rows, with HTTP(S) requests blocked and zero attempted network requests. Its full-page screenshot was visually inspected. The three series, integer axis, exact accessible table, zero-filled gaps, paging, empty states, signed values and coverage text were legible.

## Upgrade and consistency

Projection version 2 adds nullable cache facts to records and buckets and rebuilds from stored canonical facts. Existing-schema tests physically remove the new columns, reopen the index, read cached results, inject a rebuild failure, verify rollback, then retry using offline local facts and unchanged imported snapshots. Version/revision and records/buckets advance together only after success; repeated startup is idempotent. Before backfill, existing cached reads show unavailable discount and zero pricing coverage, never fully priced zero savings.

Deferred GUI maintenance and the previous no-window startup fix remain intact. Automated tests verify dashboard availability during a blocked maintenance job and correct results after it completes. All new query fields share the dashboard's read transaction, filters, timezone and revision, including a test that writes concurrently during the query. Public metric objects contain only aggregate values and day/count rows; report tests verify no added transcript or path fields. Existing account totals, local token burn, widget, summary-image, replay and malformed-file regressions pass.

## Validation

Scratch directory names below are anonymized; the recorded test results are unchanged.

Commands ran from `desktop-app`; browser commands used `PLAYWRIGHT_CHANNEL=msedge`. All artifacts and test indexes used the unique `.local-data/metric-integration-run-*` prefix.

- `PYTHONPATH=src .venv/Scripts/python.exe -m pytest -q --basetemp=.local-data/metric-integration-run-pytest` — **288 passed in 61.19s**. Includes [cache/pricing/migration tests](../../../tests/test_usage_metrics.py), [daily-session tests](../../../tests/test_daily_sessions.py), [startup/projection tests](../../../tests/test_projection_upgrade.py), and all existing Python regressions.
- `npm run build` in `frontend` — TypeScript, dashboard production build and widget production build passed. Initial sandbox Vite `realpath` EPERM was resolved by an approved local elevated retry.
- `node scripts/qa_metric_interface.mjs .local-data/metric-integration-run-browser` — passed focused data checks and built-interface browser checks: all card states, exact counts, date gaps/DST, keyboard paging, filters/drafts, refreshes, repeated navigation, narrow layout, real exporter and offline rendering without network.
- `node scripts/qa_token_activity_data.mjs`, `node scripts/qa_filter_state_unit.mjs`, and `node scripts/qa_account_identity.mjs` — passed.
- Isolated production demo server: `.venv/Scripts/python.exe -m codex_insights --demo --data-dir .local-data/metric-integration-run-server serve --port 48763`.
- Real demo report: `.venv/Scripts/python.exe -m codex_insights --demo --data-dir .local-data/metric-integration-run-report report --output .local-data/metric-integration-run-browser/demo-report.html` — passed.
- Against `http://127.0.0.1:48763`: `qa_ui.mjs` (with the demo report and a scratch screenshot path), `qa_filter_state.mjs`, `qa_token_kpi.mjs`, `qa_summary_images.mjs`, `qa_accounts.mjs`, `qa_widget.mjs` (with the report), `qa_token_activity.mjs` (with the report), and `qa_live_updates.mjs` — passed. Outputs are under the browser artifact directory above.
- Independent Python stdin acceptance generated synthetic main/copied/child/system logs under `.local-data/metric-integration-run-acceptance`, asserted exact formulas/counts, and exported `report.html` plus `expected.json`. An independent Edge stdin check verified actual API/card parity and that report's $1.08/60%/25% cards and three exact daily rows with zero network. Screenshot: `report.png` in that directory.
- Relevant `git diff --check` — passed; only existing CRLF normalization notices.
- `node scripts/qa_merges_allowance.mjs http://127.0.0.1:48763 .local-data/metric-integration-run-browser/merges` — passed bulk/single merge, undo, selection and scroll retention, queued feedback, cached allowance states and widget layout.

The live-update QA initially failed on a transient detached layout read and then on its stale mocked response filters. Integration corrected the fixture to echo applied request filters and custom bounds, and used retrying layout assertions. The full script then passed. No application repair was necessary for these failures.

## Files and handoffs

Implementation details and ownership are recorded in [backend.json](backend.json) and [interface.json](interface.json). Backend modules: [usage_metrics.py](../../../src/codex_insights/usage_metrics.py), [session_presence.py](../../../src/codex_insights/session_presence.py), [pricing.py](../../../src/codex_insights/accounting/pricing.py), [projection.py](../../../src/codex_insights/projection.py), and the storage/bucket/query integration. Frontend modules: [usage-metrics.ts](../../../frontend/src/usage-metrics.ts), [daily-sessions.ts](../../../frontend/src/daily-sessions.ts), and the separate chart/data modules.

Integration updated [metric documentation](../../metrics.md), [README](../../../README.md), the existing [live-update QA fixture](../../../scripts/qa_live_updates.mjs), and this report. Substantial earlier uncommitted work was preserved. Screenshots remained in scratch storage; `docs/dashboard.png` was not overwritten.

The isolated demo server was stopped after acceptance, and its port was checked for remaining listeners. Browser QA closed its own browser processes. No user app process was stopped.

## Limits

- Native packaged EXE/macOS behavior was not tested in this pass. Source-level startup tests and production browser/widget checks passed.
- During deferred projection maintenance, cached summary values remain visible and daily sessions are an empty array until version 2 commits; users should wait for Updating usage index to finish before interpreting daily counts. Discount coverage stays conservative during that interval.
- Missing activity/model facts cannot be reconstructed. Older portable histories recover models from available event facts, otherwise activity remains Unknown. Source filters intentionally follow canonical winners rather than every physical copy.
- Estimates use the configured dated catalog, with no live price refresh, subscription-savings claim, or real account access.
