"""Cheap identities captured in the analytics reader's SQLite transaction."""
from datetime import datetime
import hashlib
import json
from zoneinfo import ZoneInfo

VERSION = 3


def context(db, at=None):
    settings = dict(db.execute("SELECT key,value FROM settings WHERE key IN "
        "('timezone','assumed_fast_percent','pricing_catalog','project_aliases','projection_version','hot_metadata_version')"))
    sources = [tuple(r) for r in db.execute('SELECT id,label,enabled,root,revision FROM sources ORDER BY id')]
    zone = ZoneInfo(json.loads(settings.get('timezone', '"UTC"')))
    day = (at.astimezone(zone) if at else datetime.now(zone)).date().isoformat()
    return hashlib.sha256(json.dumps([VERSION, settings, sources, day], sort_keys=True).encode()).hexdigest()


def identity(db, filters, at=None):
    from .projection_state import status
    if not status(db)['readable']:
        raise ValueError('Updating usage index. Waiting for the accepted configuration to be verified.')
    signature = context(db, at)
    row = db.execute("SELECT value FROM settings WHERE key='data_revision'").fetchone()
    metadata = db.execute('SELECT revision FROM performance_state WHERE id=1').fetchone()[0]
    coverage = db.execute('SELECT revision FROM coverage_state WHERE id=1').fetchone()[0]
    health = [tuple(r) for r in db.execute('SELECT id,status,updated,detail FROM sources ORDER BY id')]
    return (signature, json.loads(row[0]) if row else 0, metadata, coverage,
            json.dumps([filters, health], sort_keys=True))


class DashboardResult(dict):
    """Private attributes never become part of the serialized dashboard contract."""
    def __init__(self, value, snapshot_key):
        super().__init__(value)
        self.snapshot_key = snapshot_key
