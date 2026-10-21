# Unreleased — concurrent accounts, faster grouping and live allowance

## Token Worlds

- Show literal novel collections with 150 books/bookcase, expanding aisles, floor-plan navigation and fractional final books. Give Floppy Vault fixed 100-disk cases and 20-case racks with inspectable contents.
- Keep paper-height callouts clear of the stack, add orthographic landmark comparisons and improve camera fitting. Add selectable unrolled/globe trail views, route close-ups, and continuous/30-minute/one-hour daily reading schedules. Preserve those views and qualifications in offline reports and PNG captures.
- Add a Visualizations gallery and Overview's Explore in 3D link, with Paper Tower, Infinite Library, Paper Trail, Reading Journey and Floppy Vault. Share the existing token accounting and disclose approximations, repeated context, grouped objects and enlarged paper width.
- Add measured GLB props authored in AI Design, orbit/keyboard/camera controls, imperial/metric units, true paper proportions, PNG copy/save and graphics-failure fallbacks. Preserve camera/focus through live updates and release graphics resources when leaving the gallery.
- Embed every scene and model in standalone HTML reports while retaining analyzed-snapshot semantics and excluding live account totals. Keep the widget build independent. See [implementation and validation](token-worlds.md).

## 0.1.6 — Claude agent identity recovery

- Identify Claude agents from session/agent metadata and validated flat, nested and workflow transcript layouts. Agent identities include the owning session, preventing unrelated agents with matching filenames from colliding.
- Automatically back up and recover existing Claude indexes through resumable staging. Preserve rejected checkpoints, retained alternatives and valid review choices; archive choices that incorrectly selected between separate agents. Uncertain evidence remains pending.
- Add read-only `diagnose-history`, a persisted recovery report, and parent/agent classification with deduplicated alternative-only token counts in Review conflicts. Recorded counters across versions are not additive.
- Keep transfer v6 and v1–v6 imports. Recover on the Mac with its existing index and export again using the same exporter identity; v5 snapshots cannot supply alternatives they omitted.
- Native Intel Mac packaging and the user's original Mac conflict audit must be completed on the Mac. Windows validation cannot establish the amount recoverable there.

## 0.1.5 — Reviewable history conflicts

- Recognize formatting/key-order-only JSON copies through ordered normalized record proofs; retain original physical boundaries for replay accounting. Verified extensions replace shorter histories without adding cumulative counters together.
- Retain divergent sanitized versions and add **Review conflicts** to Mac and Windows Sources. Keep accepted, choose another version, or undo; choices persist and new incompatible activity reopens review. Separate copy disagreements, accounting overlaps, parsing errors and unavailable evidence.
- Transfer v6 carries accepted histories, alternatives and local review decisions. Imports v1–v5 remain supported. Update Windows before importing new Mac snapshots; re-export on the Mac to recover alternatives omitted by older exports.
- Back up existing SQLite indexes before migration and recover rejected alternatives from parser checkpoints. Reparse accessible sources once and preserve unavailable evidence for later verification. Original logs remain unchanged.
- Native Intel Mac packaging validation must run on an Intel Mac before publishing its build.

## Earlier unreleased work

- Prepare version 0.1.4 with Intel Mac exporter bridge packaging, a dedicated bundled headless helper, and safe Update of previously owned commands. Missing helpers affect bridge setup only.
- Discover standard and `CLAUDE_CONFIG_DIR` Claude histories, preserve disabled/forgotten sources, and isolate bridge ownership and restored status-line commands by profile.
- Refresh sessions before desktop/CLI usage exports. Save retained history with persistent warnings when sources cannot be refreshed; cancellation before publication and failed writes preserve an existing snapshot. Completion results include refresh counts and warnings.
- Keep the new Claude pricing engine and transfer v5 metadata shared by exporter and dashboard. Update Windows before importing new Mac snapshots; v1–v4 imports remain supported. Add Intel build automation, exporter-aware native smoke, packaged cost round-trips and release checksums; Apple Silicon builds remain deferred. Native Intel validation is still required before publishing a Mac release.

- Price recorded Claude Opus 5.5 and Sonnet 5.5 history using verified launch-date API rates, including cache reads and both cache-write durations. Backfill logged speed/tier/geography and automatically reprice indexed history. Transfer v5 preserves these optional enums while retaining v1–v4 imports; unknown models and incomplete pricing stay unpriced.
- Show retirement guidance once on retained Antigravity source cards, including saved reports. Restore legacy UI verification without invoking retired archive collection, and align summary-image and token-activity QA with provider labels and unavailable counters.
- Trim surrounding whitespace from valid timezone names when saving Settings, matching the validation shown in the dialog.
- Replace the full allowance and plan-limit cards above Overview with one compact limits row: a chip per enabled provider showing its tightest window, reset countdown and Stale badge, plus local token and dollar burn. Chips open Accounts, which keeps the full cards, bucket selectors and refresh. Usage, Projects and Sources no longer repeat these cards, so usage KPIs are visible without scrolling.
- Usage & Cost shows tokens and cost beside the cache and reasoning cards instead of repeating Overview's line-change and chat cards. Card text is shorter, exact counts move to the help tooltips, and an unavailable ratio states why.
- Format the metric coverage note in plain words with thousands separators, and use a quiet style when at least 99% of responses are covered.
- Filters stay on one row at common window sizes, show **Reset filters** when any filter is set, and the page subtitle names the applied project, tool, model, source and range. The date caption is labeled as the active span.
- Projects use compact rows that fit a 1250-pixel window without sideways scrolling, a single partial-coverage marker, and a clearly disabled **Merge selected** until something is selected.
- Sources show human-readable bridge states with only the relevant Install/Update/Disable/Uninstall actions, aligned rows, short dates in the display timezone, and a collapsible **About snapshots** card. Fix a duplicated bridge sentence, and saved reports no longer label real sources "Synthetic demo source".
- Settings are grouped into General, Pricing, Live account data and Widget & tray, with Cancel, timezone suggestions and validation for unrecognized timezone names.
- Use the same window names (5-hour, Weekly), reset countdowns and whole-number, rounded-down percentages across the dashboard and widget. Antigravity bridge meters such as `gemini-5h` read as "5-hour · Gemini". Allowance burn shows `%/hr`.
- The widget labels lines as **Lines**, shows 0 and $0.00 instead of "—" when nothing has been recorded today, and makes its failure dot focusable with a tooltip.
- Smaller fixes: Accounts uses a person icon; the sidebar lists a "+N more" link for hidden sources and uses the same status words as source cards; the collapsed sidebar keeps a Settings gear; line-change counts stay side by side; the paper-stack equivalent uses feet or at most three significant digits; "No current streak" replaces "0-day current streak"; agent and service-tier names are human-readable; and the toggle styles match.

- Restore Antigravity public transcript accounting for native step records, recorded cache reads, nullable components and repeated/rewritten log reconciliation.
- Add optional official Antigravity CLI quota checks, shared dashboard/widget freshness and manual refresh. Repair Windows hook quoting and preserve configuration ownership during upgrades.
- Retire encrypted Antigravity archive/key collection while retaining indexed facts and v1-v3 imports. New portable snapshots use v4 for nullable public usage components.

- Resize the widget vertically with remembered height and a scrolling body beneath its toolbar. Add Automatic/Custom height settings and Fit to content; preserve custom height when toggling details or refreshing data.
- Compact account headers, place Updated beside reset countdowns in the selected timezone, and add allowance warning colors with Low/Critical/Exhausted labels, per-account refresh, Refresh all and Open in Accounts shortcuts.
- Show Claude's 5-hour and weekly plan limits with % remaining and exact reset dates/times in the dashboard and widget. Stale readings stay visible with their age instead of disappearing; a passed reset shows Awaiting reading rather than an old percentage. Empty buckets stay hidden, and dashboard setup diagnostics and cached Codex stale states are preserved.
- Add an optional **Check Claude plan limits** setting that runs your installed Claude Code's documented headless `/usage` command every five minutes. Claude Code signs in on its own; the app reads no Claude credentials, makes no model requests, writes no transcript and keeps readings in memory, out of reports and snapshots. Demo and exporter modes never run it.
- Retain fuller session history when a folder contains shorter copies. Divergent copies preserve accepted usage and display a persistent conflict warning; forgetting the source clears its warning.
- Require preserved event timestamps or a verified history boundary before excluding copied child usage. Upgrade cached records and buckets atomically from stored facts on GUI/CLI startup, refresh, or import, including offline and imported facts. Interrupted upgrades retry without advancing their version.
- Open the GUI before running the one-time stored-fact upgrade, showing an Updating usage index banner while cached results remain available. Refresh the displayed totals after completion; headless report/export commands wait for corrected records before returning.
- Reparse older local checkpoints once to recover history lost to shorter copies. Offline and disabled sources retain accepted facts and recover when available/enabled; snapshots missing the longer history need a corrected export. Original logs and snapshots are never rewritten.
- Isolate malformed nested log payloads per file, retain prior accepted facts, and continue healthy files with local failure diagnostics.
- Mark account totals unverified when stable account identities are unresolved, retaining available connection history while warning that the sum may include duplicates.
- Recover invalid saved date filters to All time and save filters only after successful requests. HTML export captures the displayed filters when its dialog opens; drafts and later responses cannot change that selection. Reports still query the current index at export time.
- Dismiss the widget's right-click menu when clicking outside it or switching to another window. Preserve Escape and the existing menu actions.
- Narrow the widget and its first column; shorten the labels to Cost and LoCs. Add a saved Details disclosure with keyboard and reduced-motion support, preserving the native bottom edge in automatic sizing mode.
- Show summed Codex API lifetime tokens as the dashboard headline, with filtered analyzed tokens underneath. Deduplicate known account identities and label partial, stale and unavailable totals; widget token counts remain analyzed.
- Copy a polished 1200 × 720 summary image beside Refresh, using the displayed analytics filters and selected calendar range. Include tokens, estimated cost, observed line changes, chats and token activity, with optional project names and a Save PNG fallback. Windows clipboard data remains available after app exit; widget copying is deferred.
- Show total changed lines (additions plus removals) alongside the dashboard's observed line-change breakdown, using the active filters.
- Merge selected project groups with checkboxes, a searchable destination picker and retained-name preview. Single-project Merge remains available.
- Change grouping metadata atomically without rescanning chats or rewriting usage records; recover original identities through a resumable background migration.
- Undo the latest merge across restarts and new chats. Grouping survives imports and rebuilds, with source selection and search preserved through live redraws.
- Show the signed-in Codex account's returned allowance windows above dashboard filters. Fetch every 60 seconds on an independent worker, with bounded timeouts, backoff, manual refresh and honest stale/unavailable states.
- Add an optional allowance section to the 240-pixel widget, with a separate switch and bucket preference. Existing metric selections are preserved.
- Disable live fetching in Settings. Demo/exporter modes make no allowance requests, and allowance data is excluded from reports and transfer snapshots.
- Add Accounts with independent browser sign-ins, editable labels, pause/reconnect/remove controls, and private app-owned credential directories. Current Codex keeps its existing sign-in. Login supports cancellation and a five-minute timeout while other accounts keep refreshing.
- Display account-reported token summaries and daily history with 30-day, 90-day and all-available ranges; preserve missing data, zero usage and original bucket dates. Allowance refreshes every minute and history every five minutes, with separate freshness/error states.
- Show authoritative banked reset counts and exact local expiration dates/countdowns, including partial details and non-expiring resets. Passed timestamps trigger refresh without inventing a new count. Redemption and expiry notifications are not included.
- Select and order compact account rows beneath widget totals. Preserve width and existing totals, grow vertically, and scroll the account list when it reaches the monitor's usable height. All account snapshots are memory-only and excluded from exports.

# v0.1.3 — quiet live updates and usable controls

- Indicate automatic indexing with the refresh icon; show progress strips for user-requested work.
- Queue settings and source changes ahead of automatic scans, with safe scan cancellation and completion feedback.
- Coalesce live events, leave at least five seconds between scans, and measure the fallback from scan completion.
- Preserve open dialogs, unsaved fields, focus, search, custom dates and scroll during live updates.
- Remember unchanged file failures across restarts and retry on file/parser changes or explicit refresh/rebuild. Local indexing diagnostics contain filenames and stack locations, without transcript text.
- Leave unchanged incomplete final records idle until the writer appends more data, avoiding repeated checkpoint processing.

- Keep indexing in the Windows tray when the dashboard closes, enabled by default. Disable this in Settings or use the tray's Quit action to exit.
- Add an optional floating Today/All-time widget, disabled by default, with selectable tokens, API-equivalent cost, observed line changes and main chats.
- Remember widget position and pin state, recover off-screen positions, and restore the existing dashboard when the app is launched again.
- Make the widget a compact metrics-only table with native right-click controls. Fix drag snap-back and scrolling under Windows display/text scaling, abbreviate large cost values, and retain exact amounts in tooltips.
- Keep desktop preferences independent of accounting updates; preserve offline reports and Mac exporter behavior.

# v0.1.2 — recent line-change recovery

- Read structured `FileChange` completion events, restoring counts omitted by the legacy success-message parser.
- Count recorded additions, updates, moves and deletions; preserve failed and unmeasured operations and avoid counting legacy/structured duplicates twice.
- Automatically backfill unchanged local session files after the parser upgrade, with resumable per-file progress and durable projection recovery.
- Prefer freshly parsed facts over stale equal-length copies. Existing imported snapshots require a fresh export from the updated exporter to recover their missing history.
- Keep portable snapshot fields and dashboard interfaces unchanged.

# v0.1.1 — local Windows build

- Build and test Windows packages locally; upload releases manually.
- Record startup diagnostics before importing app dependencies, and show native startup errors with the log location.
- Include `Start.cmd` and `Startup diagnostics.cmd` beside the EXE.
- Load the native dashboard before starting session indexing, and keep its WebView2 profile inside the app's data directory.
- Derive archive, UI and Mac bundle versions from the current package version.
- Show every model-axis label and grow the model chart so its bars and labels stay separated.

The previously reported silent startup failure has not yet been reproduced; a successful local build alone does not establish its cause. This version adds diagnostics to capture a remaining failure.

# v0.1.0

Initial Windows dashboard and Intel Mac exporter.

- Default and additional session folders with incremental indexing and refresh while open.
- Date, project, model and source filters; daily activity, model usage and prompt timing.
- Provider token accounting, historical API-equivalent pricing and conservative observed edits.
- Novel/page/paper-stack/reading equivalents with total processed and output bases.
- Compact snapshots with checksum validation, stable exporter identities and full replacement.
- Self-contained offline HTML reports with anonymous project/source names by default.
- Synthetic demo mode, MIT source and platform build workflows.

Windows needs WebView2/.NET Framework 4.8; the Intel Mac exporter targets macOS 12+. Packages are unsigned, and the Mac bundle is not notarized. Token pricing excludes non-token service charges. Line-change coverage is partial for unsupported writes. Log format changes may require parser updates.
