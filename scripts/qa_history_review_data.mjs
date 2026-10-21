import assert from 'node:assert/strict';
import { build } from '../frontend/node_modules/esbuild/lib/main.js';

const result = await build({entryPoints: ['frontend/src/history-review.ts'], bundle: true, format: 'esm', write: false,
  loader: {'.css': 'empty'}});
const { coverageNotice, reviewBody } = await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
const data = {coverage: {conflicts: 2, parse_errors: 0, accounting_overlaps: 1, awaiting_verification: 3}};
assert.match(coverageNotice(data), /2 copy conflicts/);
assert.match(coverageNotice(data), /1 accounting overlaps/);
assert.match(coverageNotice(data), /3 awaiting verification/);
assert.doesNotMatch(coverageNotice(data), /0 unparsed|Accepted history is retained/);
assert.match(coverageNotice({...data, readonly: true}), /Open the desktop app/);
assert.doesNotMatch(coverageNotice({...data, readonly: true}), /<button/);
assert.equal(coverageNotice({coverage: {conflicts: 0, parse_errors: 0}}), '');
const group = {session_id: '<session>', reason: 'Different counters', state: 'manually_resolved', kind: 'copy', has_selection: true,
  versions: [{id: 'x', source: '<source>', format: 'Transcript history', accepted: true, records: 10, recorded_tokens: 110,
    locations: ['C:/private/<file>.jsonl'], first_activity: '2026-10-01T12:00:00Z', last_activity: '2026-10-01T13:00:00Z'}]};
const html = reviewBody([group], 'America/New_York');
assert.match(html, /Keep accepted/);
assert.match(html, /Undo selection/);
assert.match(html, /Selection saved/);
assert.match(html, /&lt;source&gt;/);
assert.match(html, /&lt;file&gt;/);
assert.match(html, /110 recorded tokens/);
assert.doesNotMatch(html, /<session>|<source>|<file>/);
assert.match(reviewBody([], 'UTC'), /No histories need review/);
const large = reviewBody([{...group, alternative_only_tokens: 3_000_000_001,
  alternative_only_responses: 2, disputed_responses: 1, reason_code: 'claude_identity_unverified'}], 'UTC');
assert.match(large, /3,000,000,001 potentially excluded tokens/);
assert.match(large, /1 response has disputed counters/);
assert.match(large, /data-history-select[^>]+disabled/);
const recoveryBuild = await build({entryPoints: ['frontend/src/claude-recovery.ts'], bundle: true, format: 'esm', write: false});
const {recoveryNotice} = await import(`data:text/javascript;base64,${Buffer.from(recoveryBuild.outputFiles[0].text).toString('base64')}`);
const recoveryHtml = recoveryNotice({state: 'awaiting_verification', identity_issues: 1, newly_included_responses: 2,
  newly_included_tokens: 3_000_000_001, reopened_choices: 1, sources: [{state: 'pending', accepted_tokens_before: 100,
  accepted_tokens_after: 3_000_000_101, accepted_token_change: 3_000_000_001, legacy_snapshot_without_alternatives: true}]});
assert.match(recoveryHtml, /3,000,000,001 newly included tokens/);
assert.match(recoveryHtml, /older snapshot omitted alternative histories/);
assert.match(recoveryHtml, /100 → 3,000,000,101/);
assert.equal(recoveryNotice(), '');
console.log('History coverage, review states and escaped metadata passed');
