# Cache reasoning and daily session metrics

Implement estimated cache discount, cache reuse rate, reasoning share, and daily counts of chats and agents in the current Codex Session Insights app. Use the existing analyzed local and imported session facts, reconciliation, applied filters, and display timezone.

The backend and interface owners work in parallel on separate files. The integration owner verifies the complete feature after both finish. All three chats use GPT-6 Astra with Medium reasoning.

Paths in these plans are relative to the repository root unless stated otherwise. Keep live chat/project identifiers and machine-specific paths in ignored `.local-data/planning/` records, not in committed planning documents.

The prior bug-fix integration chat has completed. Its acceptance report is docs/bugfix-plans/status/integration.md. Preserve those fixes, versioned projection upgrades, filter-state behavior, and the newer local token burn feature. The working tree contains substantial uncommitted work; do not reset, stash, checkout old versions, commit, publish, release, or modify the user's live index, original logs, or account credentials.

## Metric definitions

| Metric | Definition |
| --- | --- |
| Cache reuse rate | 100 times summed cached input tokens divided by summed input tokens. Input includes cache reads/writes as subsets; the numerator is cached reads only. Calculate from aggregate counts, not an average of response percentages. |
| Reasoning share | 100 times summed reasoning tokens divided by summed output tokens. Reasoning is already included in output and must not be added again. |
| Estimated cache discount | For each reconciled priced response, cached read tokens times the difference between selected uncached-input and cached-input prices per million, divided by one million. Use exactly the model/date/service-tier/context-threshold/assumed-Fast rates selected by existing cost accounting. Hold input volume, output, and cache-write charges unchanged. Sum without per-response rounding. This is an API-equivalent estimate compared with charging those reads at uncached rates, not subscription savings. |
| Chats per day | Distinct top-level session IDs with observed activity matching the applied filters on each calendar day in the display timezone. A chat active on several days counts once on each day; daily counts are not new-chat counts and do not sum to the all-range distinct total. |
| Agents per day | Distinct spawned sub-agent session IDs and distinct system-agent session IDs, shown separately using the existing canonical categories. Multiple nesting levels remain spawned sub-agents; do not count a parent again as its child. |

Zero input or output makes its respective ratio unavailable. If a subset exceeds its denominator, keep raw counters intact and show the ratio unavailable instead of manufacturing a plausible percentage. For positive denominators, zero numerator is a real 0 percent.

No cached input means zero cache discount and no applicable cached-token pricing coverage. Cached input with no known applicable price means unavailable discount. Partial pricing produces a partial subtotal and explicit coverage of cached tokens. Missing prices must never appear as fully priced zero savings. Preserve signed price differences for unusual custom catalogs; do not silently turn a surcharge into a discount.

Daily sessions use canonical, deduplicated histories. Repeated events, copied sources, multiple segments of one chat, or bucket rows do not add extra sessions. Inherited pre-spawn/pre-creation history must not make a new child or fork appear active before it exists. Support selected project, model, source, and date filters with the same semantics as current analytics. Do not infer activity solely from positive token usage. All-time counts and daily presence must remain explainable across pagination, source selection, and project merges.

## Shared API contract

Add a separate usage_metrics object so existing summary/widget/image contracts are not overloaded:

- cache_reuse_percent: number or null
- reasoning_share_percent: number or null
- cache_discount_usd: number or null
- cache_discount_priced_tokens: number
- cache_discount_total_tokens: number
- cache_discount_coverage_percent: number or null

Add daily_sessions as a chronological array of objects with day (YYYY-MM-DD), chats, subagents, and system_agents. Counts are nonnegative integers. Sparse backend rows are acceptable; the UI must render intervening inactive dates as zero using the existing inclusive date_bounds and calendar helpers. Show an appropriate empty state when no observed range exists.

Both fields must be read from the same database snapshot, filters, timezone, and revision as the rest of the dashboard. Keep API response names stable between owners. Interface types may make the new fields optional for older fixtures/responses, with graceful fallback. Neither field exposes session identifiers, transcript text, credentials, or paths.

## Ownership

| Owner | Work | Plan |
| --- | --- | --- |
| Backend | Pricing calculation, indexed fields/migrations, aggregate ratios, daily session queries, backend tests | [Backend](01-backend.md) |
| Interface | Metric cards, daily chart and accessible values, types, browser tests | [Interface](02-interface.md) |
| Integration | Independent formula/query checks, upgrades, combined regression checks, docs, final acceptance | [Integration](03-integration.md) |

Backend owns Python source and dedicated Python tests. Interface owns frontend source and new frontend QA scripts. Neither owner edits shared app documentation, the other owner's files, or existing broad test scripts while parallel work is active. Integration makes any needed cross-module repairs only after both finish.

Each implementation owner writes its result JSON under docs/metric-plans/status with changed files, exact checks, outcomes, and handoff requirements. Use unique .local-data scratch/test directories and synthetic data. The integration owner reads those results and compact chat statuses, waits until both are finished, then validates the complete feature and writes docs/metric-plans/status/integration.md. Do not message unrelated chats or create further chats.

## Display and verification

Place the three cache/reasoning metrics in Usage & Cost near token composition. Add a dedicated Chats and agents per day panel in that view with distinct main-chat, spawned-sub-agent, and system-agent series, clear legend, integer count axis, exact tooltip values, and an accessible alternative. Use existing visual styles and chart lifecycle conventions, with small reusable modules rather than enlarging main.ts substantially. All metrics must work in standalone HTML reports without network requests.

Verify formulas, empty/zero/partial states, date and tier pricing, copied/replayed history, duplicate segments, timezone and DST boundaries, applied filters, repeated refreshes, existing-index migration, and offline reports. Preserve current summary images, widget behavior, account totals, and local token burn. The final owner must run the complete Python suite, production frontend builds, and relevant browser checks. Completion means the four requested metric groups are implemented and verified, not merely designed.

