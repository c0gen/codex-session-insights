import assert from 'node:assert/strict';
import { build } from '../frontend/node_modules/esbuild/lib/main.js';

async function moduleFor(path) {
  const compiled = await build({ entryPoints: [path], bundle: true, format: 'esm', write: false });
  return import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString('base64')}`);
}
const { visibleWidgetProviders, renderWidgetProviders } = await moduleFor('frontend/src/widget-providers.ts');
const { limitLabel, limitState, readingAged, resetText, duration, asOfText, MAX_READING_AGE } = await moduleFor('frontend/src/claude-limits.ts');
const { allowanceTone, widgetTimestamp } = await moduleFor('frontend/src/widget-presentation.ts');
const now = 1791996780; // 2026-10-14T16:53:00Z, a Wednesday
const bucket = { id: 'five_hour', unit: 'percent', remaining_percent: 0, used: null, limit: null, resets_at: now + 3600 };
const profile = { provider: 'claude_code', profile: 'local', received_at: now, buckets: [bucket] };
assert.deepEqual(visibleWidgetProviders(undefined, now), []);
for (const bad of [null, {}, { ...profile, received_at: null }, { ...profile, received_at: now + 1 },
  { ...profile, received_at: now - MAX_READING_AGE }, { ...profile, buckets: [] }, { ...profile, buckets: [null] },
  { ...profile, buckets: [{ ...bucket, remaining_percent: null }] },
  { ...profile, buckets: [{ ...bucket, remaining_percent: NaN }] },
  { ...profile, buckets: [{ ...bucket, remaining_percent: Infinity }] },
  { ...profile, buckets: [{ ...bucket, remaining_percent: 101 }] },
  { ...profile, buckets: [{ ...bucket, remaining_percent: -1 }] }]) {
  assert.deepEqual(visibleWidgetProviders([bad], now), [], JSON.stringify(bad));
}
assert.equal(visibleWidgetProviders([profile], now)[0].buckets[0].remaining_percent, 0);
// Older readings stay visible, labeled by age, instead of disappearing after five minutes.
assert.equal(visibleWidgetProviders([{ ...profile, received_at: now - 300 }], now).length, 1);
const dollars = { ...bucket, unit: 'usd', remaining_percent: null, used: 0, limit: 10 };
assert.equal(visibleWidgetProviders([{ ...profile, buckets: [dollars] }], now).length, 1);
assert.equal(visibleWidgetProviders([{ ...profile, buckets: [{ ...dollars, used: null }] }], now).length, 0);
const mixed = { ...profile, status: 'stale', buckets: [{ ...bucket, stale: true }, { ...bucket, id: 'seven_day' }, null] };
assert.deepEqual(visibleWidgetProviders([mixed], now)[0].buckets.map(b => b.id), ['five_hour', 'seven_day']);
assert.equal(mixed.buckets.length, 3, 'filtering does not modify the shared snapshot');
const fresh = renderWidgetProviders([profile], 'America/New_York', now);
assert.match(fresh, /0% · Exhausted/);
assert.match(fresh, /5-hour limit/);
// Compact surfaces count down like Codex windows; the tooltip keeps the exact reset time.
assert.match(fresh, />Resets in 1h 0m</);
assert.match(fresh, /data-tooltip="Resets Wed, Oct 14, 1:53 PM · in 1h 0m · America\/New_York"/);
assert.match(fresh, /As of 12:53 PM/);
assert.doesNotMatch(fresh, /data-stale/);
assert.match(renderWidgetProviders([{ ...profile, buckets: [dollars] }], 'UTC', now), /\$0\.00/);
const stale = renderWidgetProviders([{ ...profile, received_at: now - 600, buckets: [{ ...bucket, remaining_percent: 40, stale: true }] }], 'UTC', now);
assert.match(stale, /data-stale/);
assert.match(stale, /40% remaining/);
assert.match(stale, /As of 4:43 PM/);
const passed = renderWidgetProviders([{ ...profile, buckets: [{ ...bucket, remaining_percent: 40, resets_at: now - 60 }] }], 'UTC', now);
assert.match(passed, /Awaiting reading/);
assert.match(passed, /Reset 4:52 PM · awaiting new reading/);
assert.doesNotMatch(passed, /role="meter"/);
assert.doesNotMatch(passed, /40%/);
for (const [kind, label] of [['session', '5-hour limit'], ['five_hour', '5-hour limit'], ['weekly_all', 'Weekly limit'],
  ['seven_day', 'Weekly limit'], ['spend_limit', 'Spend limit'], ['future_meter', 'future_meter'],
  ['gemini-5h', '5-hour · Gemini'], ['3p-weekly', 'Weekly · Third-party models']]) {
  assert.equal(limitLabel({ id: kind, kind }), label);
}
assert.equal(limitLabel({ id: 'weekly_scoped:Opus', kind: 'weekly_scoped', scope_label: 'Opus' }), 'Weekly · Opus');
assert.equal(limitLabel({ id: 'five_hour' }), '5-hour limit', 'status-line buckets classify by id');
assert.equal(limitState({ ...bucket, resets_at: now }, now), 'reset_passed');
assert.equal(limitState({ ...bucket, stale: true }, now), 'stale');
assert.equal(limitState(bucket, now), 'fresh');
assert.equal(limitState(bucket, now, true), 'stale');
assert.equal(readingAged({ received_at: now - 299 }, now), false);
assert.equal(readingAged({ received_at: now - 300 }, now), true, 'status-line readings age after five minutes');
assert.equal(readingAged({ received_at: now - 599, source: 'Claude Code /usage' }, now), false);
assert.equal(readingAged({ received_at: now - 600, source: 'Claude Code /usage' }, now), true, 'a /usage reading ages after two missed checks');
const aged = renderWidgetProviders([{ ...profile, received_at: now - 300, buckets: [{ ...bucket, remaining_percent: 40 }] }], 'UTC', now);
assert.match(aged, /data-stale/);
assert.match(aged, /data-state="stale"/);
assert.equal(duration(3600), '1h 0m');
assert.equal(duration(90000), '1d 1h');
assert.equal(duration(30), '1m');
assert.equal(resetText(now + 3600, 'America/New_York', now), 'Resets Wed, Oct 14, 1:53 PM · in 1h 0m');
assert.equal(resetText(now + 2 * 86400, 'UTC', now, true), 'Resets Fri 4:53 PM');
assert.equal(resetText(now + 30 * 86400, 'UTC', now, true), 'Resets Nov 13, 4:53 PM');
// The same instant is "today" in New York but tomorrow in UTC.
const lateNight = Date.parse('2026-10-15T02:00:00Z') / 1000;
assert.equal(resetText(lateNight, 'America/New_York', now, true), 'Resets 10:00 PM');
assert.equal(resetText(lateNight, 'UTC', now, true), 'Resets Thu 2:00 AM');
assert.equal(resetText(null, 'UTC', now), 'Reset time unavailable');
// Real /usage resets arrive a fraction of a second before the minute.
const reported = Date.parse('2026-10-15T04:49:59.808Z') / 1000;
assert.equal(resetText(reported, 'America/New_York', now), 'Resets Thu, Oct 15, 12:50 AM · in 11h 57m');
assert.equal(resetText(reported, 'America/New_York', now, true), 'Resets Thu 12:50 AM');
assert.equal(asOfText(now - 86400, 'UTC', now), 'As of Tue 4:53 PM');
for (const [value, tone] of [[null, 'unknown'], [0, 'critical'], [10, 'critical'], [10.1, 'low'], [20, 'low'], [20.1, 'healthy'], [100, 'healthy']]) {
  assert.equal(allowanceTone(value).tone, tone);
}
assert.match(widgetTimestamp(Date.parse('2026-10-14T16:53:00Z') / 1000, 'America/New_York'), /Updated 12:53 PM/);
assert.match(widgetTimestamp(null, 'UTC'), /No successful update/);

const { WidgetRefreshControls } = await moduleFor('frontend/src/widget-controls.ts');
const requests = [], waiting = new Map();
globalThis.window = { pywebview: { api: { call: async (action, args) => {
  requests.push({ action, args });
  if (args.id === 'failure') throw Error('synthetic');
  if (args.id === 'slow') await new Promise(resolve => waiting.set('slow', resolve));
  return { status: 'started' };
} } } };
const account = id => ({ id, label: id, enabled: true, allowance: { enabled: true, allowed: true, refreshing: false, last_success_at: now } });
let list = [account('one'), account('one'), account('failure'), account('slow'), { ...account('paused'), enabled: false }];
let polls = 0;
const controls = new WidgetRefreshControls(() => list, () => {}, async () => { polls++; }, () => {});
const bulk = controls.refreshAll();
await Promise.resolve(); await Promise.resolve();
assert(controls.busy() && controls.pending.has('slow'));
await controls.refresh('slow');
assert.equal(requests.filter(r => r.args.id === 'slow').length, 1);
assert.deepEqual(requests.map(r => r.args.id).sort(), ['failure', 'one', 'slow']);
waiting.get('slow')();
await bulk;
assert.equal(polls, 1);
assert(controls.errors.has('failure') && !controls.busy() && controls.pending.size === 0);
list.find(a => a.id === 'failure').allowance.last_success_at++;
controls.reconcile();
assert.equal(controls.errors.size, 0);
requests.length = 0;
list = [{ ...account('disabled'), allowance: { ...account('disabled').allowance, enabled: false } }];
await controls.refreshAll();
assert.equal(requests.length, 0);
assert.equal(polls, 2, 'disabled account fetching still allows rereading local snapshots');
console.log('Widget data checks passed: numeric zero, invalid/expired/mixed snapshots, timezone, allowance thresholds, independent refreshes, grouping and partial failures.');
