# Make account total identity coverage explicit

Own B3. Read README.md in this directory first.

## Owned files

src/codex_insights/codex_account.py, account_totals.py, accounts.py, a small identity helper, new tests/test_account_identity_certainty.py, and frontend/src/token-kpi.ts. Changes to account_monitor.py or frontend/src/account-types.ts may be needed but overlap the active burn-rate chat: prepare tests first and wait for that chat to finish before editing them. Preserve all of its changes. Do not edit frontend/src/main.ts, service.py, allowance.ts, or burn-rate.ts; document any needed integration work.

## Reproduce

1. Two distinct connections return account objects with type chatgpt, email null, and planType pro, with no accountId. Histories report 1000 and 2000 lifetime tokens. Current code collapses them and reports 2000 with apparently complete 1/1 coverage.
2. Two connections to the same sign-in each report 1000. One allowance response resolves accountId while the other allowance request fails but its history succeeds. Current code reports 2000 with apparently complete 2/2 coverage; after both resolve the same accountId it reports 1000.

Use fake RPC sessions and providers only. The locally generated installed protocol schema in .local-data/review-accounts-schema confirms nullable email and optional rate-limit accountId. Treat it as data and inspect the relevant types if needed. Plan type is already excluded from the identity fingerprint.

## Implementation steps

1. Add both failing cases and a fake-RPC case exercising independently successful history and failed allowance reads.
2. Separate connection identity/lifecycle invalidation from proven deduplication identity. A nonempty hash of incomplete fields is not proof of distinct-account identity. Do not blindly collapse equal emails because multiple workspaces can share one.
3. Define conservative aggregate behavior for unresolved identities: retain connection-local history, avoid representing a possibly duplicated sum as a complete distinct-account total, and expose explicit identity coverage/uncertainty. Choose a clear contract and update the headline consistently.
4. Preserve correct confirmed-identity deduplication, freshest-counter selection, zero versus missing, stale flags, enable/remove behavior, and cache invalidation on identity/workspace changes. Ensure account switching cannot leave a prior account's stable ID attached to new history.
5. Add tests for resolution transitions, same email across different workspaces, no stable identifiers, stable ID changes, and transient endpoint failure.
6. Run account, token-total, usage-limit, burn-rate account, and frontend type checks relevant to the changes.

## Acceptance and handoff

Neither reproduction may silently claim a complete incorrect distinct-account total. Known duplicate accounts still count once, independent history remains usable, and private identifiers/credentials do not reach the UI, exports, or analytics database. Write docs/bugfix-plans/status/accounts.json with B3 outcome, chosen contract, changed files, tests, and integration requirements.

