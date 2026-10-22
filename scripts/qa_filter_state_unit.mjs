import assert from 'node:assert/strict';
import { build } from '../frontend/node_modules/esbuild/lib/main.js';

const compiled = await build({ entryPoints: ['frontend/src/filter-state.ts'], bundle: true, format: 'esm', write: false });
const { FilterState, restoreFilters, defaultFilters } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString('base64')}`);
const defaults = defaultFilters();
for (const raw of ['{', 'null', '[]', '42', '{}', JSON.stringify({...defaults, range: 'bad'}),
  JSON.stringify({...defaults, model: []}), ...[
    ['', ''], ['2026-10-10', '2026-10-01'], ['2026-02-30', '2026-03-01'], ['0000-01-01', '2026-01-01']
  ].map(([start,end]) => JSON.stringify({...defaults, range: 'custom', start, end}))]) {
  const restored = restoreFilters(raw);
  assert.equal(restored.recovered, true, raw);
  assert.deepEqual(restored.filters, defaults);
}
assert.equal(restoreFilters(null).recovered, false);
const state = new FilterState(defaults);
let request = state.begin();
state.accept(request);
Object.assign(state.draft, { range: 'custom', start: '2026-09-01', end: '2026-09-01' });
assert.equal(state.exportSnapshot().range, 'all'); // Selecting custom does not apply it.
request = state.begin(); state.accept(request);
state.draft.range = 'all'; request = state.begin(); state.accept(request);
state.draft.range = 'custom';
assert.equal(state.draft.start, '2026-09-01');
assert.equal(state.exportSnapshot().range, 'all'); // B5: earlier custom dates are still drafts.
state.draft.start = '';
assert.throws(() => state.begin(), /valid From/);
assert.equal(state.exportSnapshot().range, 'all');
state.draft.start = '2026-09-01';
const first = state.begin();
state.draft.range = '7';
const second = state.begin();
assert.equal(state.begin("background"), null); // Background queries cannot supersede user requests.
const exportDuringLoad = state.exportSnapshot();
assert.equal(exportDuringLoad.range, 'all');
state.accept(second);
assert.equal(state.accept(first), null);
assert.equal(state.exportSnapshot().range, '7');
assert.equal(exportDuringLoad.range, 'all');
assert(Object.isFrozen(exportDuringLoad));
state.draft.range = '30'; request = state.begin(); state.finish(request);
assert.equal(state.exportSnapshot().range, '7'); // Failed requests do not change the applied state.
Object.assign(state.draft, { range: 'custom', start: '2026-08-01', end: '2026-08-02' });
request = state.begin("background");
assert.equal(request.filters.range, '7');
state.draft.start = '2026-08-03';
state.accept(request);
assert.equal(state.draft.range, 'custom');
assert.equal(state.draft.start, '2026-08-03');
Object.assign(state.draft, { range: 'all', project_id: 'old', model: 'model-a', source_id: 'source-a' });
request = state.begin(); state.accept(request, {...request.filters, project_id: 'merged'});
assert.equal(state.draft.project_id, 'merged');
assert.equal(state.exportSnapshot().model, 'model-a');
assert.equal(state.exportSnapshot().source_id, 'source-a');
// A stale success or failure must not clear a newer request's feedback.
state.draft.project_id = 'project-a';
const oldRequest = state.begin();
state.draft.project_id = '';
const resetRequest = state.begin();
assert.equal(state.loading, true);
state.fail(oldRequest, 'Stale failure');
assert.equal(state.error, null);
assert.equal(state.accept(oldRequest), null);
assert.equal(state.loading, true);
state.fail(resetRequest, 'Query failed');
assert.equal(state.loading, false);
assert.equal(state.error, 'Query failed');
assert.equal(state.exportSnapshot().project_id, 'merged');
assert.equal(state.begin("background"), null); // Keep failed selections visible until retry.
request = state.begin();
assert.equal(state.error, 'Query failed');
assert.equal(state.loading, true);
state.accept(request);
assert.equal(state.loading, false);
assert.equal(state.exportSnapshot().project_id, '');
console.log('Filter state regressions passed: restore validation, drafts, failures, exports, races, background refresh, merged IDs.');

// Navigation must never validate or submit unfinished dates.
const navigation = new FilterState({...defaults, range: '7'});
assert.equal(navigation.hasApplied, false);
request = navigation.begin('initial'); navigation.accept(request);
assert.equal(navigation.hasApplied, true);
Object.assign(navigation.draft, {range:'custom',start:'2026-10-10',end:''});
request = navigation.begin('navigation');
assert.equal(request.filters.range, '7'); navigation.accept(request);
assert.equal(navigation.draft.end, '');
Object.assign(navigation.draft, {start:'2026-09-01',end:'2026-09-02'});
const submitted = navigation.begin('apply');
navigation.draft.end = '2026-09-03';
request = navigation.begin('navigation');
assert.equal(request.filters.end, '2026-09-02');
assert.equal(navigation.accept(submitted), null);
navigation.fail(request, 'Failed submitted view');
navigation.draft.start = '';
request = navigation.begin('retry');
assert.equal(request.filters.start, '2026-09-01');
assert.equal(request.filters.end, '2026-09-02');
navigation.accept(request);
assert.equal(navigation.draft.start, '');
assert.equal(navigation.exportSnapshot().end, '2026-09-02');
