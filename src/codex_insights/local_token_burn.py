"""Five-minute token and API-dollar rates from reconciled local usage records."""
import math
import threading
import time
from datetime import datetime, timezone

from .burn_rates import empty_estimate
from .codec import timestamp


def empty_local_rates(updated_at=None, **state):
    return {kind: {**empty_estimate(updated_at), **state}
            for kind in ("token_burn_rate", "cost_burn_rate")}


def cost_estimate(common, total, priced_tokens, cost, window_seconds):
    """Reuse projected API costs; unpriced usage is never reported as free."""
    result = {**common, "value": cost * 60 / window_seconds,
              "priced_tokens": priced_tokens, "total_tokens": total}
    if priced_tokens < total:
        result["partial"] = True
        if not priced_tokens:
            result.update(value=None, status="unavailable")
    return result


class LocalTokenBurn:
    """Reads the existing index; never polls accounts or samples lifetime totals."""
    window_seconds = 300
    stale_seconds = 60  # Twice the indexer's existing 30-second fallback interval.

    def __init__(self, store, *, allowed=True, clock=time.time):
        self.store, self.allowed, self.clock = store, allowed, clock
        self.lock = threading.Lock()
        self.sources = self.key = None
        self.value = None

    def decorate(self, snapshot):
        return {**snapshot, **self.read_rates()}

    def read(self):
        return self.read_rates()["token_burn_rate"]

    def read_rates(self):
        if not self.allowed:
            return empty_local_rates()
        with self.lock, self.store.connect() as db:
            # The source health, revision and records must describe one index snapshot.
            db.execute("BEGIN")
            sources = db.execute("""SELECT id,updated,status,
                EXISTS(SELECT 1 FROM file_failures f WHERE f.source_id=s.id) AS failed
                FROM sources s WHERE kind='folder' AND enabled=1 AND provider='codex'
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
            updates = [timestamp(row["updated"]) for row in sources]
            ready = any(row["status"] == "Ready" for row in sources)
            fresh = [row["status"] == "Ready" and update is not None
                     and 0 <= at - update.timestamp() <= self.stale_seconds
                     for row, update in zip(sources, updates)]
            updated = max((update.timestamp() for update in updates if update), default=None)
            revision = db.execute("SELECT value FROM settings WHERE key='data_revision'").fetchone()
            partial = not all(fresh) or any(row["failed"] for row in sources)
            key = (now, updated, revision[0] if revision else None, tuple(fresh), partial, ready)
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
                        return {kind: {**rate, "status": "stale", "detail": detail}
                                for kind, rate in self.value.items()}
                    return empty_local_rates(updated, detail=detail,
                                             status="collecting" if ready else "unavailable")
                common = {"status": "available", "observed_seconds": self.window_seconds,
                          "updated_at": updated}
                if partial:
                    common.update(partial=True, detail="Some local sources have indexing errors or are not up to date. "
                                  "This rate uses the indexed records and may be incomplete. Check Sources.")
                self.value = {
                    "token_burn_rate": {**common, "value": total * 60 / self.window_seconds},
                    "cost_burn_rate": cost_estimate(common, total, priced_tokens, cost, self.window_seconds),
                }
                self.key = key
            return {kind: dict(rate) for kind, rate in self.value.items()}
