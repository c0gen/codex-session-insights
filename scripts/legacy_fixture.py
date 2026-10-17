"""Offline UI fixtures for retained legacy history after collection retirement."""
import json
import sys
from pathlib import Path

from codex_insights.codec import digest
from codex_insights.ingestion import refresh
from codex_insights.projection import project_segments
from codex_insights.providers.legacy.accounting import facts
from codex_insights.providers.legacy.wire import message
from codex_insights.queries import dashboard
from codex_insights.report import export_html
from codex_insights.storage import Store
from codex_insights.widget_queries import WidgetSummaries

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from legacy_fixtures import SID, archive, field


directory = Path(sys.argv[1]).resolve()
root = directory / 'original-antigravity'
(root / 'conversations').mkdir(parents=True, exist_ok=True)
payload = archive(writes=None)
missing = message(archive(reads=None, writes=None, request='second-request'))[3][0]
payload += field(3, missing)
original = root / 'conversations' / (SID + '.pb')
original.write_bytes(b'Synthetic archive placeholder: collection must not read or modify this file.')
store = Store(directory / 'data')
store.set_setting('timezone', 'America/New_York')
sid = next((source['id'] for source in store.sources()
            if source['root'] == str(root) and source['format'] == 'antigravity_legacy'), None)
if sid is None:
    sid = store.add_source(root, 'Retained Antigravity synthetic', 'antigravity',
                           profile_location=directory / 'private-profile-location')
# Seed an already accepted synthetic fact. Never enable the retired collector,
# unlock a profile, or decrypt an archive to prepare browser fixtures.
fact = facts(message(payload), SID)
fact.update(byte_count=len(payload), prefix_hash=digest(['synthetic retained history']), proofs={})
with store.connect() as db:
    db.execute("UPDATE sources SET format='antigravity_legacy' WHERE id=?", (sid,))
    store.put_candidate(db, sid, fact, 1002)
    store.choose_canonical(db, fact['segment_id'])
    project_segments(store, db, [fact['segment_id']])
before = dashboard(store)['summary']
original_bytes = original.read_bytes()
refresh(store)
assert dashboard(store)['summary'] == before
assert store.sources()[0]['status'] == 'Collection disabled'
assert original.read_bytes() == original_bytes
fixtures = {}
for provider in ('','antigravity','codex'):
    data = dashboard(store, {'provider':provider})
    data.update(job={'running':False,'message':'','error':None,'progress':{}},exporter=False)
    fixtures[provider] = data
(directory / 'dashboard-fixtures.json').write_text(json.dumps(fixtures),encoding='utf-8')
widget = WidgetSummaries(store).read()
widget.update(job=fixtures['']['job'],desktop={'available':True,'preferences':{'metrics':['tokens','cost']}})
(directory / 'widget-fixture.json').write_text(json.dumps(widget),encoding='utf-8')
export_html(fixtures[''],directory / 'legacy-report.html')
print(directory)
