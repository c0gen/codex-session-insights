"""Paired counters migrate accepted records in durable bounded units."""
import threading

import pytest

from codex_insights.buckets import rebuild_buckets
from codex_insights.ingestion import refresh
from codex_insights.queries import dashboard
from conftest import log, token


def test_cancelled_migration_resumes_and_matches_records(indexed):
    store, root, _ = indexed
    for index in range(20):
        (root / f'{index}.jsonl').write_bytes(log(str(index)) + token(100))
    refresh(store)
    store.set_setting('bucket_version', 1)
    with store.connect() as db:
        db.execute('UPDATE metric_buckets SET paired_reasoning=0,paired_output=0,paired_responses=0')
        assert db.execute('SELECT count(*) FROM bucket_migration').fetchone()[0] == 0
    cancel, calls = threading.Event(), []
    store.maintenance_cancel = cancel
    def checkpoint():
        calls.append(1)
        if len(calls) == 2:
            cancel.set()
    store.cooperate = checkpoint
    with pytest.raises(InterruptedError):
        rebuild_buckets(store, resume=True)
    assert store.setting('bucket_version') == 1
    with store.connect() as db:
        assert db.execute('SELECT count(*) FROM bucket_migration_pending').fetchone()[0] == 4
    del store.cooperate
    cancel.clear()
    rebuild_buckets(store, resume=True)
    assert store.setting('bucket_version') == 2
    paired = dashboard(store)['usage_metrics']['reasoning_share_basis']
    store.set_setting('bucket_version', None)
    assert dashboard(store)['usage_metrics']['reasoning_share_basis'] == paired
