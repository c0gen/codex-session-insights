# Implement metric calculations and daily session counts

Read README.md in this directory for the binding definitions, API contract, and ownership rules. Implement the backend now using the current working tree.

## Scope

Own Python source changes, a small dedicated metrics module or helper where useful, and new focused tests such as tests/test_usage_metrics.py and tests/test_daily_sessions.py. Likely integration points are accounting/pricing.py, projection.py, storage.py, buckets.py, queries.py, and demo.py. Use the existing historical pricing evaluator; do not duplicate the rate-selection logic or fetch new prices. Leave frontend files and app documentation to their owners.

## Plan

1. Add focused calculation and query fixtures. A synthetic request with 1000000 input tokens, 600000 cached reads, 200000 output, and 50000 reasoning must yield 60 percent reuse and 25 percent reasoning. With selected rates of 2 USD input and 0.20 USD cached input per million, the cache discount is 1.08 USD. These are fixture rates, not a claim about current model pricing.
2. Derive discount from the effective rates already selected for each reconciled response. Preserve date boundaries, logged tiers, assumed Fast blends, long-context request thresholds, and fallback assumptions. Keep cache-write charges unchanged in the comparison. Check that actual priced cost plus discount equals the same-response counterfactual with cached reads charged as ordinary input.
3. Persist enough additive facts at projection time to answer filtered discount and coverage queries efficiently. Do not deserialize all raw session facts on each dashboard poll. Reuse existing indexed records/buckets or a justified sidecar. Compute aggregate ratios from summed original token fields.
4. Extend the schema and versioned projection upgrade safely. Correct both raw records and buckets, recover existing local/imported/offline facts, and preserve atomic rollback and idempotence. Expensive rebuilds must retain the recently fixed deferred GUI startup behavior. Do not advance the version until the correction commits. Ensure startup can display cached data during migration without SQL missing-column failures or invented fully priced zero metrics.
5. Implement daily distinct session counts under the shared contract, deduplicating by actual session ID and category per display-zone day. Preserve activity without token output. Prevent replayed/pre-spawn history from creating phantom child activity. Cover paginated segments and exact copied source deduplication. Use the existing applied date/project/model/source clauses and one SQLite read snapshot.
6. Test ratios with zero/invalid denominators, unknown prices, partial known cached tokens, zero cached tokens, mixed tiers, historical rate changes, assumed rates, long context, cache writes, signed custom rate differences, and no per-response rounding.
7. Test repeated same-day events, two segments of one session, copied sources, parent/child/system categories, agents spanning midnight, inactive days, daylight saving boundaries, project merges, source enable/forget, model filters, and parity between records and bucket query paths.
8. Use synthetic demo/test fixtures to make both agent categories testable; avoid globally changing longstanding demo totals unnecessarily.

## Acceptance

The README API contract must be implemented. Existing projected indexes must acquire accurate metrics after their normal safe upgrade path. Transfers stay compatible and private; reports can consume the public metrics without session IDs. Run focused tests and relevant existing accounting, engine, projection-upgrade, source/transfer, and replay tests. Write docs/metric-plans/status/backend.json with results, changed files, migration details, and any frontend/integration notes. Complete implementation rather than stopping at the plan.

