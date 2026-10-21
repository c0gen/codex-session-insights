# Codex Session Insights bug fix plan

Fix the six reproduced review findings in the current desktop app while preserving existing features and uncommitted work. Four implementation owners work on separate files. A fifth owner integrates the fixes, repairs existing indexed data where needed, and verifies the complete app.

All five chats use GPT-6 Astra with Medium reasoning. Paths in these plans are relative to the repository root unless stated otherwise. Keep live chat/project identifiers and machine-specific paths in ignored `.local-data/planning/` records, not in committed planning documents.

## Scope and assignments

| Owner | Bugs | Plan |
| --- | --- | --- |
| Ingestion | B1 shorter duplicate overwrites fuller history; B6 malformed nested payload aborts scanning | [Ingestion](01-ingestion.md) |
| Replay accounting | B2 independent child usage is incorrectly excluded as replay | [Replay accounting](02-replay-accounting.md) |
| Account identity | B3 unresolved identities cause false merging or double counting | [Account identity](03-account-identity.md) |
| Filter state | B4 invalid persisted dates break startup; B5 HTML export uses unapplied filters | [Filter state](04-filter-state.md) |
| Integration | Existing-index upgrades, cross-module compatibility, combined regression checks | [Integration](05-integration.md) |

New metrics and unrelated improvements remain outside this repair pass. Refactoring is appropriate where it directly prevents the reported bugs.

## Shared workspace rules

The repository already contains substantial uncommitted and untracked work. Preserve it. Work directly in the current checkout; do not create a worktree from an older commit or reset any files. No commits, releases, or production data mutations are requested.

Another user-owned chat, "Add token burn rate metric", is active in this checkout. Its work includes account_monitor.py, burn_rates.py, local_token_burn.py, service.py, account-types.ts, burn-rate.ts, accounts.css, and views/accounts.ts. Read its compact status when overlapping work becomes necessary, do independent work while it runs, and wait for it to finish before editing those overlapping modules. Do not message or steer that unrelated chat. The integration owner must preserve and test its final changes.

Implementation owners must not edit another active owner's files. Add separate regression test files instead of concurrently modifying shared conftest.py or broad existing test files. The integration owner may reconcile cross-cutting changes after all implementation owners finish. Reread current files before applying patches.

Use unique .local-data test directories. The prior baseline was 185 passing Python tests plus TypeScript, production frontend builds, calendar checks, browser navigation, summary-image, token KPI, and offline-report checks. The burn-rate work may add tests, so do not use the old count as a completion condition.

## Completion contract

Each implementation owner must reproduce its bugs, implement the fix, run focused tests, inspect its diff, and write one JSON result under docs/bugfix-plans/status using the filename in its plan. Include bug IDs, outcome, changed files, test commands and results, unresolved issues, and required integration work. Add a concise final response. A result file is evidence, not a substitute for verification.

The integration owner starts useful preparation immediately, then waits for all four implementation chats to finish. It runs the combined checks only after the code has settled, verifies the six regressions, handles upgrade/backfill behavior, and fixes integration regressions. It records a final acceptance report under docs/bugfix-plans/status/integration.md.

## Acceptance

1. File order and shorter copied prefixes cannot reduce accepted usage or conceal divergent copies.
2. Coincidentally equal post-spawn token counters remain counted; genuine inherited history still deduplicates.
3. Account totals never claim complete distinct-account coverage when identity is unresolved.
4. Empty, invalid, or reversed saved dates cannot trap startup; only valid applied filters persist.
5. HTML exports use the filters represented by the displayed dashboard, even with drafts or in-flight requests.
6. One malformed file cannot stop subsequent healthy files from indexing or bypass failure diagnostics.
7. Previously affected indexes receive the correction through a safe upgrade or refresh path, including imported facts where possible; original logs and snapshots remain untouched.
8. Existing desktop, widget, local burn-rate, import/export, account, and summary-image behavior remains covered.

