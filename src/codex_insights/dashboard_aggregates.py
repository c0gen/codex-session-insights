"""Small revision-scoped aggregate cache shared by dashboard views."""
from collections import OrderedDict
from copy import deepcopy
import threading


class SharedAggregates:
    def __init__(self, limit=8):
        self.lock, self.values, self.limit = threading.RLock(), OrderedDict(), limit

    def get(self, identity, name, calculate):
        key = (identity, name)
        with self.lock:
            if key in self.values:
                self.values.move_to_end(key)
                return deepcopy(self.values[key])
            value = calculate()
            self.values[key] = deepcopy(value)
            while len(self.values) > self.limit:
                self.values.popitem(last=False)
            return value


def shared(store):
    # Store creation is serialized by the application; this lazy fallback also
    # serves the synchronous report API without requiring Engine.start().
    if not hasattr(store, '_dashboard_aggregates'):
        store._dashboard_aggregates = SharedAggregates(32)
    return store._dashboard_aggregates
