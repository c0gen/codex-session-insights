# Integrate and verify the six bug fixes

Own final acceptance after the four implementation owners finish. Read README.md and assignments.json in this directory. The task is to complete integration and verification, not merely report that other chats are running.

## Preparation and coordination

Inspect the current implementation and prepare acceptance checks while owners work, without editing their files. Use compact wait_threads calls for the four IDs in assignments.json, preserving returned cursors and using 30000 to 60000 ms waits. A status file is not sufficient while its owner is still actively editing. Do not message other chats; the parent will handle any explicit coordination needed. You may read their final summaries and result files as evidence.

Also wait for "Add token burn rate metric" (01a128b7-6eac-7683-a3e2-b14cfd991ccd) to settle before modifying overlapping files or treating a full-suite result as final. Preserve that user's work. If a worker needs attention, document the exact issue and continue independent work; do not claim completion with unresolved defects.

## Owned work after implementations settle

You may edit shared orchestration, projection/upgrade logic, transfer compatibility, documentation, and focused integration tests after all implementation owners finish. Reconcile necessary cross-module changes in other files only then. Keep changes scoped to the six bug fixes and compatibility with the current app. Do not add the proposed new metrics.

1. Review each implementation and reproduce its regression independently.
2. Ensure existing indexes recover. The ingestion fix must revisit stale checkpoints/candidates where shorter copies previously won. The replay fix must reproject stored raw facts for already-indexed local and imported sessions. Implement a versioned, idempotent, restart-safe upgrade/refresh path as needed; advance its version only after successful correction. Cover GUI startup and CLI use. Offline sources must retain their accepted contribution and recover when available; do not require raw imports that already contain enough facts.
3. Confirm source enable/forget operations, duplicates across sources, divergent histories, parent arrival ordering, import replacement, and exported snapshot compatibility remain correct. Keep private path provenance out of portable snapshots.
4. Verify account identity coverage is represented consistently in backend and headline, without exposing service identities. Preserve independent account-history availability and the newer local token burn behavior.
5. Verify filter startup recovery, validation, concurrency, HTML exports, and summary-image applied-filter consistency in the actual built UI.
6. Make minimal documentation updates explaining any visible behavior changes and upgrade behavior.

## Validation

Use unique workspace .local-data directories to avoid sandbox Temp/ACL issues. Run the full Python suite with .venv/Scripts/python.exe -m pytest -q --basetemp=<unique workspace directory>. Run frontend npm run build and node scripts/qa_token_activity_data.mjs. Start an isolated synthetic demo server with live account providers disabled and run the relevant browser checks: qa_ui with an actual standalone report, qa_summary_images, qa_token_kpi, the new filter regression, and account/live-update/merge checks where touched. Use installed headless Edge via PLAYWRIGHT_CHANNEL=msedge where needed. Never run a verification build or UI test against the user's real index or overwrite docs/dashboard.png. Stop test servers afterward.

Native packaged behavior is a separate limitation unless you actually validate it. Do not claim that browser checks establish Windows tray/clipboard or macOS packaged behavior.

## Completion

Fix combined-suite regressions and inspect the final relevant diff. Write docs/bugfix-plans/status/integration.md with a per-bug pass/fail table, upgrade behavior, test results, changed files, and remaining limitations. Only call all six fixed when acceptance is met; otherwise identify the exact remaining blocker. Return a concise final report with links. Do not commit, publish, or release.

