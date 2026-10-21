"""Refresh local history before writing a portable, fact-only snapshot."""
from .ingestion import refresh
from .transfers import export_snapshot


def check_cancel(cancel):
    if cancel is not None and cancel.is_set():
        raise InterruptedError("Export cancelled")


def export_usage(store, destination, label="This computer", progress=None, cancel=None):
    check_cancel(cancel)
    report = {"files": 0, "changed_files": 0, "bytes_read": 0, "errors": 0, "skipped_errors": 0}

    def refreshing(value):
        if progress:
            progress({**value, "phase": "Refreshing session files before export"})

    refreshing(report)
    if not store.setting("demo", False):
        report = refresh(store, refreshing, cancel)
    check_cancel(cancel)
    if report.get("cancelled"):
        raise InterruptedError("Export cancelled")
    report["offline_sources"] = sum(
        s["enabled"] and s["kind"] in {"folder", "bridge"} and s["status"] == "Offline" and s["segments"] > 0
        for s in store.sources())
    warnings = []
    affected = report["errors"] + report["skipped_errors"]
    if affected:
        warnings.append(f"{affected} file or source refresh failures. Last accepted history was retained where available; some usage may be missing.")
    if report["offline_sources"]:
        warnings.append(f"{report['offline_sources']} offline sources contain retained history. Their latest activity could not be checked.")
    from .claude_recovery_store import status
    with store.connect() as db:
        recovery = status(db)
    if recovery['identity_issues']:
        warnings.append(f"{recovery['identity_issues']} Claude identity observations need verification. Reconnect the original logs and refresh; retained usage may be incomplete.")
    if progress:
        progress({"phase": "Exporting usage facts", "sessions": 0})
    result = export_snapshot(store, destination, label, progress, cancel)
    if result.get('unresolved_histories'):
        warnings.append(f"{result['unresolved_histories']} histories need review or verification. Accepted totals can exclude activity in alternative versions. Open Review conflicts; retained alternatives are included in this snapshot.")
    from .history_overlaps import groups
    with store.connect() as db:
        overlaps = sum(g['state'] == 'needs_review' for g in groups(db, local=True))
    if overlaps:
        warnings.append(f"{overlaps} accounting overlaps need review. One stored format contributes usage until a choice is made.")
    return {**result, "refresh": report, "warnings": warnings, 'claude_recovery': recovery}
