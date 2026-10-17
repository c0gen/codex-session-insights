# Preserve independent child token usage

Own B2. Read README.md in this directory first.

## Owned files

src/codex_insights/accounting/token_reconciliation.py and new tests/test_replay_origin.py. Add a small accounting helper only if useful. Leave parser.py, ingestion.py, projection.py, service.py, and existing shared tests to their owners.

## Reproduce

Create a parent response at second 3 with 110 tokens and a child spawned at second 5 whose first independent response at second 6 has the same full cumulative and last-usage counter tuples. Expected aggregate is 220. Current matching reports 110, marks 110 as verified replay, and reports no unresolved history.

The current prefix matcher checks whether parent events predate spawn, but matching signatures do not prove that the child event was copied.

## Implementation steps

1. Add a regression showing that coincidentally equal post-spawn counter tuples remain counted, including different model context where appropriate.
2. Require actual inheritance evidence before excluding child prefix events. Preserved child event timestamps and verified explicit history boundaries are valid evidence; equal counts alone are insufficient.
3. Preserve existing exact pre-spawn prefix and aligned-prefix replay behavior. Keep startup baseline handling, counter resets, pagination boundaries, missing parents, and late-arriving parents conservative.
4. Test both the positive inherited-history cases and the negative independent-response cases. Avoid solving undercount by simply disabling reconciliation.
5. Verify recalculation from stored portable facts produces corrected totals. Document exactly which existing projection/version/backfill changes the integration owner must add so cached affected totals recover without manual deletion.
6. Run new regression cases and existing accounting/engine tests.

## Acceptance and handoff

The independent parent plus child example totals 220, genuine inherited usage still counts once, and uncertainty is retained when inheritance cannot be established. Write docs/bugfix-plans/status/replay.json with B2 outcome, changed files, tests, and existing-index repair requirements.

