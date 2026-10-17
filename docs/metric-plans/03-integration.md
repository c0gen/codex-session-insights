# Verify and finish the new metric feature

Read README.md and assignments.json in this directory. You own end-to-end completion after the backend and interface implementations finish.

## Coordination

Prepare independent acceptance cases now without modifying files owned by active implementation chats. Use compact wait_threads calls for the two IDs in assignments.json with retained cursors and 30000 to 60000 ms waits. Read their result JSONs and final summaries after they finish. Do not end the task just because they are still working. Do not message or steer unrelated chats, and do not create additional chats.

The previous bug integration has finished; preserve its projection-version, startup, replay, parser-isolation, account identity, and filter fixes. The same checkout may also contain other uncommitted user work. Reread current files and make surgical changes.

## Acceptance work after both owners finish

1. Independently verify the four metric groups against small synthetic fixtures and direct expectations. In particular: 60 percent cache reuse, 25 percent reasoning share, and a 1.08 USD cache discount under the README fixture rates; exact distinct daily counts for main, spawned, and system sessions.
2. Check that cache discount is the difference for cached reads at otherwise identical rates/usage. Validate unknown and partial price coverage, historic dates, service tiers, long-context rates, assumed Fast blend, cache-write treatment, signed differences, precision, and aggregate weighted ratios.
3. Check active-session semantics across multi-day chats, repeated records, segments, duplicate sources, parent replay, project grouping, model/source/date filters, display timezones, DST, inactive dates, and empty ranges. Confirm that daily totals need not sum to all-range distinct chats and that the UI explains this.
4. Check old-schema/index upgrade using stored local and imported facts, failure rollback, repeated startup, and deferred GUI maintenance. New fields must not trigger the previous no-window startup regression or temporarily claim correct zero coverage when data has not been backfilled.
5. Run the complete Python suite with a unique .local-data basetemp, frontend npm run build, calendar checks, focused new metric tests, filter-state checks, and relevant browser QA against an isolated synthetic demo server. Include actual offline HTML report rendering with no network access. Preserve current summary-image, token KPI, account, local burn, and widget expectations; run their checks where changes affect them.
6. Fix integration regressions after owners finish. Inspect the final relevant diff and verify no private facts, IDs, credentials, or paths have entered public metrics or transfers.
7. Update docs/metrics.md and README.md with formulas, active-day/session definitions, coverage semantics, upgrade behavior, and where users can find the feature. Keep this as repository documentation. No live price refresh, billing claims, or unrelated new metrics are needed.
8. Stop isolated test servers and leave user app processes, original session logs, real indexes and credentials untouched. Do not publish, release, or commit.

## Completion

Write docs/metric-plans/status/integration.md with per-metric acceptance, migration behavior, exact tests, source links, and any limitations. Only report completion when all four metric groups are implemented, wired into the app and offline reports, and verified. If any required outcome remains blocked, state the concrete remaining issue instead of claiming success. Native packaged behavior is unverified unless actually tested.

