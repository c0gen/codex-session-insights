# Display cache reasoning and daily session metrics

Read README.md in this directory for definitions and the fixed API contract. Implement the interface in parallel with the backend owner using synthetic contract fixtures until its API is ready.

## Scope

Own frontend/src/types.ts, views/usage.ts, new focused metric/daily-chart modules and styles, minimal main.ts/chart lifecycle wiring, and dedicated new QA scripts. Do not edit Python source, app documentation, existing large QA scripts, or the backend owner's tests. Preserve the recently added filter-state controller and account identity/local burn-rate UI.

## Plan

1. Add the shared optional usage_metrics and daily_sessions types without weakening existing types. Gracefully handle a response that predates the new fields. Consume the backend values rather than recomputing cache pricing in the browser.
2. Add three compact metric cards in Usage & Cost near token composition: Estimated cache discount, Cache reuse rate, and Reasoning share. Tooltips must explain the denominators and API-equivalent counterfactual. Cached reads and reasoning are subsets; no additional tokens are implied.
3. Render real zero, unavailable, and partial pricing distinctly. Show cached-token pricing coverage with a partial discount. Use sensible monetary precision so a small nonzero discount is not presented as an unexplained zero; expose exact values through the existing formatting/tooltip pattern. A signed negative catalog difference must not be advertised as money saved.
4. Add a Chats and agents per day chart in Usage & Cost using distinct main-chat, spawned-sub-agent, and system-agent series. Grouped or stacked bars are appropriate; use a clear legend, integer axis, exact per-series tooltip values, date and display-timezone context, and accessible count information. Label counts as unique active sessions per day.
5. Fill inactive calendar dates from the applied response bounds with existing calendar helpers. Do not shift dates through browser-local UTC conversion. Avoid unbounded chart work for long ranges and keep narrow layouts readable.
6. Keep draft filters separate from applied data. Navigation and automatic reloads must clean up charts/listeners and preserve existing form drafts. Reuse the app's chart lifecycle or encapsulate the new chart's mount/unmount behavior.
7. Add isolated browser/UI fixtures covering all metric states, series/count labels, filters, empty dates, keyboard/accessibility behavior, narrow layout, repeat navigation/live updates, and standalone reports. Include examples with both agent categories even if default demo data lacks them.
8. Run TypeScript and focused data tests first. You own the frontend build during parallel implementation; the integration owner will wait and run the final production build. If backend is unfinished, validate synthetic UI routes and explain that live integration remains pending.

## Acceptance

All four metric groups are visible and understandable in Usage & Cost and saved HTML reports. Offline reports make no network calls. Existing overview charts, summary images, widget, filters, account totals, and local burn remain intact. Write docs/metric-plans/status/interface.json with changed files, checks, screenshots if useful, and any remaining integration needs. Complete your implementation and focused checks rather than waiting idle for backend work.

