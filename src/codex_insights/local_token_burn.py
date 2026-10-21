"""Five-minute token and API-dollar rates from reconciled local usage records."""
import math
import json
import sqlite3
from copy import deepcopy
import threading
import time
from datetime import datetime, timezone

from .burn_rates import empty_estimate
from .burn_coverage import evaluate, describe, reason


def empty_local_rates(updated_at=None, **state):
    if 'coverage' in state:
        state['indexing'] = indexing_state(state['coverage'])
    return {kind: {**empty_estimate(updated_at), **state}
            for kind in ("token_burn_rate", "cost_burn_rate")}


def indexing_state(coverage):
    return {'live_checked_at': coverage.get('checked_at'),
            'live_pending_files': coverage.get('live_pending_files', 0),
            'historical_pending_files': coverage.get('historical_pending_files', 0)}


def cost_estimate(common, total, priced_tokens, cost, window_seconds):
    """Reuse projected API costs; unpriced usage is never reported as free."""
    result = {**common, "value": cost * 60 / window_seconds,
              "priced_tokens": priced_tokens, "total_tokens": total}
    if priced_tokens < total:
        result["partial"] = True
        coverage = deepcopy(result.get("coverage", {"state": "partial", "checked_at": None, "reasons": []}))
        coverage["state"] = "partial"
        coverage["reasons"].append(reason("unpriced_usage", count=total - priced_tokens))
        result["coverage"] = coverage
        result["detail"] = describe(coverage)
        if not priced_tokens:
            result.update(value=None, status="unavailable")
    return result


def stale_estimate(rate, coverage, detail):
    coverage = deepcopy(coverage)
    coverage['reasons'].extend(r for r in rate.get('coverage', {}).get('reasons', [])
                               if r['code'] == 'unpriced_usage')
    partial = bool(coverage['reasons'])
    coverage['state'] = 'partial' if partial else 'complete'
    return {**deepcopy(rate), 'status': 'stale', 'coverage': coverage,
            'partial': partial, 'detail': detail, 'indexing': indexing_state(coverage)}


class LocalTokenBurn:
    """Reads the existing index; never polls accounts or samples lifetime totals."""
    window_seconds = 300
    stale_seconds = 60  # Twice the indexer's existing 30-second fallback interval.

    def __init__(self, store, *, allowed=True, clock=time.time):
        self.store, self.allowed, self.clock = store, allowed, clock
        self.lock = threading.RLock()
        self.sources = self.key = None
        self.value = None
        self.coverage_key = self.coverage_value = None
        self.coverage_expires = 0
        self.coverage_clock = float('-inf')

    def decorate(self, snapshot):
        return {**snapshot, **self.read_rates()}

    def read(self):
        return self.read_rates()["token_burn_rate"]

    def read_rates(self):
        with self.lock:
            try:
                return self._read_rates()
            except sqlite3.DatabaseError:
                coverage = {'state': 'partial', 'checked_at': None, 'reasons': [reason('index_error')]}
                state = dict(coverage=coverage, partial=True,
                             detail='Local index unavailable. Open Sources or startup diagnostics for recovery.')
                if self.value:
                    return {kind: stale_estimate(rate, coverage, state['detail']) for kind, rate in self.value.items()}
                return empty_local_rates(**state)

    def _read_rates(self):
        if not self.allowed:
            return empty_local_rates()
        with self.lock, self.store.connect() as db:
            # The source health, revision and records must describe one index snapshot.
            db.execute("BEGIN")
            from .projection_state import status
            if not status(db)['readable']:
                return empty_local_rates(coverage={'state': 'partial', 'checked_at': None,
                    'reasons': [reason('coverage_unverified')]}, partial=True,
                    detail='Updating usage index. Verifying the accepted configuration.')
            sources = db.execute("""SELECT id,updated,status FROM sources s WHERE kind='folder' AND enabled=1 AND provider='codex'
                AND NOT (status='Offline' AND updated IS NULL
                    AND NOT EXISTS(SELECT 1 FROM files f WHERE f.source_id=s.id))
                ORDER BY id""").fetchall()
            # An optional folder that has never existed (e.g. archived_sessions)
            # has no indexed usage and must not block the active local sources.
            ids = tuple(row["id"] for row in sources)
            if ids != self.sources:
                self.sources, self.key, self.value = ids, None, None
            if not sources:
                return empty_local_rates()
            at = self.clock()
            now = math.floor(at)
            ready = any(row["status"] == "Ready" for row in sources)
            live = getattr(self.store, 'live_paths', None)
            health_revision = db.execute('SELECT revision FROM coverage_state WHERE id=1').fetchone()[0]
            metadata_revision = db.execute('SELECT revision FROM performance_state WHERE id=1').fetchone()[0]
            coverage_key = (health_revision, metadata_revision, tuple(live.pending()) if live else (), ids)
            if coverage_key != self.coverage_key or at >= self.coverage_expires or at < self.coverage_clock:
                self.coverage_value = evaluate(db, sources, at, self.window_seconds, self.stale_seconds, live)
                self.coverage_expires = self.coverage_value[0].pop('_expires_at', at + 1)
                self.coverage_key = coverage_key
            self.coverage_clock = at
            coverage, fresh = self.coverage_value
            updated = coverage['checked_at']
            revision = db.execute("SELECT value FROM settings WHERE key='data_revision'").fetchone()
            partial = coverage['state'] != 'complete'
            key = (now, updated, revision[0] if revision else None, json.dumps(coverage, sort_keys=True), ready)
            if key != self.key:
                cutoff = datetime.fromtimestamp(now - self.window_seconds, timezone.utc).isoformat()
                end = datetime.fromtimestamp(now, timezone.utc).isoformat()
                total, count, cost, priced_tokens = db.execute("""SELECT
                    COALESCE(SUM(r.total),0),COUNT(*),
                    COALESCE(SUM(CASE WHEN r.priced=1 AND r.cost IS NOT NULL THEN r.cost ELSE 0 END),0),
                    COALESCE(SUM(CASE WHEN r.priced=1 AND r.cost IS NOT NULL THEN r.total ELSE 0 END),0)
                    FROM records r
                    JOIN sources s ON s.id=r.source_id
                    WHERE r.kind='usage' AND r.ts>? AND r.ts<=?
                    AND s.kind='folder' AND s.enabled=1 AND r.provider='codex'""", (cutoff, end)).fetchone()
                # A failed historical file or a long scan does not invalidate
                # successfully indexed events. Disclose incomplete coverage.
                # Without a fresh scan OR recent events, never invent an idle zero.
                if not ready or not (any(fresh) or count):
                    detail = ("Waiting for a fresh local scan to finish."
                              if ready else "Local session folders are offline. Check Sources.")
                    if self.value:
                        return {kind: stale_estimate(rate, coverage, detail)
                                for kind, rate in self.value.items()}
                    return empty_local_rates(updated, detail=detail, coverage=coverage,
                                             status="collecting" if ready else "unavailable")
                common = {"status": "available", "observed_seconds": self.window_seconds,
                          "updated_at": updated, "coverage": coverage,
                          'indexing': indexing_state(coverage)}
                if partial:
                    common.update(partial=True, detail=describe(coverage))
                self.value = {
                    "token_burn_rate": {**common, "value": total * 60 / self.window_seconds},
                    "cost_burn_rate": cost_estimate(common, total, priced_tokens, cost, self.window_seconds),
                }
                self.key = key
            return deepcopy(self.value)
