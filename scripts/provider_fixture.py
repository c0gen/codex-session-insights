"""Build isolated mixed-provider UI/report fixtures from real ingestion queries."""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from codex_insights.ingestion import refresh
from codex_insights.providers.bridge import receive
from codex_insights.providers.setup import Setup
from codex_insights.queries import dashboard
from codex_insights.report import export_html
from codex_insights.storage import Store
from codex_insights.widget_queries import WidgetSummaries
from codex_insights.providers.allowances import read

directory = Path(sys.argv[1])
store = Store(directory / "data")
store.set_setting("timezone", "America/New_York")
now = datetime.now(timezone.utc)
ts = "2026-10-11T12:00:00Z"

def write(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")

claude = directory / "claude"
write(claude / "c.jsonl", [{"timestamp": ts, "type": "assistant", "sessionId": "same", "cwd": "C:/synthetic/project",
    "message": {"id": "m", "model": "claude-sonnet-4-6", "usage": {"input_tokens": 100, "output_tokens": 20}}}])
store.add_source(claude, "Claude Code synthetic", "claude_code")
brain = directory / "brain"
write(brain / "same/.system_generated/logs/transcript.jsonl", [{"timestamp": ts, "sessionId": "same", "cwd": "C:/synthetic/project",
    "type": "assistant", "message": {"id": "a", "model": "claude-sonnet-4-6", "content": []}}])
store.add_source(brain, "Antigravity synthetic", "antigravity")
codex = directory / "codex"
write(codex / "c.jsonl", [{"timestamp": ts, "type": "session_meta", "payload": {"id": "same", "cwd": "C:/synthetic/project"}},
    {"timestamp": ts, "type": "event_msg", "payload": {"type": "token_count", "info": {"last_token_usage": {"input_tokens": 50, "output_tokens": 10, "total_tokens": 60}}}}])
store.add_source(codex, "Codex synthetic")
refresh(store)
receive(store.directory, "claude_code", "status", {"rate_limits": {"five_hour": {"used_percentage": 0}}}, now=now)
receive(store.directory, "antigravity", "status", {"quota": {"gemini-weekly": {"remaining_fraction": .5}}}, now=now)
setup = Setup(store.directory, directory / "synthetic-home", ["synthetic-bridge"])
fixtures = {}
for provider in ("", "codex", "claude_code", "antigravity"):
    data = dashboard(store, {"provider": provider})
    data.update(demo=True, exporter=False, job={"running": False, "message": "", "error": None, "progress": {}},
                provider_allowances=read(store.directory), provider_setup=setup.states())
    fixtures[provider] = data
(directory / "dashboard-fixtures.json").write_text(json.dumps(fixtures), encoding="utf-8")
widget = WidgetSummaries(store).read()
widget.update(job=fixtures[""]["job"], desktop={"available": True, "preferences": {"metrics": ["tokens", "cost"], "show_usage_remaining": True}},
              provider_allowances=read(store.directory))
(directory / "widget-fixture.json").write_text(json.dumps(widget), encoding="utf-8")
export_html(fixtures[""], directory / "providers-report.html")
print(directory)
