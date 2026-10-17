import assert from 'node:assert/strict';
import { build } from '../frontend/node_modules/esbuild/lib/main.js';

const result = await build({entryPoints: ['frontend/src/export-feedback.ts'], bundle: true, format: 'esm', write: false});
const { ExportFeedback } = await import(`data:text/javascript;base64,${Buffer.from(result.outputFiles[0].text).toString('base64')}`);
const feedback = new ExportFeedback();
assert.equal(feedback.render(), '');
feedback.observe({state: 'completed', result: {warnings: ['1 offline source', '<private>']}});
assert.match(feedback.render(), /Export saved with warnings/);
assert.match(feedback.render(), /role="status"/);
assert.match(feedback.render(), /&lt;private&gt;/);
const warning = feedback.render();
feedback.observe({state: 'completed', result: {changed_files: 3}});
feedback.observe({state: 'cancelled', result: {warnings: []}});
assert.equal(feedback.render(), warning);
feedback.observe({state: 'completed', result: {warnings: []}});
assert.match(feedback.render(), /Export saved/);
assert.doesNotMatch(feedback.render(), /Export saved with warnings/);
console.log('Export completion feedback passed');
