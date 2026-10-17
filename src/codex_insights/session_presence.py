"""Compact day/model presence recovered from portable canonical session facts."""
from .codec import unpack


class SessionPresence:
    def __init__(self, db):
        self.db = db
        self.created = {}

    def days(self, fact, zone):
        sid = fact["id"]
        if sid not in self.created:
            self.created[sid] = min(unpack(row[0])["metadata_timestamp"] for row in self.db.execute(
                "SELECT fact FROM canonical WHERE session_id=?", (sid,)))
        # Older portable/demo facts may lack contexts but retain per-event models.
        contexts = sorted(
            (item for field in ("contexts", "messages", "change_events", "raw_token_trace")
             for item in fact.get(field, []) if item.get("timestamp") and item.get("model")),
            key=lambda item: item["timestamp"],
        )
        index, model = 0, "Unknown"
        days = {}
        for timestamp in sorted(fact.get("activity", [])):
            while index < len(contexts) and contexts[index]["timestamp"] <= timestamp:
                model = contexts[index]["model"]
                index += 1
            if timestamp >= self.created[sid]:
                days[(timestamp.astimezone(zone).date(), model)] = timestamp
        return days
