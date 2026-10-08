"""Synthetic, reproducible demo data; contains no real user sessions."""
import math
import random
from datetime import datetime, timedelta, timezone

from .accounting.token_accounting import empty_usage
from .codec import digest
from .projection import project_segments


def seed_demo(store):
    if store.setting("demo", False):
        return
    rng = random.Random(4721)
    start = datetime(2026, 5, 24, tzinfo=timezone.utc)
    projects = ["spectrum-studio", "paperwork", "little-planets", "codex-insights"]
    sources = [("demo-windows", "Windows PC"), ("demo-mac", "Intel Mac")]
    with store.lock, store.connect() as db:
        for sid, label in sources:
            db.execute("INSERT OR REPLACE INTO sources(id,label,kind,status) VALUES(?,?,'folder',?)", (sid,label,"Live" if sid.endswith("windows") else "Imported"))
        segments = []
        for day in range(138):
            if rng.random() < .11:
                continue
            volume = (1.3 + day / 15) * (1 + rng.random() * 1.8)
            if day == 123:
                volume *= 3.1
            for chat in range(rng.randint(5, 13)):
                t = start + timedelta(days=day, hours=14 + chat)
                sid = f"demo-{day}-{chat}"
                model = "gpt-5.3-codex" if day < 80 else "gpt-5.6-sol"
                input_count = int(volume * rng.randint(65000, 160000))
                output_count = rng.randint(15000, 58000)
                usage = {**empty_usage(), "input_tokens": input_count, "cached_input_tokens": int(input_count*.94),
                         "output_tokens": output_count, "reasoning_output_tokens": int(output_count*.35), "total_tokens": input_count+output_count}
                segment = digest([sid, t])
                fact = {"id": sid, "segment_id": segment, "metadata_timestamp": t, "project_id": "https://github.com/example/"+projects[chat%4],
                    "project_label": projects[chat%4], "session_source": "top_level", "parent_session_id": None, "spawn_timestamp": t,
                    "history_mode": None, "history_base": None, "raw_token_trace": [{"timestamp": t+timedelta(minutes=5),
                        "ordinal": 3,"end_byte_offset":1000, "cumulative_usage":usage,"last_usage":usage,"model":model,
                        "effort":"high","service_tier":None,"model_context_window":272000}],
                    "messages": [{"timestamp": t,"role":"user","signature":digest([sid,"user"]),"model":model}],
                    "change_events": [{"timestamp":t+timedelta(minutes=1),"resolved_at":t+timedelta(minutes=2),"call_id":sid+"-edit","index":0,
                        "digest":digest(sid),"added":rng.randint(50,450),"removed":rng.randint(5,130),"files":["file:"+digest(sid)],
                        "result_files":["file:"+digest(sid)],"supported":True,"unknown_size":False,"outcome":"confirmed","direct":True}],
                    "activity":[t,t+timedelta(minutes=5)],"tools":{"exec_command":20},"contexts":[],"prefix_hash":digest([sid,"prefix"]),
                    "byte_count":1000,"record_count":4,"boundaries":[],"record_boundaries":[],"proofs":{"1000":digest([sid,"prefix"])},"last_event_ordinal":3,"parse_errors":0}
                store.put_candidate(db, sources[chat%2][0], fact)
                store.choose_canonical(db, segment)
                segments.append(segment)
        project_segments(store, db, segments)
    store.set_setting("demo", True)
    store.set_setting("data_revision", 1)
