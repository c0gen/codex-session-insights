# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Codex Session Insights: a local-only usage dashboard for Codex (plus Claude Code and Antigravity) session logs. A Python engine indexes JSONL session logs into SQLite; a TypeScript/Vite UI renders it inside a pywebview window (Windows dashboard), a loopback HTTP server (`serve`), or a self-contained offline HTML report. An Intel Mac "exporter" build only indexes and exports `.codex-insights` snapshots for import on Windows. `README.md` documents user-visible behavior in detail; `docs/spec.md` is the architecture reference; `docs/metrics.md` defines metric formulas.

## Commands

Windows dev environment (use `.venv/bin/python` on macOS/Linux). Python 3.11+, Node 22+.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
cd frontend; npm ci; npm run build; cd ..       # build is required before gui/serve/report
.venv\Scripts\python -m codex_insights --demo gui    # synthetic data, isolated under <data-dir>/demo
```

- Full local check (pytest + Node data checks + typecheck + frontend build): `scripts/check.ps1`
- Python tests: `.venv\Scripts\python -m pytest -q` (pytest config in `pyproject.toml` puts `src` on the path)
- Single test: `.venv\Scripts\python -m pytest tests/test_engine.py::test_name -q`. `check.ps1` passes `--basetemp` under `.local-data\`; keep test/scratch output there.
- Frontend typecheck only: `npm run typecheck` in `frontend/`. `npm run build` = `tsc --noEmit` + dashboard build + separate widget build (`vite.widget.config.ts` → `frontend/dist/widget`).
- Node data checks (no browser; bundle TS on the fly with esbuild from `frontend/node_modules`), run from the repo root: `node scripts/qa_dashboard_data.mjs`, `qa_filter_state_unit`, `qa_token_activity_data`, `qa_metric_interface_data`, `qa_account_identity`, `qa_widget_data`.
- Browser QA scripts (`scripts/qa_*.mjs`, Playwright) take a demo server URL as the first argument. Start one with `.venv\Scripts\python -m codex_insights --demo --data-dir .local-data\<dir> serve` (prints the URL). Some instead use `scripts/ui-test-server.mjs`, which serves `frontend/dist` and intercepts all API calls. Set `PLAYWRIGHT_CHANNEL=msedge` to use installed Edge.
- Native Windows smoke (startup, tray, widget, clipboard) against a fresh demo index: `scripts/check_desktop.ps1` (`-App <exe>` for a packaged build, `-WidgetOnly`, `-LiveAllowance` reads real account limits).
- Windows release build: `scripts/build_windows.ps1` (runs `check.ps1`, PyInstaller `packaging/windows.spec` + `packaging/bridge.spec`, zips to `release/`). Mac: `python setup_mac.py py2app` on an Intel Mac with x86_64 Python.org Python. There is no CI or release workflow; releases are uploaded manually after testing the extracted archive.
- CLI: global options (`--demo`, `--data-dir`) go **before** the subcommand: `codex-insights --data-dir X scan|export|import|report|catalog|serve|gui|exporter`.

## Architecture

**Data pipeline** (each stage has a version setting that triggers an automatic upgrade when bumped):

1. `ingestion.refresh` walks enabled sources and reads only appended complete lines, checkpointing offset/mtime/size plus a SHA-256 suffix anchor per file (`files` table). `providers.adapter(provider)` picks the parser: `parser.SessionParser` for Codex, `providers/transcripts.py` for Claude Code/Antigravity JSONL, `providers/legacy/` for original Antigravity binary archives. Bumping `parser.PARSER_VERSION` forces a one-time reparse of local files. Per-file failures are isolated and recorded (`index_failures.py`) without stopping the scan.
2. Parsers emit compact **facts** (codec `pack`/`unpack`, never pickle) into `candidates`, one row per source copy. `Store.choose_canonical` selects one `canonical` row per segment using byte-prefix fingerprints, so copied histories count once.
3. `projection.project_segments` turns canonical facts into timestamped `records` (tokens, cost via `accounting/pricing.py`, edits via `accounting/change_accounting.py`, parent/child replay reconciliation via `accounting/token_reconciliation.py`) and hourly `metric_buckets` (`buckets.py`). Bumping `projection.PROJECTION_VERSION` rebuilds records/buckets from stored facts (including imported and offline sources) without touching logs.
4. `queries.dashboard` and friends (`summary_queries`, `usage_metrics`, `widget_queries`, `indexed_tokens`) read one SQLite snapshot and apply date/project/model/source/provider filters in the selected IANA timezone.

Project grouping is metadata layered on top (`project_groups.py`: memberships, aliases, merge/undo); merges never rewrite records.

**Engine and API surface.** `service.Engine` owns the `Store`, the single job worker (`jobs.py`: one DB-mutating worker, user work prioritized over coalesced automatic scans, watchdog + 30 s fallback), accounts, and provider setup. `Engine.call(action, args)` is the one action dispatcher for everything the UI does. The frontend's `api.ts` `call()` routes to `window.pywebview.api.call` (native), `POST /api/<action>` with the per-launch `X-Insights-Token` (`server.py`, loopback-only, token injected into `index.html`), or returns the embedded `window.__INSIGHTS_REPORT__` (offline report). New UI features normally mean a new `Engine.call` action plus a `call("...")` in TS. Mutations go through `engine.submit(...)` so they serialize on the job worker.

**Live account data** runs on its own threads and never waits on the indexing queue: `accounts.py`/`account_monitor.py`/`account_polling.py` drive a hidden Codex app-server over stdio (`codex_account.py`, `account_rpc.py`). Account caches are memory-only and must stay out of SQLite, reports and snapshots. Demo and exporter modes must never start account providers or login.

**Desktop (Windows).** `desktop.py` runs the pywebview window; `desktop_controller.py` holds tray/widget lifecycle policy, with WinForms adapters in `windows_desktop.py` and `windows_widget.py`. The floating widget is a separate frontend entry (`frontend/widget/index.html` → `widget.ts`). `*_verification.py` modules implement the native smoke checks triggered by `--smoke-result` and `CODEX_INSIGHTS_*_SMOKE*` env vars. `launcher.py` is the entry point and logs startup failures before importing native deps.

**Provider bridge.** `providers/bridge.py` (packaged as `CodexInsightsBridge.exe`) is a headless stdin-only process that Claude Code status lines and Antigravity hooks invoke; `providers/setup.py` installs/restores those config entries with preview and ownership checks.

**Frontend.** Vanilla TypeScript, no framework; Chart.js for charts. `main.ts` owns layout, filter bar, loading and binding; `views/*.ts` render pages; feature modules are split into `*-data.ts` (pure logic, tested by Node data checks) and render/UI files. Live updates must preserve open dialogs, unsaved form fields, focus and scroll (`live-updates.ts`).

## Constraints to keep

- **Privacy:** raw transcript text, prompts, commands, patch contents, credentials and absolute paths are never stored in facts, exported in snapshots, or shown in reports/images. `transfers.py` validates imports against a field allowlist (`FACT_KEYS`) and `FORMAT_VERSION`; new fact fields must be added there deliberately. Original session files are read-only.
- **Offline report:** `report.export_html` inlines the built dashboard JS/CSS into one HTML file, so the dashboard bundle must not use dynamic `import()` or shared chunks (this is why the widget has a separate Vite config). Features that need the backend must degrade when `window.__INSIGHTS_REPORT__` is set.
- **Browser targets:** `chrome100` / `safari15`, because the Mac exporter runs on macOS 12 WebKit.
- **Honest coverage:** missing, zero, partial and stale values are distinct states throughout (nullable fields, explicit coverage). Never substitute zero for unavailable or infer tokens/costs that weren't recorded.
- **Version** lives in `pyproject.toml`, `src/codex_insights/__init__.py` and `frontend/package.json`; keep them in sync. User-facing changes go in the `Unreleased` section of `docs/release-notes.md`, and behavior changes are usually documented in `README.md`/`docs/spec.md` too.
- The working tree often carries large uncommitted work from parallel sessions (see `docs/bugfix-plans/`, `docs/metric-plans/`). Don't reset, stash or check out files to clean it up; reread files before editing.
