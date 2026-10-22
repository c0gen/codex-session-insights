"""Incremental archive validation, sparse calculation and atomic acceptance."""
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import zipfile

from .codec import unpack
from .cooperative import checkpoint, cancelled
from .transfer_fingerprints import read_archive, ensure_schema


def import_snapshot(store, path, progress=None, cancel=None):
    from .storage import Store
    from .projection import ensure_projection
    ensure_projection(store)
    root = store.directory / 'work'
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='i-', dir=root) as directory:
        directory = Path(directory)
        incoming_path = directory / 'in.sqlite'
        incoming = sqlite3.connect(incoming_path)
        incoming.row_factory = sqlite3.Row
        try:
            manifest, counts, claude, legacy = read_archive(store, path, incoming, progress, cancel)
            incoming.commit()
            source = 'import:' + manifest['exporter_id']
            with store.connect() as db:
                existing = db.execute('SELECT revision FROM sources WHERE id=?', (source,)).fetchone()
                ledger = db.execute('SELECT revision,fact_count FROM transfer_fingerprint_sources WHERE source_id=?', (source,)).fetchone()
                ledger_count = db.execute('SELECT count(*) FROM transfer_fingerprints WHERE source_id=?', (source,)).fetchone()[0]
                valid_ledger = bool(existing and ledger and tuple(ledger) == (existing[0], ledger_count))
            if existing and not valid_ledger:
                # Historical hashes may validate identical bytes, but only the
                # current accepted revision can classify the incoming delta.
                with store.lock, store.connect() as db:
                    db.execute('DELETE FROM transfer_fingerprints WHERE source_id=?', (source,))
                    db.execute('DELETE FROM transfer_fingerprint_sources WHERE source_id=?', (source,))
                from .transfer_fingerprints import backfill
                try:
                    restored = backfill(store, source, existing[0], directory, progress, cancel)
                except InterruptedError:
                    raise
                except (ValueError, zipfile.BadZipFile, UnicodeError, OSError):
                    restored = False
                if not restored:
                    from .transfer_fingerprints import backfill_matching_evidence
                    counts['backfilled'] = backfill_matching_evidence(store, source, incoming)
            with store.connect() as db:
                existing = db.execute('SELECT * FROM sources WHERE id=?', (source,)).fetchone()
                recovery = db.execute("SELECT 1 FROM claude_recovery_sources WHERE source_id=? AND state!='complete'", (source,)).fetchone()
                decisions = [unpack(r[0]) for r in db.execute("SELECT h.selection FROM history_choices h WHERE h.scope='' AND EXISTS("
                    "SELECT 1 FROM candidates c WHERE h.group_id='copy:'||c.segment_id AND c.source_id=? AND c.provider='claude_code')", (source,))]
                ensure_schema(db)
                old = {r['segment_id']: tuple(r)[1:] for r in db.execute('SELECT segment_id,fingerprint,format_version,validator_version FROM transfer_fingerprints WHERE source_id=?', (source,))}
                previous = {r[0] for r in db.execute('SELECT segment_id FROM candidates WHERE source_id=?', (source,))}
                rekeyed_source = False
                ledger_source = db.execute('SELECT revision,fact_count FROM transfer_fingerprint_sources WHERE source_id=?', (source,)).fetchone()
                # Legacy recovery can rekey accepted identities. Snapshot input
                # membership remains the complete ledger's original segments.
                if existing and ledger_source and tuple(ledger_source) == (existing['revision'], len(old)):
                    rekeyed_source = previous != set(old)
                    previous = set(old)
            if existing and manifest['revision'] <= existing['revision']:
                return dict(status='unchanged', revision=existing['revision'], **counts, added=0, changed=0, removed=0, recalculated=0)
            new = {r['segment_id']: tuple(r)[1:] for r in incoming.execute('SELECT segment_id,fingerprint,format_version,validator_version FROM transfer_fingerprints')}
            added = set(new) - previous
            changed = {segment for segment in set(new) & previous if old.get(segment) != new[segment]}
            removed = previous - set(new)
            counts.update(added=len(added), changed=len(changed), removed=len(removed), recalculated=0)
            delta = added | changed
            repaired_choice = False
            if (delta or removed) and claude and decisions:
                from .claude_recovery_publish import physical_cover
                reviewed = [fact for decision in decisions for fact in decision.get('reviewed', [])]
                for row in incoming.execute("SELECT value,format_version FROM transfer_fingerprints WHERE provider='claude_code'"):
                    value = unpack(row['value'])
                    facts = [value['accepted']] + value['alternatives'] if row['format_version'] == 6 else [value]
                    if any(new['segment_id'] != old['segment_id'] and physical_cover(new, old) for new in facts for old in reviewed):
                        repaired_choice = True
                        break
            repair_source = rekeyed_source or claude and (legacy or manifest['format_version'] < 6 or recovery or repaired_choice) and (not existing or existing['enabled'])
            if (delta or removed) and repair_source:
                # Identity recovery has separate evidence/review publication rules.
                # Its established isolated path remains available for legacy input.
                from .transfers import _legacy_import_snapshot
                return _legacy_import_snapshot(store, path, progress, cancel)
            def report(value):
                if progress:
                    progress({**counts, **value})
            # Save bytes before publication, so any I/O failure leaves accepted
            # contributions and their revision untouched.
            backups = store.directory / 'imports'
            backups.mkdir(exist_ok=True)
            backup = backups / (manifest['exporter_id'] + '-' + str(manifest['revision']) + '.codex-insights')
            temporary = directory / 'archive'
            shutil.copyfile(path, temporary)
            os.replace(temporary, backup)
            cancelled(store)
            if cancel and cancel.is_set():
                raise InterruptedError('Import cancelled')
            if not delta and not removed:
                # A newer identical snapshot only advances source provenance.
                # No canonical selection, projection, staging clone or metrics.
                with store.lock, store.connect() as db:
                    db.execute("INSERT INTO sources(id,label,kind,revision,status,updated) VALUES(?,?,'import',?,'Imported',?) "
                        'ON CONFLICT(id) DO UPDATE SET label=excluded.label,revision=excluded.revision,status=excluded.status,updated=excluded.updated WHERE sources.revision<excluded.revision',
                        (source, str(manifest.get('label') or 'Imported computer')[:200], manifest['revision'], manifest.get('created_at')))
                    db.execute('INSERT OR REPLACE INTO transfer_fingerprint_sources VALUES(?,?,?)', (source, manifest['revision'], manifest['fact_count']))
                return dict(status='imported', sessions=counts['checked'], revision=manifest['revision'], **counts)
            while True:
                cancelled(store)
                if cancel and cancel.is_set():
                    raise InterruptedError('Import cancelled')
                checkpoint(store)
                stage_dir = directory / 's'
                shadow = Store(stage_dir)
                from .transfer_staging import prepare
                context, since, required, affected, providers, choices, old_ids, relation_ids = prepare(store, shadow, incoming, source, delta, removed, manifest, report)
                counts['recalculated'] = len(affected)
                cancelled(store)
                if cancel and cancel.is_set():
                    raise InterruptedError('Import cancelled')
                if progress:
                    progress(dict(counts, phase='Publishing snapshot'))
                cancelled(store)
                if cancel and cancel.is_set():
                    raise InterruptedError('Import cancelled')
                from .transfer_publication import publish
                accepted = publish(store, shadow, incoming_path, source, delta, removed, affected, required, context, since, providers, manifest, choices, old_ids, relation_ids)
                if accepted:
                    return dict(status='unchanged' if accepted == 'unchanged' else 'imported', sessions=counts['checked'], revision=manifest['revision'], **counts)
                shutil.rmtree(stage_dir)
        finally:
            incoming.close()
