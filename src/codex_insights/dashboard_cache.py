"""Bounded analytics cache and credential-free last overview for startup."""
from collections import OrderedDict
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
import threading

from .query_snapshot import VERSION, context, identity
FILTERS = ('range', 'project_id', 'model', 'source_id', 'provider', 'start', 'end')


def selected(args):
    return {key: args.get(key, 'all' if key == 'range' else '') for key in FILTERS}


class OverviewSnapshot:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'overview-cache.json'
        self.lock = threading.Lock()

    def load(self, filters):
        try:
            if self.path.stat().st_size > 8 * 1024 * 1024:
                return None
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            if saved['version'] != VERSION or saved['filters'] != selected(filters):
                return None
            with sqlite3.connect((self.directory / 'insights.sqlite3').resolve().as_uri() + '?mode=ro', uri=True, timeout=.1) as db:
                db.execute('BEGIN')
                from .projection_state import status
                if not status(db)['readable']:
                    return None
                if context(db) != saved['context']:
                    return None
            value = saved['data']
            value['cached_at'] = value['generated_at']
            return value
        except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
            return None

    def save(self, value, signature):
        # Explicit allowlist: no account responses, credentials or provider setup.
        keys = ('summary', 'timeline', 'projects', 'models', 'heatmap', 'tiers', 'efforts', 'agents', 'highlights',
                'equivalents', 'options', 'sources', 'timezone', 'revision', 'generated_at', 'date_bounds', 'demo',
                'coverage', 'settings', 'filters', 'usage_metrics', 'daily_sessions', 'source_states', 'indexed_token_totals')
        data = {k: deepcopy(value[k]) for k in keys if k in value}
        for source in data.get('sources', []):
            for key in ('root', 'detail', 'index_health', 'legacy_diagnostics'):
                source.pop(key, None)
            source.update(root=None, detail='')
        data.update(job={'running': False, 'message': 'Checking for updates', 'progress': {}, 'error': None}, exporter=False)
        payload = json.dumps({'version': VERSION, 'filters': selected(value['filters']), 'context': signature, 'data': data})
        if len(payload.encode()) > 8 * 1024 * 1024:
            return
        with self.lock:
            temporary = self.path.with_suffix('.tmp')
            try:
                temporary.write_text(payload, encoding='utf-8')
                os.replace(temporary, self.path)
            except OSError:
                # A read-only/full disk must not break an otherwise valid query.
                pass


class DashboardCache:
    def __init__(self, store):
        self.store, self.values, self.lock = store, OrderedDict(), threading.Lock()
        self.snapshot = OverviewSnapshot(store.directory)
        self.latest, self.pending, self.errors = {}, {}, {}
        self.pending_views = set()
        self.orders, self.sequence, self.snapshot_order = {}, 0, None
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='insights-analytics')

    def key(self, filters):
        with self.store.connect() as db:
            db.execute('BEGIN')
            return identity(db, filters)

    def read(self, filters):
        filters = dict(filters)
        background = filters.pop('_background', False) is True
        retry = filters.pop('_retry', False) is True
        key = self.key(filters)
        view_key = (key[0], json.dumps(filters, sort_keys=True))
        with self.lock:
            if key in self.values:
                self.values.move_to_end(key)
                return deepcopy(self.values[key])
            if retry:
                self.errors.pop(key, None)
            if key in self.errors:
                raise ValueError(self.errors[key])
            previous = self.latest.get(view_key)
            if background and previous:
                if view_key not in self.pending_views:
                    self.pending_views.add(view_key)
                    self.pending[key] = self.executor.submit(self._refresh, filters, key, view_key)
                return {**deepcopy(previous), 'analytics_refreshing': True}
        return self._compute(filters, key, view_key)

    def _compute(self, filters, key, view_key):
        from .queries import dashboard
        with self.lock:
            self.sequence += 1
            sequence = self.sequence
        result = dashboard(self.store, filters)
        captured = result.snapshot_key
        value = dict(result)
        current = self.key(filters)
        order = (*captured[1:4], sequence)
        captured_view = (captured[0], json.dumps(filters, sort_keys=True))
        if captured[0] == current[0]:
            with self.lock:
                self.values[captured] = deepcopy(value)
                if order > self.orders.get(captured_view, (-1,)):
                    self.latest[captured_view] = deepcopy(value)
                    self.orders[captured_view] = order
                    if filters.get('_view') == 'overview' and (self.snapshot_order is None or order > self.snapshot_order):
                        self.snapshot.save(value, captured[0])
                        self.snapshot_order = order
                while len(self.values) > 8:
                    self.values.popitem(last=False)
                while len(self.latest) > 8:
                    oldest = next(iter(self.latest))
                    del self.latest[oldest]
                    self.orders.pop(oldest, None)
        if captured != current:
            value['analytics_refreshing'] = True
        return value

    def _refresh(self, filters, key, view_key):
        try:
            self._compute(filters, key, view_key)
        except Exception:
            with self.lock:
                self.errors[key] = 'Could not refresh usage metrics. Retry to load the latest results.'
                while len(self.errors) > 8:
                    del self.errors[next(iter(self.errors))]
        finally:
            with self.lock:
                self.pending.pop(key, None)
                self.pending_views.discard(view_key)

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
