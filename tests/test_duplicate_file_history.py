import json

import pytest

from codex_insights.ingestion import refresh
from codex_insights.queries import dashboard
from codex_insights.storage import Store
from conftest import log, token


@pytest.mark.parametrize('long_name,short_name', [('a.jsonl', 'z.jsonl'), ('z.jsonl', 'a.jsonl')])
def test_prefix_copies_preserve_full_history_and_append(indexed, long_name, short_name):
    store, root, _ = indexed
    short = log() + token(100)
    long = short + token(300, 5, last=200)
    (root / long_name).write_bytes(long)
    (root / short_name).write_bytes(short)
    (root / 'exact.jsonl').write_bytes(long)
    refresh(store)
    assert dashboard(store)['summary']['total_tokens'] == 330
    restarted = Store(store.directory)
    assert refresh(restarted)['bytes_read'] == 0
    assert dashboard(restarted)['summary']['total_tokens'] == 330
    with (root / short_name).open('ab') as stream:
        stream.write(token(300, 5, last=200) + token(400, 6, last=100))
    refresh(restarted)
    assert dashboard(restarted)['summary']['total_tokens'] == 440


def test_divergent_copy_preserves_accepted_history_with_diagnostic(indexed):
    store, root, sid = indexed
    (root / 'accepted.jsonl').write_bytes(log() + token(100))
    refresh(store)
    revision = store.setting('data_revision')
    (root / 'divergent.jsonl').write_bytes(log() + token(900) + token(1000, 5, last=100))
    refresh(store)
    assert dashboard(store)['summary']['total_tokens'] == 110
    assert dashboard(store)['coverage']['conflicts'] == 1
    assert store.setting('data_revision') > revision
    restarted = Store(store.directory)
    refresh(restarted, rebuild=True)
    assert dashboard(restarted)['summary']['total_tokens'] == 110
    with restarted.connect() as db:
        diagnostic = json.loads(db.execute('SELECT diagnostic FROM canonical').fetchone()[0])
    assert sid in diagnostic['conflicts']
    assert str(root) not in json.dumps(diagnostic)


def test_old_checkpoint_reparses_and_recovers_overwritten_candidate(indexed):
    store, root, _ = indexed
    short = log() + token(100)
    (root / 'a-long.jsonl').write_bytes(short + token(300, 5, last=200))
    (root / 'z-short.jsonl').write_bytes(short)
    refresh(store)
    # Simulate the old winner using the saved short physical-file checkpoint.
    from codex_insights.codec import unpack, pack
    from codex_insights.parser import SessionParser, portable_fact
    from codex_insights.projection import rebuild_projection
    with store.connect() as db:
        state = unpack(db.execute('SELECT state FROM files WHERE path=?', (str(root / 'z-short.jsonl'),)).fetchone()[0])
        fact = portable_fact(SessionParser(state).fact())
        db.execute('UPDATE candidates SET fact=?,record_count=?,byte_count=?,prefix_hash=?,parser_version=2',
                   (pack(fact), fact['record_count'], fact['byte_count'], fact['prefix_hash']))
        db.execute('UPDATE files SET parser_version=2')
        db.execute('DELETE FROM history_variants')
        db.execute('DELETE FROM canonical')
    rebuild_projection(store)
    assert dashboard(store)['summary']['total_tokens'] == 110
    assert refresh(Store(store.directory))['changed_files'] == 2
    assert dashboard(store)['summary']['total_tokens'] == 330
    assert refresh(store)['bytes_read'] == 0


def test_offline_old_source_retained_until_reconnected(indexed):
    store, root, sid = indexed
    (root / 'chat.jsonl').write_bytes(log() + token(100))
    refresh(store)
    with store.connect() as db:
        db.execute('UPDATE files SET parser_version=2')
        db.execute('UPDATE sources SET root=? WHERE id=?', (str(root / 'offline'), sid))
    assert refresh(Store(store.directory))['bytes_read'] == 0
    assert dashboard(store)['summary']['total_tokens'] == 110
    assert store.sources()[0]['status'] == 'Offline'
    with store.connect() as db:
        db.execute('UPDATE sources SET root=? WHERE id=?', (str(root), sid))
    assert refresh(store)['changed_files'] == 1
    assert refresh(store)['bytes_read'] == 0


def test_fuller_same_source_history_survives_snapshot_without_paths(indexed, tmp_path):
    import zipfile
    from codex_insights.transfers import export_snapshot, import_snapshot
    store, root, sid = indexed
    short = log() + token(100)
    (root / 'a.jsonl').write_bytes(short + token(300, 5, last=200))
    (root / 'z.jsonl').write_bytes(short)
    refresh(store)
    assert len(store.sources()) == 1 and store.sources()[0]['id'] == sid
    assert store.sources()[0]['segments'] == 1
    bundle = tmp_path / 'duplicate.codex-insights'
    export_snapshot(store, bundle)
    with zipfile.ZipFile(bundle) as archive:
        facts = archive.read('facts.jsonl')
        assert str(root).encode() not in facts and b'C:/private' not in facts
    target = Store(tmp_path / 'imported')
    import_snapshot(target, bundle)
    assert dashboard(target)['summary']['total_tokens'] == 330


def test_ignored_branch_does_not_block_compatible_extension_in_another_source(indexed, tmp_path):
    store, root, _ = indexed
    short = log() + token(100)
    (root / 'accepted.jsonl').write_bytes(short)
    refresh(store)
    (root / 'divergent.jsonl').write_bytes(log() + token(900))
    refresh(store)
    other = tmp_path / 'other-source'
    other.mkdir()
    store.add_source(other)
    (other / 'full.jsonl').write_bytes(short + token(300, 5, last=200))
    refresh(store)
    assert dashboard(store)['summary']['total_tokens'] == 330
    assert dashboard(store)['coverage']['conflicts'] == 1
