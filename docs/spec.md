# App specification — v0.1

## Scope

A local Windows dashboard and Intel Mac export utility for casual Codex usage analysis. Default Codex directories, extra folders, compact import/export, live refresh while open, and offline HTML reports. Public MIT repository. No server account, transcript browser, model calls, tray service or cloud sync.

## UI

Dark charcoal surfaces, thin panel borders, mint highlights, line icons and a left navigation rail based on the supplied reference image. Native OS window chrome. Overview has global date/project/model/source filters, four headline cards, a switchable daily chart, highlights, and text equivalents. Usage & Cost adds token composition, model bars, prompt timing, agent breakdown and pricing coverage. Projects is a searchable table with filters and explicit group merging. Sources owns local folders, imports, exports and inclusion controls. Settings owns timezone, computer label, assumed Fast share and pricing catalog import.

Dates use the selected IANA timezone. All-time includes indexed history through today; custom ranges include the whole final local day. A filtered export saves exactly the selected dataset. HTML exports contain inline CSS/JS/data and require no server; filtering is frozen to the saved scope, while navigation and chart measure switches remain usable.

## Architecture

- Python parser, accounting modules and SQLite index shared by dashboard and exporter.
- TypeScript/Vite UI with Chart.js; a pywebview window uses Edge WebView2 on Windows or WKWebView on macOS.
- A loopback-only HTTP server serves bundled UI assets and a token-protected API. Native file dialogs run through the desktop bridge. The CLI uses the same engine without a browser.
- One indexing worker prevents concurrent mutations. Watchdog notifications and a periodic fallback find session appends; only complete JSONL lines are consumed. Offset, mtime, size and a suffix anchor support restarts and replacement detection.
- Raw transcript text is read for deterministic extraction, then discarded. SQLite stores compact facts and private checkpoints; timestamped metric records have indexes for date/project/model/source queries.
- Source candidates are deduplicated by session ID plus metadata timestamp. Rolling byte-prefix fingerprints prove that a copy extends another; conflicting copies retain accepted history and show diagnostics. Verified parent trace replay and exact paginated boundaries are reconciled by the accounting core.
- Imports validate version, checksum, field allowlists and counts, then replace one exporter’s candidates in a transaction. A failure rolls back. Disabled-source preferences persist. Sources can be forgotten without editing original logs.

## Snapshot v1

`.codex-insights` is a ZIP containing exactly `manifest.json` and `facts.jsonl`. Manifest: format/version, app version, stable exporter UUID, monotonically increasing revision, label, creation time, fact count, SHA-256 of the decompressed facts, and conversation-content=false.

Each fact holds session/segment IDs, sanitized project identity/label, ancestry and immutable boundary metadata, model/tier/effort context, response token traces, timestamped prompt/assistant signatures, hashed edit files with counts/outcomes, activity timestamps and byte-prefix proofs. Prompts, responses, tool arguments, shell commands, patches, credentials and absolute paths are excluded. Export contains locally observed candidates only, so imported data is not circulated back as new local history. Full snapshots keep transfer logic simple.

## Packaging and validation

Windows portable folder zipped by PyInstaller; the system supplies WebView2/.NET. Intel Mac exporter built with py2app using an x86_64 Python runtime, macOS 12 deployment target. Builds currently have no signing/notarization. Tagged GitHub Actions runs publish release assets and checksums.

Regression tests cover response counter resets/repeats, cached/reasoning subsets, append-only reads, partial lines, duplicates, disconnected roots, forgotten sources, full snapshot replacement, integrity failure, privacy, delayed edit confirmations, unknown prices, exact portable boundaries and late parent history. Browser smoke checks exercise navigation, filters, project search, chart switches, narrow windows and standalone exports. Demo data is synthetic and safe to publish.

## Limits and later options

Log formats can evolve; unsupported records and histories are exposed as coverage diagnostics. Observed edits remain partial for writes outside recognized patches. Cost estimates exclude non-token services. First-time indexing is proportional to raw history size; later refreshes are incremental. Source deletion is conservative: retained cached history requires explicit forgetting. No custom rate editor, automatic update service or delta-transfer protocol in v0.1. Those can be added when actual use justifies them.
