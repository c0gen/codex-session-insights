"""Bounded analytics cache and credential-free last overview for startup."""
from collections import OrderedDict
from copy import deepcopy
from concurrent.futures import Future, ThreadPoolExecutor, wait
import json
import os
from pathlib import Path
import sqlite3
import threading
import time

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
                'coverage', 'settings', 'filters', 'usage_metrics', 'daily_sessions', 'source_states', 'indexed_token_totals', 'analytics_context')
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
    # Indexing changes the snapshot identity continuously. A background view
    # recomputes at most this often, and never spends over a third of its time
    # computing; clients keep the previous result, marked as refreshing.
    MIN_INTERVAL = 2

    def __init__(self, store, min_interval=MIN_INTERVAL, clock=time.monotonic):
        self.store, self.values, self.lock = store, OrderedDict(), threading.Lock()
        self.snapshot = OverviewSnapshot(store.directory)
        self.latest, self.pending, self.errors = {}, {}, {}
        self.flights = {}
        self.pending_views = set()
        self.orders, self.sequence, self.snapshot_order = {}, 0, None
        self.min_interval, self.clock = min_interval, clock
        self.finished, self.durations = {}, {}
        # Advances whenever a newer result is published, so clients poll a number.
        self.generation = 0
        self.closing = threading.Event()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='insights-analytics')

    def _allowed(self, view_key):
        finished = self.finished.get(view_key)
        if not self.min_interval or finished is None:
            return True
        return self.clock() >= finished + max(self.min_interval, 2 * self.durations.get(view_key, 0))

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
            if background and previous and not retry:
                # Requests the user made themselves (retry) are never throttled.
                if view_key not in self.pending_views and not self.closing.is_set() and (retry or self._allowed(view_key)):
                    self.pending_views.add(view_key)
                    self.pending[key] = self.executor.submit(self._refresh, filters, key, view_key)
                return {**deepcopy(previous), 'analytics_refreshing': True}
        return self._singleflight(filters, key, view_key)

    def _singleflight(self, filters, key, view_key):
        with self.lock:
            future = self.flights.get(key)
            owner = future is None
            if owner:
                future = self.flights[key] = Future()
        if not owner:
            return deepcopy(future.result())
        try:
            value = self._compute(filters, key, view_key)
            future.set_result(value)
            return value
        except BaseException as error:
            future.set_exception(error)
            raise
        finally:
            with self.lock:
                self.flights.pop(key, None)

    def _compute(self, filters, key, view_key):
        from .queries import dashboard
        with self.lock:
            self.sequence += 1
            sequence = self.sequence
        started = self.clock()
        result = dashboard(self.store, filters)
        captured = result.snapshot_key
        value = dict(result)
        current = self.key(filters)
        order = (*captured[1:4], sequence)
        captured_view = (captured[0], json.dumps(filters, sort_keys=True))
        with self.lock:
            self.finished[captured_view] = self.clock()
            self.durations[captured_view] = self.finished[captured_view] - started
        if captured[0] == current[0]:
            with self.lock:
                self.values[captured] = deepcopy(value)
                if order > self.orders.get(captured_view, (-1,)):
                    self.generation += 1
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
            if not self.closing.is_set():
                self._singleflight(filters, key, view_key)
        except Exception:
            # A query interrupted by shutdown is not a result clients should see.
            if not self.closing.is_set():
                with self.lock:
                    self.errors[key] = 'Could not refresh usage metrics. Retry to load the latest results.'
                    while len(self.errors) > 8:
                        del self.errors[next(iter(self.errors))]
                    self.generation += 1  # Clients must request again to see the failure.
        finally:
            with self.lock:
                self.pending.pop(key, None)
                self.pending_views.discard(view_key)

    def begin_close(self):
        """Stop scheduling and abort a running aggregate without waiting for it."""
        self.closing.set()
        readers = getattr(self.store, 'readers', None)
        if readers is not None:
            readers.interrupt()

    def close(self, timeout=None):
        self.begin_close()
        with self.lock:
            running = list(self.pending.values())
        self.executor.shutdown(wait=False, cancel_futures=True)
        wait(running, timeout=timeout)
