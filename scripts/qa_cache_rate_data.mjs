import assert from 'node:assert/strict';
import { build } from '../frontend/node_modules/esbuild/lib/main.js';
import { metricFixture } from './metric-interface-fixture.mjs';

async function moduleAt(path) {
  const result = await build({ entryPoints: [path], bundle: true, format: 'esm', write: false });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
}
const { cachePeriods, cacheRange, cacheStatus } = await moduleAt('frontend/src/cache-rate-data.ts');
const { usageMetrics } = await moduleAt('frontend/src/usage-metrics.ts');
export const cacheDay = (day, input_tokens, cached_tokens, extra = {}) => ({
  day, input_tokens, cached_tokens, observations: 1, input_available: 1, cached_available: 1, ...extra,
});

const data = metricFixture();
data.date_bounds = { start: '2026-10-05', end: '2026-10-11' };
data.cache_rate_timeline = [cacheDay('2026-10-05', 100, 100), cacheDay('2026-10-06', 900, 0)];
const original = JSON.stringify(data);
assert.deepEqual(cachePeriods(data, 'daily', 0).map(row => row.percent), [100, 0, null, null, null, null, null]);
assert.equal(cachePeriods(data, 'weekly', 0)[0].percent, 10);
assert.equal(JSON.stringify(data), original);
for (const [extra, status] of [
  [{input_tokens: 0, cached_tokens: 0}, 'no-input'],
  [{cached_tokens: 101}, 'invalid'], [{cached_tokens: -1}, 'invalid'],
  [{input_available: 0}, 'missing'], [{cached_available: 0}, 'missing'],
  [{observations: 0}, 'no-activity'],
]) assert.equal(cacheStatus({...data.cache_rate_timeline[0], ...extra}), status);
data.cache_rate_timeline[0].cached_available = 0;
assert.equal(cachePeriods(data, 'weekly', 0)[0].percent, null);
assert.equal(cachePeriods(data, 'weekly', 0)[0].status, 'missing');
data.cache_rate_timeline[0] = cacheDay('2026-10-05', 100, 101);
assert.equal(cachePeriods(data, 'weekly', 0)[0].status, 'invalid'); // Cannot hide an invalid day in larger weekly totals.
data.cache_rate_timeline[0] = cacheDay('2026-10-05', 0, 0);
assert.equal(cachePeriods(data, 'weekly', 0)[0].percent, 0); // Zero-input days do not invalidate known weekly input.

// Monday–Sunday weeks clip both ends; out-of-range counters cannot leak in.
data.date_bounds = {start:'2026-10-07', end:'2026-10-13'};
data.cache_rate_timeline = [cacheDay('2026-10-05', 9999, 9999), cacheDay('2026-10-07', 100, 50), cacheDay('2026-10-12', 200, 20)];
assert.deepEqual(cachePeriods(data, 'weekly', 0).map(row => [row.start, row.end, row.percent]), [
  ['2026-10-07', '2026-10-11', 50], ['2026-10-12', '2026-10-13', 10],
]);
for (const [start, end, length] of [
  ['2024-02-28','2024-03-01',3], ['2026-03-07','2026-03-10',4],
  ['2026-10-31','2026-11-03',4], ['2026-12-31','2027-01-02',3],
  ['0001-01-01','9999-12-31',3652059],
]) {
  data.date_bounds = {start, end};
  assert.equal(cacheRange(data, 'daily').length, length);
  for (const mode of ['daily','weekly']) {
    const range = cacheRange(data, mode);
    const offset = Math.floor((range.length - 1) / 90) * 90;
    assert(cachePeriods(data, mode, offset).length <= 90);
    assert.equal(cachePeriods(data, mode, offset).at(-1).end, end);
  }
}
delete data.cache_rate_timeline;
assert.deepEqual(cachePeriods(data, 'daily', 0), []);
data.cache_rate_timeline = [];
data.date_bounds = {start:null, end:'2026-10-11'};
assert.deepEqual(cachePeriods(data, 'weekly', 0), []);

data.usage_metrics.reasoning_share_basis = {reasoning_tokens:5, output_tokens:10, included_responses:1, total_responses:3};
data.usage_metrics.reasoning_share_percent = 50;
assert.match(usageMetrics(data), /Recorded subset · 1 of 3 responses/);
assert.match(usageMetrics(data), /5 reasoning tokens ÷ 10 output tokens/);
data.usage_metrics.reasoning_share_percent = 0;
data.usage_metrics.reasoning_share_basis.reasoning_tokens = 0;
assert.match(usageMetrics(data), />0%<\/strong>/);
data.usage_metrics.reasoning_share_percent = null;
data.usage_metrics.reasoning_share_basis.included_responses = 0;
assert.match(usageMetrics(data), /No responses record both reasoning and output counters/);
data.usage_metrics.reasoning_share_basis.included_responses = 1;
data.usage_metrics.reasoning_share_basis.output_tokens = 0;
assert.match(usageMetrics(data), /No output tokens in recorded responses/);
console.log('PASS cache rate data: token weighting, coverage gaps, clipped weeks, DST/leap/year dates, bounded paging, immutable snapshots and recorded reasoning basis.');
