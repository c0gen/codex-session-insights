"""Revision-cached widget summaries; never scan files or build dashboard charts."""
from .buckets import current as current_buckets
import json
import threading
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .queries import filter_clause
from .summary_queries import query_summary


class WidgetSummaries:
    def __init__(self, store, clock=None):
        self.store = store
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.lock = threading.Lock()
        self.key = None
        self.value = None

    def read(self):
        with self.lock, self.store.connect() as db:
            # Both columns and their revision describe the same SQLite snapshot.
            db.execute("BEGIN")
            from .projection_state import status
            if not status(db)['readable']:
                raise ValueError('Updating usage index. Waiting for the accepted configuration to be verified.')
            settings = {row[0]: json.loads(row[1]) for row in db.execute(
                "SELECT key,value FROM settings WHERE key IN ('timezone','data_revision','bucket_version')")}
            zone_name = settings.get("timezone", "America/New_York")
            now = self.clock()
            today = now.astimezone(ZoneInfo(zone_name)).date()
            revision = settings.get("data_revision", 0)
            from .providers.history_coverage import source_states
            states = source_states(db)
            key = (revision, zone_name, today, settings.get("bucket_version"), tuple(sorted(states.items())))
            if key != self.key:
                table = "metric_buckets" if current_buckets(settings.get("bucket_version")) else "records"
                value = {"timezone": zone_name, "date": today.isoformat(), "revision": revision,
                         "generated_at": now.isoformat(), 'source_states': states}
                for name, selected in (("today", "today"), ("all_time", "all")):
                    where, params, end = filter_clause({"range": selected}, ZoneInfo(zone_name), today)
                    value[name] = query_summary(db, table, where, params, end)
                    from .providers.schema import coverage
                    metric_coverage = coverage(db, table, where, params)
                    value[name]["token_coverage"] = metric_coverage["state"]
                    value[name]['metric_coverage'] = metric_coverage['metrics']
                self.value, self.key = value, key
            return dict(self.value)
