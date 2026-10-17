import assert from 'node:assert/strict';
import { build } from '../frontend/node_modules/esbuild/lib/main.js';
import { metricFixture } from './metric-interface-fixture.mjs';
import { coverageFixture } from './dashboard-fixture.mjs';

async function moduleAt(path) {
  const result = await build({entryPoints: [path], bundle: true, format: 'esm', write: false});
  return import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
}
const { equivalentSnapshot, convertTokens } = await moduleAt('frontend/src/text-equivalents-data.ts');
const { textEquivalents } = await moduleAt('frontend/src/text-equivalents.ts');
const { usageMetrics } = await moduleAt('frontend/src/usage-metrics.ts');
const data = metricFixture(); data.demo = false;
const indexed = (total_tokens, state = 'complete', sessions = 1) => ({total_tokens, state, sessions});
data.indexed_token_totals = {codex: indexed(500), claude_code: indexed(20), antigravity: indexed(30)};
data.account_token_total = {total_tokens: 1000, accounts: 1, reported_accounts: 1, identity_complete: true, stale: false};
const original = JSON.stringify(data);
assert.deepEqual(equivalentSnapshot(data, 'total').values, convertTokens(1050));
assert.deepEqual(equivalentSnapshot(data, 'output').values, convertTokens(20));
assert.equal(JSON.stringify(data), original);
data.filters = {...data.filters, range: 'today', provider: 'claude_code'};
data.summary.total_tokens = 3;
assert.equal(equivalentSnapshot(data, 'total').tokens, 1050);
assert.match(textEquivalents(data, 'total'), /independent of dashboard filters/);
data.account_token_total.total_tokens = 2000;
assert.deepEqual(equivalentSnapshot(data, 'total').values, convertTokens(2050));
assert.equal(equivalentSnapshot(data, 'output').tokens, 20);
data.account_token_total.total_tokens = 0;
assert.equal(equivalentSnapshot(data, 'total').tokens, 50);
data.account_token_total.total_tokens = null;
assert.equal(equivalentSnapshot(data, 'total').tokens, 550);
assert.match(equivalentSnapshot(data, 'total').detail, /Indexed Codex fallback/);
Object.assign(data.account_token_total, {total_tokens: 1000, identity_complete: false, stale: true});
assert.equal(equivalentSnapshot(data, 'total').partial, true);
assert.equal(equivalentSnapshot(data, 'total').stale, true);
for (const mode of ['demo', 'readonly', 'exporter']) {
  data[mode] = true;
  assert.equal(equivalentSnapshot(data, 'total').tokens, 3);
  data[mode] = false;
}
data.readonly = true; data.coverage = coverageFixture('unavailable');
assert.equal(equivalentSnapshot(data, 'total').values, null);
assert.match(textEquivalents(data, 'total'), /Token counters unavailable/);
assert.doesNotMatch(textEquivalents(data, 'total'), />0<\/strong>/);
assert.match(usageMetrics(data), /Cached-token counters unavailable/);
assert.doesNotMatch(usageMetrics(data), /\$0.00|No cached reads/);
data.coverage = coverageFixture('partial');
assert.match(textEquivalents(data, 'total'), /recorded subtotal only/);
assert.match(usageMetrics(data), /Partial counter coverage/);
data.coverage = coverageFixture();
data.summary.total_tokens = 0; data.summary.output_tokens = 0;
Object.assign(data.usage_metrics, {cache_discount_usd: 0, cache_discount_total_tokens: 0, cache_discount_priced_tokens: 0});
assert.equal(equivalentSnapshot(data, 'total').tokens, 0);
assert.match(usageMetrics(data), /\$0.00/);
data.coverage.tokens.metrics.output.state = 'unavailable';
assert.equal(equivalentSnapshot(data, 'output').values, null);
assert.equal(equivalentSnapshot(data, 'total').tokens, 0);
console.log('Dashboard data checks passed: combined equivalents, output basis, filter independence, polling inputs, zero/fallback/partial/stale and unavailable counters.');
