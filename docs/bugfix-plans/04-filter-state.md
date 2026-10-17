# Repair persisted filters and HTML export consistency

Own B4 and B5. Read README.md in this directory first.

## Owned files

frontend/src/main.ts, a new focused filter-state module, frontend/src/live-updates.ts only if needed, a dedicated new browser regression script such as scripts/qa_filter_state.mjs, and focused tests for that module. Avoid account modules, token-kpi.ts, service.py, report.py, shared frontend types, and existing QA scripts during parallel work. Do not build frontend/dist concurrently with another chat; the integration chat owns final builds after implementations finish.

## Reproduce

B4: on a fresh origin, select Custom dates and reload before Apply. The displayed inputs receive defaults, but storage already contains range custom with empty start/end. Reload fails with Invalid isoformat string and Try again loops. Applying reversed dates likewise persists rejected values and breaks reload.

B5: apply a one-day custom range, switch to All time, then select Custom dates again without Apply. Displayed results remain all-time, but HTML export sends the earlier custom draft. Review demo values were 1469955411 displayed tokens versus 30415062 for the exported date.

An earlier headless Edge reproduction is .local-data/review-frontend/repro.mjs; treat it as supporting data rather than required implementation.

## Implementation steps

1. Add regression tests reproducing startup failure, invalid saved JSON/shape, empty or reversed dates, and the unapplied-range export discrepancy.
2. Introduce a focused controller/helper that separates draft inputs, pending requested filters, and last successfully applied response filters. Validate restored preferences at startup and recover to safe defaults with a usable explanation/reset path.
3. Persist only validated, successfully applied filters. Invalid or failed requests must leave the last usable state recoverable. Preserve the existing ability to edit dates without automatic refresh overwriting drafts.
4. Export an immutable snapshot of the displayed response filters. Guard any in-flight filter requests so exports cannot silently use a new draft or a stale request completion.
5. Preserve source/model/project filters, merged project IDs, summary image applied-filter behavior, navigation, and automatic reloads.
6. Verify race cases: two filter requests returning out of order, exporting during a pending load, and editing date drafts while background updates occur.
7. Run TypeScript and new focused tests. Coordinate a single isolated build if browser regression verification needs fresh assets; do not change screenshots or user data. The integration owner will run the complete browser suite.

## Acceptance and handoff

The app always reopens with valid filters, rejected dates do not poison storage, and exported HTML represents displayed results. Write docs/bugfix-plans/status/filters.json with B4/B5 outcomes, changed files, tests, and any backend export-contract requirement.

