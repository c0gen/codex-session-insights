import shutil
import sqlite3

import pytest

from codex_insights.index_recovery import compare, integrity, prepare
from codex_insights.ingestion import refresh
from conftest import log, token


def test_prepare_selects_valid_backup_and_preserves_original_and_import_history(indexed, tmp_path):
    store, root, sid = indexed
    (root / 'chat.jsonl').write_bytes(log() + token(100))
    refresh(store)
    with store.connect() as db:
        db.execute("UPDATE sources SET kind='import',root=NULL WHERE id=?", (sid,))
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    shutil.copy2(store.path, evidence / 'insights.before-test.sqlite3')
    original = evidence / 'insights.sqlite3'
    original.write_bytes(b'broken SQLite data')
    result = prepare(evidence, tmp_path / 'candidate')
    assert result['base'] == 'insights.before-test.sqlite3'
    assert not result['promotion_allowed']
    assert original.read_bytes() == b'broken SQLite data'
    candidate = tmp_path / 'candidate' / 'insights.sqlite3'
    assert integrity(candidate)['ok']
    assert compare(store.path, candidate)['preserved']
    with sqlite3.connect(candidate) as db:
        db.execute('DELETE FROM history_variants')
    assert not compare(store.path, candidate)['preserved']


def test_invalid_backups_and_existing_destinations_are_never_overwritten(tmp_path):
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    (evidence / 'insights.sqlite3').write_bytes(b'invalid')
    target = tmp_path / 'candidate'
    with pytest.raises(ValueError, match='No integrity'):
        prepare(evidence, target)
    assert not target.exists()
    target.mkdir()
    with pytest.raises(ValueError, match='new recovery'):
        prepare(evidence, target)


def test_interrupted_preparation_is_marked_and_cannot_be_reused(indexed, tmp_path, monkeypatch):
    store, root, sid = indexed
    evidence = tmp_path / 'evidence'
    evidence.mkdir()
    shutil.copy2(store.path, evidence / 'insights.sqlite3')
    (evidence / 'imports').mkdir()
    target = tmp_path / 'candidate'

    def interrupted(*args, **kwargs):
        raise OSError('simulated interrupted copy')

    monkeypatch.setattr(shutil, 'copytree', interrupted)
    with pytest.raises(OSError, match='interrupted copy'):
        prepare(evidence, target)
    assert (target / 'RECOVERY_INCOMPLETE').exists()
    assert not (target / 'recovery-report.json').exists()
    assert integrity(evidence / 'insights.sqlite3')['ok']
    with pytest.raises(ValueError, match='new recovery'):
        prepare(evidence, target)
