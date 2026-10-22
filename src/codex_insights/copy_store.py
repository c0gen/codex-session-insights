"""Retained portable versions and materialized per-source candidates."""
from .codec import pack, unpack
from .copy_reconciliation import covers, select, variant_id

SCHEMA = """
CREATE TABLE IF NOT EXISTS history_variants(
 source_id TEXT,segment_id TEXT,variant_id TEXT,session_id TEXT,fact BLOB,parser_version INTEGER,
 PRIMARY KEY(source_id,segment_id,variant_id));
CREATE INDEX IF NOT EXISTS history_variants_session ON history_variants(session_id);
CREATE TABLE IF NOT EXISTS variant_locations(
 source_id TEXT,segment_id TEXT,variant_id TEXT,path TEXT,
 PRIMARY KEY(source_id,segment_id,variant_id,path));
CREATE TABLE IF NOT EXISTS history_pending(source_id TEXT,segment_id TEXT,reason TEXT,
 PRIMARY KEY(source_id,segment_id));
CREATE TABLE IF NOT EXISTS history_choices(group_id TEXT,scope TEXT,selection BLOB,
 PRIMARY KEY(group_id,scope));
"""


def retain(db, source_id, fact, parser_version=0, path=None):
    identity = variant_id(fact)
    # A byte extension contains the old physical boundaries too. Keep branches
    # and differently serialized versions, not an O(n²) series of append snapshots.
    for row in db.execute("SELECT variant_id,fact FROM history_variants WHERE source_id=? AND segment_id=?",
                          (source_id, fact["segment_id"])).fetchall():
        old = unpack(row["fact"])
        if (old["byte_count"] < fact["byte_count"]
                and fact.get("proofs", {}).get(str(old["byte_count"])) == old["prefix_hash"]
                and covers(fact, old)):
            # Do not claim that a different shorter physical copy contains the
            # new extension. The path observed for this version is added below.
            db.execute("DELETE FROM variant_locations WHERE source_id=? AND segment_id=? AND variant_id=?",
                       (source_id, fact["segment_id"], row["variant_id"]))
            db.execute("DELETE FROM history_variants WHERE source_id=? AND segment_id=? AND variant_id=?",
                       (source_id, fact["segment_id"], row["variant_id"]))
            for saved in db.execute("SELECT * FROM history_choices WHERE group_id IN (?,?)",
                                    ('copy:' + fact['segment_id'], 'overlap:' + fact['id'])).fetchall():
                value = unpack(saved["selection"])
                if value.get("selected") == row["variant_id"]:
                    value["selected"] = identity
                    value['reviewed'] = [f for f in value.get('reviewed', [])
                                         if variant_id(f) != row['variant_id']] + [fact]
                    db.execute("UPDATE history_choices SET selection=? WHERE group_id=? AND scope=?",
                               (pack(value), saved["group_id"], saved["scope"]))
    db.execute("INSERT OR REPLACE INTO history_variants VALUES(?,?,?,?,?,?)", (
        source_id, fact["segment_id"], identity, fact["id"], pack(fact), parser_version))
    if path:
        db.execute("INSERT OR IGNORE INTO variant_locations VALUES(?,?,?,?)", (
            source_id, fact["segment_id"], identity, str(path)))
    return identity


def variants(db, segment_id, source_id=None, local=False):
    where, params = "v.segment_id=? AND s.enabled=1", [segment_id]
    if source_id is not None:
        where += " AND v.source_id=?"
        params.append(source_id)
    if local:
        where += " AND s.kind IN ('folder','bridge')"
    return [{**dict(r), "fact": unpack(r["fact"])} for r in db.execute(
        "SELECT v.*,s.label,s.kind FROM history_variants v JOIN sources s ON s.id=v.source_id WHERE " + where,
        params)]


def choice(db, group_id, scope=""):
    row = db.execute("SELECT selection FROM history_choices WHERE group_id=? AND scope=?", (group_id, scope)).fetchone()
    return unpack(row[0]) if row else None


def effective_choice(db, group_id, preferred_source=None):
    local = choice(db, group_id)
    if local is not None:
        return local
    if preferred_source:
        inherited = choice(db, group_id, preferred_source)
        if inherited is not None:
            return inherited
    row = db.execute("SELECT h.selection FROM history_choices h JOIN sources s ON s.id=h.scope "
                     "WHERE h.group_id=? AND s.enabled=1 ORDER BY h.scope LIMIT 1", (group_id,)).fetchone()
    return unpack(row[0]) if row else None


def save_choice(db, group_id, selected, facts, scope=""):
    value = {"selected": selected, "reviewed": facts}
    db.execute("INSERT OR REPLACE INTO history_choices VALUES(?,?,?)", (group_id, scope, pack(value)))
    return value


def pending_sources(db, segment_id, source_id=None, local=False):
    extra, params = "", [segment_id]
    if source_id is not None:
        extra = " AND p.source_id=?"
        params.append(source_id)
    if local:
        extra += " AND s.kind IN ('folder','bridge')"
    return [r[0] for r in db.execute("SELECT p.source_id FROM history_pending p JOIN sources s ON s.id=p.source_id "
                                   "WHERE p.segment_id=? AND s.enabled=1" + extra, params)]


def write_candidate(db, source_id, fact, version=0):
    db.execute("INSERT OR REPLACE INTO candidates(source_id,segment_id,session_id,parent_id,record_count,trace_count,"
               "byte_count,prefix_hash,fact,parser_version,same_source_conflict,provider) VALUES(?,?,?,?,?,?,?,?,?,?,0,?)", (
        source_id, fact["segment_id"], fact["id"], fact.get("parent_session_id"), fact["record_count"],
        len(fact["raw_token_trace"]), fact["byte_count"], fact["prefix_hash"], pack(fact), version, fact.get("provider", "codex")))


def put(db, source_id, fact, version=0, path=None):
    old = db.execute("SELECT fact FROM candidates WHERE source_id=? AND segment_id=?", (source_id, fact["segment_id"])).fetchone()
    previous = {"source_id": source_id, "variant_id": variant_id(unpack(old[0])), "fact": unpack(old[0])} if old else None
    retain(db, source_id, fact, version, path)
    # Provider collectors already have explicit replacement/enrichment semantics.
    if fact.get("snapshot_mode") == "complete_binary" or fact.get("history_mode") == "antigravity_steps":
        write_candidate(db, source_id, fact, version)
        return
    items = variants(db, fact["segment_id"], source_id)
    # Disabled sources are retained but do not participate in global selection.
    if not items:
        items = [{"source_id": source_id, "variant_id": variant_id(fact), "fact": fact, "parser_version": version}]
    winner, _ = select(items, previous, effective_choice(db, "copy:" + fact["segment_id"], source_id))
    write_candidate(db, source_id, winner["fact"], winner["parser_version"])


def finish_verification(db, source_id, segments=None):
    """Only recovered evidence can retire an old, otherwise unexplainable flag."""
    changed = set()
    where, args = '', [source_id]
    if segments is not None:
        if not segments:
            return changed
        where = ' AND segment_id IN (' + ','.join('?' for _ in segments) + ')'
        args.extend(segments)
    for row in db.execute("SELECT segment_id FROM history_pending WHERE source_id=? AND reason='legacy_conflict'" + where, args).fetchall():
        items = variants(db, row[0], source_id)
        if len(items) < 2:
            continue
        facts = [v["fact"] for v in items]
        proved = all(f.get("record_hash") or any(other.get("record_hash") and covers(other, f)
                                                  for other in facts) for f in facts)
        if proved:
            db.execute("DELETE FROM history_pending WHERE source_id=? AND segment_id=?", (source_id, row[0]))
            changed.add(row[0])
    return changed


def forget(db, source_id):
    db.execute('DELETE FROM transfer_fingerprints WHERE source_id=?', (source_id,))
    db.execute('DELETE FROM transfer_fingerprint_sources WHERE source_id=?', (source_id,))
    for table in ('claude_recovery_sources', 'claude_recovery_stage', 'claude_recovery_baseline',
                  'claude_recovery_variants', 'claude_recovery_observations', 'claude_recovery_moves', 'claude_recovery_choices', 'claude_identity_issues'):
        db.execute('DELETE FROM ' + table + ' WHERE source_id=?', (source_id,))
    for table in ("variant_locations", "history_variants", "history_pending"):
        db.execute("DELETE FROM " + table + " WHERE source_id=?", (source_id,))
    db.execute("DELETE FROM history_choices WHERE scope=?", (source_id,))
    # Remove decisions only when their entire session has been forgotten.
    for row in db.execute("SELECT group_id FROM history_choices WHERE scope='' AND group_id LIKE 'copy:%'").fetchall():
        if not db.execute("SELECT 1 FROM history_variants WHERE segment_id=?", (row[0][5:],)).fetchone():
            db.execute("DELETE FROM history_choices WHERE group_id=?", (row[0],))
