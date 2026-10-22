"""Validated source records retained independently of derived metric generations."""
import hashlib
import json
import re
import sqlite3
import zipfile

from .codec import dumps, loads, pack, unpack

VALIDATOR_VERSION = 1
SCHEMA = """CREATE TABLE IF NOT EXISTS transfer_fingerprints(
 source_id TEXT,segment_id TEXT,format_version INTEGER,validator_version INTEGER,
 fingerprint TEXT,value BLOB,PRIMARY KEY(source_id,segment_id));"""


def ensure_schema(db):
    db.execute(SCHEMA)
    db.execute('CREATE TABLE IF NOT EXISTS transfer_fingerprint_sources(source_id TEXT PRIMARY KEY,revision INTEGER,fact_count INTEGER)')
    columns = {r[1] for r in db.execute('PRAGMA table_info(transfer_fingerprints)')}
    for name, datatype in (('provider', 'TEXT'), ('session_id', 'TEXT'), ('parent_id', 'TEXT'), ('legacy', 'INTEGER')):
        if name not in columns:
            db.execute('ALTER TABLE transfer_fingerprints ADD COLUMN ' + name + ' ' + datatype)
    db.execute('CREATE INDEX IF NOT EXISTS fingerprints_digest ON transfer_fingerprints(source_id,fingerprint,format_version,validator_version)')
    db.execute('CREATE INDEX IF NOT EXISTS fingerprints_session ON transfer_fingerprints(source_id,session_id)')


def read_archive(store, path, target, progress=None, cancel=None):
    """Decompress once, verifying framing, checksum, identity and every new record.

    Trusted reuse requires both matching bytes and the current validator version;
    checksum and count checks also apply to old/repeated source revisions.
    """
    from .transfers import MAX_BYTES, MAX_LINE, validate_fact
    from .history_transfers import validate
    with zipfile.ZipFile(path) as bundle, store.connect() as accepted:
        if sorted(bundle.namelist()) != ['facts.jsonl', 'manifest.json']:
            raise ValueError('A snapshot must contain exactly manifest.json and facts.jsonl')
        if bundle.getinfo('manifest.json').file_size > 64 * 1024 or bundle.getinfo('facts.jsonl').file_size > MAX_BYTES:
            raise ValueError('Snapshot exceeds the supported size limit')
        manifest = json.loads(bundle.read('manifest.json'))
        version = manifest.get('format_version')
        if manifest.get('format') != 'codex-session-insights' or type(version) is not int or version not in range(1, 7):
            raise ValueError('Unsupported snapshot version; update the app or exporter')
        exporter = manifest.get('exporter_id')
        if not isinstance(exporter, str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,64}', exporter):
            raise ValueError('Invalid exporter identity')
        if type(manifest.get('revision')) is not int or manifest['revision'] < 1:
            raise ValueError('Invalid snapshot revision')
        if type(manifest.get('fact_count')) is not int or manifest['fact_count'] < 0:
            raise ValueError('Invalid snapshot session count')
        source = 'import:' + exporter
        ensure_schema(accepted)
        ensure_schema(target)
        checksum, count, reused, total_bytes = hashlib.sha256(), 0, 0, 0
        claude, legacy = False, False
        invalid = None
        if progress:
            progress({'phase': 'Validating snapshot', 'checked': 0, 'reused': 0})
        with bundle.open('facts.jsonl') as stream:
            while True:
                if cancel and cancel.is_set():
                    raise InterruptedError('Import cancelled')
                line = stream.readline(MAX_LINE + 1)
                if not line:
                    break
                total_bytes += len(line)
                if total_bytes > MAX_BYTES:
                    raise ValueError('Snapshot exceeds the supported size limit')
                checksum.update(line)
                if len(line) > MAX_LINE or not line.endswith(b'\n'):
                    invalid = invalid or ValueError('Invalid or oversized fact record')
                    continue
                if invalid is not None:
                    continue
                try:
                    fingerprint = hashlib.sha256(line).hexdigest()
                    old = accepted.execute('SELECT segment_id,value,provider,session_id,parent_id,legacy FROM transfer_fingerprints '
                        'WHERE source_id=? AND fingerprint=? AND format_version=? AND validator_version=? AND provider IS NOT NULL',
                        (source, fingerprint, version, VALIDATOR_VERSION)).fetchone()
                    if old:
                        segment, packed, provider, session, parent, legacy_entry = tuple(old)
                        reused += 1
                    else:
                        value = loads(line.decode('utf-8'))
                        fact = value.get('accepted') if version == 6 and isinstance(value, dict) else value
                        segment = fact.get('segment_id') if isinstance(fact, dict) else None
                        if not isinstance(segment, str):
                            raise ValueError('Missing session fingerprint')
                        if version == 6:
                            value = validate(value, validate_fact)
                            fact = value['accepted']
                        else:
                            if version == 1 and fact.get('provider', 'codex') != 'codex':
                                raise ValueError('Version 1 only supports Codex')
                            fact = validate_fact(fact, version)
                        entries = [fact] + (value['alternatives'] if version == 6 else [])
                        provider, session, parent = fact.get('provider', 'codex'), fact['id'], fact.get('parent_session_id')
                        legacy_entry = any(entry.get('provider') == 'claude_code' and
                            str(entry.get('id', '')).startswith('claude_code:agent-') and bool(entry.get('parent_session_id')) for entry in entries)
                        packed = pack(value)
                    claude |= provider == 'claude_code'
                    legacy |= bool(legacy_entry)
                    try:
                        target.execute('INSERT INTO transfer_fingerprints VALUES(?,?,?,?,?,?,?,?,?,?)',
                            (source, segment, version, VALIDATOR_VERSION, fingerprint, packed, provider, session, parent, int(legacy_entry)))
                    except sqlite3.IntegrityError:
                        raise ValueError('Duplicate session segment in snapshot') from None
                    count += 1
                    if count % 50 == 0:
                        from .cooperative import checkpoint, cancelled
                        cancelled(store)
                        checkpoint(store)
                    if progress and count % 50 == 0:
                        progress({'phase': 'Validating snapshot', 'checked': count, 'reused': reused, 'sessions': count})
                except (ValueError, UnicodeError, TypeError, KeyError) as error:
                    invalid = error
        if checksum.hexdigest() != manifest.get('facts_sha256'):
            raise ValueError('Snapshot checksum does not match')
        if invalid is not None:
            raise invalid
        if count != manifest.get('fact_count'):
            raise ValueError('Snapshot session count does not match')
        return manifest, {'checked': count, 'reused': reused}, claude, legacy


def backfill(store, source, revision, directory, progress=None, cancel=None):
    """Recover a ledger from the exact retained accepted archive, without metrics."""
    from pathlib import Path
    archive = store.directory / 'imports' / (source[7:] + '-' + str(revision) + '.codex-insights')
    if not archive.exists():
        return False
    path = Path(directory) / 'backfill.sqlite'
    target = sqlite3.connect(path)
    try:
        manifest, _, _, _ = read_archive(store, archive, target, progress, cancel)
        target.commit()
        if 'import:' + manifest['exporter_id'] != source or manifest['revision'] != revision:
            return False
        with store.lock, store.connect() as db:
            current = db.execute('SELECT revision FROM sources WHERE id=?', (source,)).fetchone()
            if not current or current[0] != revision:
                return False
            db.execute('ATTACH DATABASE ? AS prior', (str(path),))
            db.execute('DELETE FROM transfer_fingerprints WHERE source_id=?', (source,))
            db.execute('INSERT OR IGNORE INTO transfer_fingerprints SELECT * FROM prior.transfer_fingerprints')
            db.execute('INSERT OR REPLACE INTO transfer_fingerprint_sources VALUES(?,?,?)', (source, revision, manifest['fact_count']))
        return True
    finally:
        target.close()


def backfill_matching_evidence(store, source, incoming):
    """Prove unchanged input against stored accepted facts when no archive remains.

    Raw fingerprints are learned only after full validation and an exact match
    of accepted facts, retained alternatives, pending evidence and review choices.
    No canonical selection or derived-row rebuild is needed for that proof.
    """
    from .copy_reconciliation import variant_id
    from .copy_store import choice
    count = 0
    overlap_selections = {}
    for row in incoming.execute('SELECT session_id,value FROM transfer_fingerprints WHERE source_id=? AND format_version=6', (source,)):
        value = unpack(row['value'])
        overlap_selections.setdefault(row['session_id'], None)
        if value['accounting_selection']:
            overlap_selections[row['session_id']] = value['accounting_selection']
    with store.lock, store.connect() as db:
        for row in incoming.execute('SELECT * FROM transfer_fingerprints WHERE source_id=?', (source,)):
            if db.execute('SELECT 1 FROM transfer_fingerprints WHERE source_id=? AND segment_id=?', (source, row['segment_id'])).fetchone():
                continue
            value = unpack(row['value'])
            fact = value['accepted'] if row['format_version'] == 6 else value
            candidate = db.execute('SELECT fact FROM candidates WHERE source_id=? AND segment_id=?', (source, row['segment_id'])).fetchone()
            if not candidate or unpack(candidate[0]) != fact:
                continue
            if row['format_version'] == 6:
                retained = {variant_id(unpack(r[0])) for r in db.execute('SELECT fact FROM history_variants WHERE source_id=? AND segment_id=?', (source, row['segment_id']))}
                if retained != {variant_id(f) for f in [fact] + value['alternatives']}:
                    continue
                pending = bool(db.execute('SELECT 1 FROM history_pending WHERE source_id=? AND segment_id=?', (source, row['segment_id'])).fetchone())
                if pending != value['awaiting_verification'] or choice(db, 'copy:' + fact['segment_id'], source) != value['selection']:
                    continue
                if choice(db, 'overlap:' + fact['id'], source) != overlap_selections.get(fact['id']):
                    continue
            db.execute('INSERT INTO transfer_fingerprints VALUES(?,?,?,?,?,?,?,?,?,?)', tuple(row))
            count += 1
        missing = db.execute('SELECT 1 FROM candidates c WHERE source_id=? AND NOT EXISTS('
            'SELECT 1 FROM transfer_fingerprints f WHERE f.source_id=c.source_id AND f.segment_id=c.segment_id) LIMIT 1', (source,)).fetchone()
        if not missing:
            current = db.execute('SELECT revision FROM sources WHERE id=?', (source,)).fetchone()
            if current:
                total = db.execute('SELECT count(*) FROM transfer_fingerprints WHERE source_id=?', (source,)).fetchone()[0]
                db.execute('INSERT OR REPLACE INTO transfer_fingerprint_sources VALUES(?,?,?)', (source, current[0], total))
    return count
