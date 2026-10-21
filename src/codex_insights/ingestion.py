"""Shared synchronous entry point for resumable local indexing."""
import os
import time
from pathlib import Path
from .parser import PARSER_VERSION
from .projection import ensure_projection
from .index_file import anchor
from .index_scan import Scan


def refresh(store, progress=None, cancel=None, rebuild=False, automatic=False):
    ensure_projection(store)
    report = {"files": 0, "changed_files": 0, "bytes_read": 0, "errors": 0, "skipped_errors": 0}
    sources = [s for s in store.sources() if s['kind'] in {'folder', 'bridge'} and s['enabled'] and s['root']]
    local = [s for s in sources if s['provider'] == 'codex']
    hints = getattr(store, 'live_paths', None)
    if hints:
        hints.prune({s['id'] for s in sources})
    local_ids = {s['id'] for s in local}
    if (automatic and not rebuild and hints and not hints.discovery_due()
            and hints.pending() and all(sid in local_ids for sid, _ in hints.pending())):
        Scan(store, local, report, progress, cancel, False, True).run_pending()
        return {**report, 'cancelled': True} if cancel and cancel.is_set() else report
    if hints:
        hints.begin_discovery()
    scan = Scan(store, local, report, progress, cancel, rebuild, automatic)
    for failure in scan.failures.values():
        failure.parser_version = PARSER_VERSION
    scan.run()
    if cancel and cancel.is_set():
        return {**report, 'cancelled': True}
    from .claude_recovery import recover
    live = Scan(store, local, report, cancel=cancel, automatic=True)
    def recovery_progress(value):
        # This phase runs outside the recovery publication transaction.
        if value.get('phase') == 'Recovering Claude history':
            live.hints()
            if time.monotonic() - live.last_inventory >= 30:
                live.inventory()
            deadline = time.monotonic() + .25
            while live.tasks and time.monotonic() < deadline and not live.cancelled():
                live.step()
            live.finalize(deadline)
        if progress:
            progress(value)
    try:
        recovering_sources = recover(store, recovery_progress, cancel, report)
    except InterruptedError:
        return {**report, 'cancelled': True}
    finally:
        live.close()
    remaining = []
    for source in sources:
        if source['provider'] == 'codex':
            continue
        if source['id'] in recovering_sources:
            if not Path(source['root']).is_dir():
                with store.connect() as db:
                    db.execute("UPDATE sources SET status='Offline',detail='Previously indexed history retained; Claude identity verification resumes when reconnected' WHERE id=?", (source['id'],))
            continue
        if source.get('format') == 'antigravity_legacy':
            with store.connect() as db:
                db.execute("UPDATE sources SET status='Collection disabled',detail='Encrypted archive collection is retired. Previously indexed history is retained; use public transcripts and official hooks.' WHERE id=?", (source['id'],))
            continue
        remaining.append(source)
    Scan(store, remaining, report, progress, cancel, rebuild, automatic, live_sources=local).run()
    return {**report, 'cancelled': True} if cancel and cancel.is_set() else report


def register_defaults(store):
    home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")).expanduser()
    for name in ("sessions", "archived_sessions"):
        store.add_source(home / name, "This computer" if name == "sessions" else "Archived sessions")


def register_provider_defaults(store):
    home = Path.home()
    from .providers.profiles import register_claude_profiles
    register_claude_profiles(store)
    for application in ("antigravity", "antigravity-cli", "antigravity-ide"):
        store.add_source(home / ".gemini" / application / "brain", "Antigravity · " + application, "antigravity")
    store.add_source(store.directory / "bridge" / "events", "Antigravity · passive hooks", "antigravity", "bridge")
