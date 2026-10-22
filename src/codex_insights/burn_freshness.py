"""Pending age and verified window evidence, independent of token accounting."""
from .codec import unpack

WATCHER_OVERDUE = 10
FALLBACK_OVERDUE = 35


def relevant_history(db, segment, cutoff, expirations=None, window=300):
    """Only complete timestamp evidence can retire a historical uncertainty."""
    if db.execute('SELECT 1 FROM history_pending WHERE segment_id=?', (segment,)).fetchone():
        return True
    values = [unpack(r[0]) for r in db.execute('SELECT fact FROM history_variants WHERE segment_id=?', (segment,))]
    if not values:
        values = [unpack(r[0]) for r in db.execute('SELECT fact FROM canonical WHERE segment_id=?', (segment,))]
    session = db.execute('SELECT session_id FROM session_metadata WHERE segment_id=?', (segment,)).fetchone()
    groups = ['copy:' + segment] + (['overlap:' + session[0]] if session else [])
    for group in groups:
        for row in db.execute("SELECT selection FROM history_choices WHERE group_id=? AND (scope='' OR scope IN (SELECT id FROM sources WHERE enabled=1))", (group,)):
            values.extend(unpack(row[0]).get('reviewed', []))
    if not values:
        return True
    for fact in values:
        # A retained physical/normalized proof establishes which records this
        # evidence bounds. Timestamp-free or absent traces stay uncertain.
        if fact.get('parse_errors') or not (fact.get('record_hash') or fact.get('proofs')):
            return True
        events = fact.get('raw_token_trace', [])
        if not events:
            return True
        timestamps = [event.get('timestamp') for event in events]
        if any(at is None or not hasattr(at, 'timestamp') for at in timestamps):
            return True
        latest = max(at.timestamp() for at in timestamps)
        if latest > cutoff:
            if expirations is not None:
                expirations.append(latest + window + 1)
            return True
    return False


def pending_age(db, source, paths, at, live):
    oldest, progress, deadlines = [], [], []
    row = db.execute('SELECT last_progress_at FROM source_progress WHERE source_id=?', (source,)).fetchone()
    if row and row[0] is not None:
        progress.append(row[0])
    for path in paths:
        row = db.execute('SELECT oldest_pending_at,last_progress_at FROM pending_progress WHERE source_id=? AND path=?', (source, path)).fetchone()
        if row and row[0] is not None:
            oldest.append(row[0])
            origin = db.execute('SELECT origin FROM pending_origins WHERE source_id=? AND path=?', (source, path)).fetchone()
            deadlines.append((row[0] + (WATCHER_OVERDUE if origin and origin[0] == 'watcher' else FALLBACK_OVERDUE),
                              WATCHER_OVERDUE if origin and origin[0] == 'watcher' else FALLBACK_OVERDUE))
            if row[1] is not None:
                progress.append(row[1])
    return (max(0, at - min(oldest)) if oldest else None,
            min(oldest) if oldest else None, max(progress) if progress else None,
            min(deadlines)[1] if deadlines else FALLBACK_OVERDUE,
            min(deadlines)[0] if deadlines else None)
