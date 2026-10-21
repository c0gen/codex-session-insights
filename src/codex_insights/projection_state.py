"""Durable rebuild intent and configuration belonging to accepted metrics."""
import json

KEY = 'projection_request'
DEFAULTS = {'timezone': 'America/New_York', 'assumed_fast_percent': 0, 'pricing_catalog': None}


def configuration(db):
    result = dict(DEFAULTS)
    for key, value in db.execute("SELECT key,value FROM settings WHERE key IN ('timezone','assumed_fast_percent','pricing_catalog')"):
        result[key] = json.loads(value)
    return result


def stage_exists(db):
    return bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='rebuild_state' AND type='table'").fetchone())


def pending(db):
    row = db.execute('SELECT value FROM settings WHERE key=?', (KEY,)).fetchone()
    return json.loads(row[0]) if row else None


def request(db, changes=None):
    """Call in the same transaction as a source mutation; settings stay accepted."""
    saved = pending(db)
    accepted = saved['accepted'] if saved else None if stage_exists(db) else configuration(db)
    target = {**configuration(db), **(saved['target'] if saved else {}), **(changes or {})}
    value = {'accepted': accepted, 'target': target}
    db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)', (KEY, json.dumps(value)))
    return value


def target(db):
    saved = pending(db)
    return saved['target'] if saved else configuration(db)


def status(db):
    saved = pending(db)
    legacy = stage_exists(db) and not saved
    return {'pending': bool(saved or legacy), 'readable': not legacy and (not saved or saved['accepted'] is not None)}


def needs_rebuild(store, version):
    if getattr(store, '_staging_projection', False):
        return False
    with store.connect() as db:
        row = db.execute("SELECT value FROM settings WHERE key='projection_version'").fetchone()
        return not row or json.loads(row[0]) != version or status(db)['pending']


def publish(db):
    saved = pending(db)
    if saved:
        db.executemany('INSERT OR REPLACE INTO settings VALUES(?,?)',
                       [(key, json.dumps(value)) for key, value in saved['target'].items()])
        db.execute('DELETE FROM settings WHERE key=?', (KEY,))


class ProjectionStore:
    """A stage's immutable preferences; cooperative work keeps the real store."""
    def __init__(self, store, config):
        self.store, self.config = store, config

    def setting(self, key, default=None):
        return self.config[key] if key in self.config else self.store.setting(key, default)

    def __getattr__(self, name):
        return getattr(self.store, name)


def activate(store):
    """Refresh the catalog exposed by compatibility APIs only after commit."""
    from .pricing_catalog import apply_catalog
    value = store.setting('pricing_catalog')
    if value is not None:
        apply_catalog(value)
