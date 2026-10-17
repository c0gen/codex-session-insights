import assert from 'node:assert/strict';
import { build } from '../frontend/node_modules/esbuild/lib/main.js';

const compiled = await build({ entryPoints: ['frontend/src/token-kpi.ts'], bundle: true, format: 'esm', write: false });
const { tokenKpiContent } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString('base64')}`);
const data = { summary: { total_tokens: 42 }, coverage: { tokens: { state: "complete" } }, account_token_total: {
  total_tokens: 3000, accounts: 2, reported_accounts: 2,
  identity_complete: false, unresolved_connections: 2, stale: false,
} };
const initial = tokenKpiContent(data);
assert.match(initial, />42<\/strong>/);
for (const changes of [ { reported_accounts: 1 }, { identity_complete: true, unresolved_connections: 0 }, { total_tokens: 0 }, { total_tokens: null } ]) {
  Object.assign(data.account_token_total, changes);
  assert.equal(tokenKpiContent(data), initial); // Account cards own these counters.
}
data.coverage.tokens.state = "partial";
assert.match(tokenKpiContent(data), /<small>partial<\/small>/);
data.coverage.tokens.state = "unavailable";
assert.match(tokenKpiContent(data), /Token counters unavailable/);
const indexed = (total_tokens, state = 'complete', sessions = 1) => ({ total_tokens, state, sessions });
data.indexed_token_totals = { codex: indexed(42), claude_code: indexed(20), antigravity: indexed(30) };
Object.assign(data.account_token_total, { total_tokens: 1000, reported_accounts: 2, identity_complete: true, unresolved_connections: 0, stale: false });
data.coverage.tokens.state = 'complete';
assert.match(tokenKpiContent(data), />1\.05K<\/strong>/);
assert.match(tokenKpiContent(data), /Analyzed tokens in this view: 42/);
assert.doesNotMatch(tokenKpiContent(data), /Indexed Codex fallback<\/p>/);
data.summary.total_tokens = 5;
data.filters = { provider: 'claude_code', range: 'today' };
assert.match(tokenKpiContent(data), />1\.05K<\/strong>/);
assert.match(tokenKpiContent(data), /Analyzed tokens in this view: 5/);
data.account_token_total.reported_accounts = 1;
assert.match(tokenKpiContent(data), /<small>partial<\/small>/);
data.account_token_total.reported_accounts = 2;
data.account_token_total.identity_complete = false;
assert.match(tokenKpiContent(data), /duplicate connections may remain/);
assert.match(tokenKpiContent(data), /<small>partial<\/small>/);
data.account_token_total.identity_complete = true;
data.account_token_total.stale = true;
assert.match(tokenKpiContent(data), /<small>stale<\/small>/);
assert.doesNotMatch(tokenKpiContent(data), /Indexed Codex fallback<\/p>/);
data.account_token_total.total_tokens = 0;
assert.match(tokenKpiContent(data), />50<small>stale/);
data.account_token_total.total_tokens = null;
data.account_token_total.reported_accounts = 0;
assert.match(tokenKpiContent(data), />92<\/strong>/);
assert.match(tokenKpiContent(data), /Indexed Codex fallback<\/p>/);
data.indexed_token_totals.antigravity = indexed(null, 'unavailable');
assert.match(tokenKpiContent(data), />62<small>partial/);
data.indexed_token_totals.codex = indexed(null, 'unavailable');
data.indexed_token_totals.claude_code = indexed(null, 'unavailable');
assert.match(tokenKpiContent(data), /Token counters unavailable/);
data.indexed_token_totals = { codex: indexed(0), claude_code: indexed(null, 'unavailable', 0), antigravity: indexed(null, 'unavailable', 0) };
assert.match(tokenKpiContent(data), />0<\/strong>/);
for (const mode of ['demo', 'exporter', 'readonly']) {
  data[mode] = true;
  assert.match(tokenKpiContent(data), /Analyzed tokens/);
  assert.doesNotMatch(tokenKpiContent(data), /Indexed Codex fallback/);
  delete data[mode];
}
console.log('Token headline checks passed: reported plus other tools, filter independence, zero, identity coverage, partial/stale counters, indexed fallback and offline presentation.');
