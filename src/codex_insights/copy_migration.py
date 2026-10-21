"""Restart-safe recovery of pre-review indexes, without opening original logs."""
import json
import sqlite3
from contextlib import closing

from .codec import unpack
from .copy_store import SCHEMA, retain

VERSION = 1


def backup_before_upgrade(path):
    if not path.exists():
        return
    with closing(sqlite3.connect(path)) as source:
        tables = {r[0] for r in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "settings" in tables and source.execute("SELECT 1 FROM settings WHERE key='copy_history_version' AND value=?", (str(VERSION),)).fetchone():
            return
        target = path.with_name("insights.before-copy-review.sqlite3")
        if not target.exists():
            temporary = target.with_suffix(".tmp")
            with closing(sqlite3.connect(temporary)) as destination:
                source.backup(destination)
            temporary.replace(target)


def migrate(db):
    db.executescript(SCHEMA)
    row = db.execute("SELECT value FROM settings WHERE key='copy_history_version'").fetchone()
    if row and json.loads(row[0]) == VERSION:
        return
    from .providers import adapter
    from .parser import portable_fact
    for row in db.execute("SELECT * FROM candidates"):
        retain(db, row["source_id"], unpack(row["fact"]), row["parser_version"])
        if row["same_source_conflict"]:
            db.execute("INSERT OR REPLACE INTO history_pending VALUES(?,?,'legacy_conflict')", (row["source_id"], row["segment_id"]))
        db.execute("INSERT OR IGNORE INTO projection_queue VALUES(?)", (row["segment_id"],))
    # Checkpoints include rejected physical copies even though old candidates do not.
    for row in db.execute("SELECT f.*,s.provider,s.kind,s.format FROM files f JOIN sources s ON s.id=f.source_id"):
        if row["format"] == "antigravity_legacy":
            continue
        try:
            parser = adapter(row["provider"]).parser(unpack(row["state"]), row["path"], row["kind"])
            fact = parser.fact()
            if fact:
                retain(db, row["source_id"], portable_fact(fact), row["parser_version"], row["path"])
        except (ValueError, TypeError, KeyError, AttributeError):
            # A damaged/older checkpoint never justifies dropping accepted facts.
            continue
    db.execute("INSERT OR REPLACE INTO settings VALUES('copy_history_version',?)", (str(VERSION),))
