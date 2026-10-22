"""Remove one-time upgrade backups once their upgrade has finished and aged."""
import json
import logging
import time

log = logging.getLogger(__name__)

RETENTION_SECONDS = 14 * 24 * 3600
# A copy still being written is never older than this; an older one was interrupted.
TEMPORARY_SECONDS = 24 * 3600


def copy_review_finished(db):
    from .copy_migration import VERSION
    row = db.execute("SELECT value FROM settings WHERE key='copy_history_version'").fetchone()
    return bool(row) and json.loads(row[0]) == VERSION


def claude_recovery_finished(db):
    from .claude_recovery_store import VERSION
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='claude_recovery_sources'").fetchone():
        return True
    # Unresolved ('pending') or interrupted ('staging') recovery may still need its backup.
    return not db.execute("SELECT 1 FROM claude_recovery_sources WHERE state!='complete' OR version!=?",
                          (VERSION,)).fetchone()


BACKUPS = (('insights.before-copy-review.sqlite3', copy_review_finished),
           ('insights.before-claude-identity-v1.sqlite3', claude_recovery_finished))


def prune_upgrade_backups(store, now=None):
    """Delete finished upgrades' backups after 14 days; return the removed names."""
    now = time.time() if now is None else now
    with store.connect() as db:
        finished = {name: check(db) for name, check in BACKUPS}
    removed = []
    for name, _ in BACKUPS:
        backup = store.directory / name
        for path, age, allowed in ((backup.with_suffix('.tmp'), TEMPORARY_SECONDS, True),
                                   (backup, RETENTION_SECONDS, finished[name])):
            try:
                stat = path.stat()
                if not allowed or now - stat.st_mtime < age:
                    continue
                path.unlink()
            except OSError:
                continue
            removed.append(path.name)
            log.info("Removed upgrade backup %s (%.1f GB, %d days old)", path.name, stat.st_size / 1e9,
                     (now - stat.st_mtime) // 86400)
            if path == backup and name == 'insights.before-claude-identity-v1.sqlite3':
                # A later recovery must create and verify a new backup first.
                store._claude_identity_backup_verified = False
    return removed
