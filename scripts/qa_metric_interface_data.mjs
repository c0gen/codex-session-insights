import assert from 'node:assert/strict';
import { build } from '../frontend/node_modules/esbuild/lib/main.js';
import { metricFixture } from './metric-interface-fixture.mjs';
async function moduleAt(path) {
  const result = await build({ entryPoints: [path], bundle: true, format: 'esm', write: false });
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
}
const { sessionDays, sessionRange } = await moduleAt('frontend/src/daily-sessions-data.ts');
const { usageMetrics, discountAmount } = await moduleAt('frontend/src/usage-metrics.ts');
const { costCard } = await moduleAt('frontend/src/components.ts');
const { usage } = await moduleAt('frontend/src/views/usage.ts');
const claude = metricFixture();
claude.filters.provider = 'claude_code';
claude.settings.assumed_fast_percent = 75;
claude.tiers = [{ name: 'Not logged', tokens: 120, responses: 1 }];
assert.match(costCard(claude), /Standard\/global where unlogged/);
assert.doesNotMatch(costCard(claude), /75% Fast assumed/);
assert.match(usage(claude, 'cost'), /https:\/\/platform\.claude\.com\/docs\/en\/about-claude\/pricing/);
assert.match(usage(claude, 'cost'), /Standard\/global assumed/);
claude.filters.provider = 'codex';
assert.match(costCard(claude), /Codex: 75% Fast assumed where unlogged/);
let fixture = metricFixture();
const original = JSON.stringify(fixture);
assert.deepEqual(sessionDays(fixture, 0).map(row => [row.day, row.chats, row.subagents, row.system_agents]), [
  ['2026-03-07', 4, 2, 1], ['2026-03-08', 0, 0, 0], ['2026-03-09', 1, 0, 3], ['2026-03-10', 0, 0, 0],
]);
assert.match(usageMetrics(fixture), /Priced subtotal only/);
// The card states coverage briefly; exact token counts move to the help text.
assert.match(usageMetrics(fixture), /50% of cached tokens priced/);
assert.match(usageMetrics(fixture), /Priced cached tokens: 25 of 50\./);
assert.equal(JSON.stringify(fixture), original);
for (const [start, end, length] of [['2024-02-28', '2024-03-01', 3], ['2026-10-31', '2026-11-03', 4], ['0001-01-01', '9999-12-31', 3652059]]) {
  fixture.date_bounds = { start, end };
  assert.equal(sessionRange(fixture).length, length);
  assert.equal(sessionDays(fixture, 0).length, Math.min(length, 90));
}
fixture.date_bounds = { start: null, end: '2026-03-10' };
assert.deepEqual(sessionDays(fixture, 0), []);
fixture = metricFixture(); delete fixture.daily_sessions; delete fixture.usage_metrics;
assert.deepEqual(sessionDays(fixture, 0), []);
assert.equal((usageMetrics(fixture).match(/class="usage-metric-value">Unavailable/g) || []).length, 3);
fixture = metricFixture();
Object.assign(fixture.usage_metrics, { cache_discount_usd: 0, cache_discount_priced_tokens: 0, cache_discount_total_tokens: 0, cache_discount_coverage_percent: null, cache_reuse_percent: 0, reasoning_share_percent: 0 });
assert.match(usageMetrics(fixture), /\$0.00/); assert.match(usageMetrics(fixture), /not applicable/);
assert.equal((usageMetrics(fixture).match(/class="usage-metric-value">0%/g) || []).length, 2);
Object.assign(fixture.usage_metrics, { cache_discount_usd: null, cache_discount_total_tokens: 50, cache_reuse_percent: null, reasoning_share_percent: null });
assert.match(usageMetrics(fixture), /No applicable cache prices/);
Object.assign(fixture.usage_metrics, { cache_discount_usd: -0.0000000001, cache_discount_priced_tokens: 50, cache_discount_coverage_percent: 100 });
assert.match(usageMetrics(fixture), /Estimated surcharge/);
assert.match(usageMetrics(fixture), /Exact signed difference: -1e-10 USD/);
for (const value of [0.0000000001, 0.000001, 0.0001, 0.001, 0.009, -0.001]) assert.notEqual(discountAmount(value), '$0.00');
assert.equal(discountAmount(-1.25), '−$1.25');
console.log('PASS metric interface data: sparse/zero days, leap/DST dates, bounded long ranges, immutable snapshots, missing fields, zero/null ratios, coverage, tiny and signed amounts.');
