"""Stable project identities, resumable membership backfill and metadata-only merges.

Facts and metric rows always retain their original identity. A group is a root
project identity; every member points directly at that root, including aliases
without currently indexed sessions. Undo restores identities, not a list of chats.
"""
import json
import uuid
from datetime import datetime, timezone

from .codec import unpack

VERSION = 1
SCHEMA = """
CREATE TABLE IF NOT EXISTS project_memberships(
 project_id TEXT PRIMARY KEY, name TEXT NOT NULL, group_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS membership_group ON project_memberships(group_id);
CREATE TABLE IF NOT EXISTS session_projects(
 segment_id TEXT PRIMARY KEY, original_project_id TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS session_original_project ON session_projects(original_project_id);
CREATE VIEW IF NOT EXISTS project_sessions AS
 SELECT c.segment_id,coalesce(s.original_project_id,c.project_id) original_project_id,
 coalesce(m.group_id,c.project_id) project_id,coalesce(g.name,c.project_label) name
 FROM canonical c LEFT JOIN session_projects s ON s.segment_id=c.segment_id
 LEFT JOIN project_memberships m ON m.project_id=coalesce(s.original_project_id,c.project_id)
 LEFT JOIN project_memberships g ON g.project_id=m.group_id;
"""


def setting(db, key, default=None):
    row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def save(db, key, value):
    db.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, json.dumps(value)))


def resolve_alias(project_id, aliases):
    """Resolve the legacy/public alias representation, rejecting corrupt cycles."""
    visited = set()
    while project_id in aliases:
        if project_id in visited:
            raise ValueError("Project aliases contain a cycle")
        visited.add(project_id)
        project_id = aliases[project_id]["id"]
    return project_id


def ensure_schema(db):
    db.executescript(SCHEMA)
    # Seed inexpensive labels for queries before fact backfill finishes. This
    # runs once on upgrade; migration itself commits bounded, restartable batches.
    if not setting(db, "project_groups_seeded", False):
        aliases = setting(db, "project_aliases", {})
        labels = {r[0]: r[1] for r in db.execute(
            "SELECT project_id,project_label FROM canonical GROUP BY project_id")}
        for source, target in aliases.items():
            labels.setdefault(source, source.rsplit("/", 1)[-1])
            labels.setdefault(target["id"], target["name"])
        for pid, name in labels.items():
            group = resolve_alias(pid, aliases)
            db.execute("INSERT OR IGNORE INTO project_memberships VALUES(?,?,?)", (pid, name, group))
        save(db, "project_groups_seeded", True)
        if not db.execute("SELECT 1 FROM canonical LIMIT 1").fetchone():
            save(db, "project_groups_version", VERSION)


def register_session(db, segment_id, fact):
    """The common path for ingestion, imports, rebuilds and migration."""
    pid, name = fact["project_id"], fact["project_label"]
    member = db.execute("SELECT group_id FROM project_memberships WHERE project_id=?", (pid,)).fetchone()
    if not member:
        aliases = setting(db, "project_aliases", {})
        group = resolve_alias(pid, aliases)
        if group != pid:
            label = next((a["name"] for a in aliases.values() if a["id"] == group), group)
            db.execute("INSERT OR IGNORE INTO project_memberships VALUES(?,?,?)", (group, label, group))
        db.execute("INSERT INTO project_memberships VALUES(?,?,?)", (pid, name, group))
    else:
        db.execute("UPDATE project_memberships SET name=? WHERE project_id=? AND name<>?", (name, pid, name))
    db.execute("INSERT INTO session_projects VALUES(?,?) ON CONFLICT(segment_id) DO UPDATE SET original_project_id=excluded.original_project_id",
               (segment_id, pid))


def migrate(store, progress=None, cancel=None, batch_size=200):
    """Backfill only stored fact identities; never read logs or rewrite metrics."""
    completed = 0
    while not cancel or not cancel.is_set():
        with store.lock, store.connect() as db:
            rows = db.execute("SELECT c.segment_id,c.fact FROM canonical c LEFT JOIN session_projects s ON s.segment_id=c.segment_id WHERE s.segment_id IS NULL ORDER BY c.segment_id LIMIT ?",
                              (batch_size,)).fetchall()
            for row in rows:
                register_session(db, row[0], unpack(row[1]))
            completed += len(rows)
            if not rows:
                save(db, "project_groups_version", VERSION)
                save(db, "data_revision", setting(db, "data_revision", 0) + 1)
                return {"sessions": completed, "status": "completed"}
        if progress:
            progress({"sessions": completed, "phase": "Recovering original project identities"})
    return {"sessions": completed, "status": "cancelled"}


def resolve_project(db, project_id):
    row = db.execute("SELECT group_id FROM project_memberships WHERE project_id=?", (project_id,)).fetchone()
    group = row[0] if row else resolve_alias(project_id, setting(db, "project_aliases", {}))
    root = db.execute("SELECT group_id FROM project_memberships WHERE project_id=?", (group,)).fetchone()
    if root and root[0] != group:
        raise ValueError("Project membership contains a cycle or non-root destination")
    return group


def sync_aliases(db):
    aliases = {row[0]: {"id": row[1], "name": row[2]} for row in db.execute(
        "SELECT m.project_id,m.group_id,g.name FROM project_memberships m JOIN project_memberships g ON g.project_id=m.group_id WHERE m.project_id<>m.group_id")}
    save(db, "project_aliases", aliases)


def merge_projects(store, sources, target):
    if not isinstance(sources, list) or not sources or any(not isinstance(s, str) or not s for s in sources):
        raise ValueError("Select at least one source project")
    if not isinstance(target, str) or not target:
        raise ValueError("Choose a destination project")
    with store.lock, store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if setting(db, "project_groups_version") != VERSION:
            raise ValueError("Project identity migration is still running. Retry when it finishes.")
        # Validate inside the transaction/queued operation, against today's groups.
        aliases = setting(db, "project_aliases", {})
        for pid in aliases:
            resolve_alias(pid, aliases)
        destination = resolve_project(db, target)
        exists = db.execute("SELECT name FROM project_sessions WHERE project_id=? LIMIT 1", (destination,)).fetchone()
        if not exists:
            raise ValueError("Destination project is no longer indexed")
        groups = sorted({resolve_project(db, pid) for pid in sources} - {destination})
        if not groups:
            raise ValueError("Choose a source group different from the destination")
        for group in groups:
            if not db.execute("SELECT 1 FROM project_sessions WHERE project_id=? LIMIT 1", (group,)).fetchone():
                raise ValueError("A source project is no longer indexed")
        placeholders = ",".join("?" for _ in groups)
        members = [dict(r) for r in db.execute(
            f"SELECT project_id,group_id FROM project_memberships WHERE group_id IN ({placeholders})", groups)]
        preview = [dict(r) for r in db.execute(
            f"SELECT project_id id,name FROM project_memberships WHERE project_id IN ({placeholders})", groups)]
        count = db.execute(f"SELECT count(*) FROM session_projects s JOIN project_memberships m ON m.project_id=s.original_project_id WHERE m.group_id IN ({placeholders})", groups).fetchone()[0]
        operation = {"operation_id": str(uuid.uuid4()), "sources": preview,
                     "target": {"id": destination, "name": exists[0]}, "sessions": count,
                     "identities": len(members), "completed_at": datetime.now(timezone.utc).isoformat(),
                     "members_before": members}
        db.execute(f"UPDATE project_memberships SET group_id=? WHERE group_id IN ({placeholders})", [destination, *groups])
        sync_aliases(db)
        save(db, "last_project_merge", operation)
        save(db, "data_revision", setting(db, "data_revision", 0) + 1)
        return public_merge(operation)


def public_merge(operation):
    return {k: v for k, v in operation.items() if k != "members_before"} if operation else None


def undo_project_merge(store, operation_id):
    with store.lock, store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        operation = setting(db, "last_project_merge")
        if not operation or operation["operation_id"] != operation_id:
            raise ValueError("Only the latest merge can be undone")
        db.executemany("UPDATE project_memberships SET group_id=? WHERE project_id=?",
                       [(r["group_id"], r["project_id"]) for r in operation["members_before"]])
        sync_aliases(db)
        save(db, "last_project_merge", None)
        save(db, "data_revision", setting(db, "data_revision", 0) + 1)
        return {**public_merge(operation), "undone": True}
