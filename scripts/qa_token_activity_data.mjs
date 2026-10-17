import assert from 'node:assert/strict';
import { build } from '../frontend/node_modules/esbuild/lib/main.js';
import { metricFixture } from './metric-interface-fixture.mjs';
import { filterFixture } from './dashboard-fixture.mjs';

async function moduleAt(path) {
  const compiled = await build({ entryPoints: [path], bundle: true, format: 'esm', write: false });
  return import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString('base64')}`);
}
const { buildTokenActivity } = await moduleAt('frontend/src/token-activity-data.ts');
const { summaryImageSnapshot } = await moduleAt('frontend/src/summary-image-data.ts');
const fixture = (start, end, timeline = []) => ({
  ...metricFixture(),
  date_bounds: { start, end }, timeline, timezone: 'America/New_York', generated_at: '2026-10-09T03:59:00Z',
  filters: filterFixture(),
  options: { projects: [] }, settings: { assumed_fast_percent: 0 },
  summary: { ...metricFixture().summary, total_tokens: timeline.reduce((sum, row) => sum + row.tokens, 0) },
});
const row = (day, tokens) => ({ day, tokens });
function reconciles(data) {
  const result = buildTokenActivity(data);
  assert.equal(result.days.reduce((sum, day) => sum + day.tokens, 0), result.total);
  assert.equal(result.weeks.reduce((sum, week) => sum + week.tokens, 0), result.total);
  assert.equal(result.days.at(-1)?.cumulative || 0, result.total);
  assert.equal(result.years.flatMap(year => year.cells).filter(Boolean).length, result.days.length);
  assert.equal(new Set(result.days.map(day => day.day)).size, result.days.length);
  return result;
}

// Missing selected days are real zeroes, while alignment padding is not a day.
const selected = fixture('2024-02-28', '2024-03-02', [row('2024-02-28', 12), row('2024-03-01', 8)]);
const before = JSON.stringify(selected), leap = reconciles(selected);
assert.deepEqual(leap.days.map(day => day.day), ['2024-02-28', '2024-02-29', '2024-03-01', '2024-03-02']);
assert.deepEqual(leap.days.map(day => day.tokens), [12, 0, 8, 0]);
assert.deepEqual(leap.days.map(day => day.cumulative), [12, 12, 20, 20]);
assert.deepEqual(leap.years[0].cells.map(day => day?.tokens ?? null), [null, null, 12, 0, 8, 0, null]);
assert.equal(JSON.stringify(selected), before);
assert.deepEqual(summaryImageSnapshot(selected, false).activity, [12, 0, 8, 0]);

// A week spanning New Year is counted once, despite separate calendar grids.
const crossing = reconciles(fixture('2025-12-31', '2026-01-06', [row('2025-12-31', 100), row('2026-01-01', 25), row('2026-01-05', 50)]));
assert.deepEqual(crossing.weeks, [
  { weekStart: '2025-12-29', start: '2025-12-31', end: '2026-01-04', tokens: 125 },
  { weekStart: '2026-01-05', start: '2026-01-05', end: '2026-01-06', tokens: 50 },
]);
assert.deepEqual(crossing.years.map(year => year.year), ['2025', '2026']);
assert.equal(crossing.years[1].cells[3].day, '2026-01-01');
assert.equal(crossing.years[1].cells[3].level, 1); // Common scale across years.
const bands = reconciles(fixture('2026-01-01', '2026-01-05', [0, 25, 50, 75, 100].map((value, index) => row(`2026-01-0${index + 1}`, value))));
assert.deepEqual(bands.days.map(day => day.level), [0, 1, 2, 3, 4]);

for (const [start, end, days] of [
  ['2026-03-07', '2026-03-10', 4], ['2026-10-31', '2026-11-03', 4],
  ['2024-01-01', '2026-12-31', 1096], ['2026-10-09', '2026-10-09', 1],
]) {
  const result = reconciles(fixture(start, end, [row(start, 17)]));
  assert.equal(result.days.length, days);
  assert.equal(result.total, 17);
  assert.equal(result.days.at(-1).day, end);
}
const empty = reconciles(fixture('2026-10-01', '2026-10-09'));
assert.equal(empty.days.length, 9);
assert(empty.days.every(day => day.level === 0));
assert.equal(reconciles(fixture(null, '2026-10-09')).days.length, 0);
assert.equal(reconciles(fixture('2026-10-10', '2026-10-09')).days.length, 0);
assert.equal(reconciles(fixture('2026-10-01', '2026-10-01', [row('2026-09-30', 99), row('2026-10-01', 7), row('2026-10-02', 99)])).total, 7);

// Compatibility dates follow the snapshot timezone, never the browser clock.
for (const [generated, expectedStart, expectedEnd] of [
  ['2026-03-09T03:59:00Z', '2026-03-02', '2026-03-08'],
  ['2026-11-02T04:30:00Z', '2026-10-26', '2026-11-01'],
]) {
  const data = fixture(null, '', []);
  delete data.date_bounds;
  data.filters.range = '7'; data.generated_at = generated;
  const result = reconciles(data), image = summaryImageSnapshot(data, false);
  assert.equal(result.start, expectedStart); assert.equal(result.end, expectedEnd);
  assert.equal(result.days.length, 7);
  assert.equal(image.start, expectedStart); assert.equal(image.end, expectedEnd);
}
console.log('Token activity data checks passed: gaps, leap years, DST, shared image dates, partial weeks, yearly grids, scale, empty ranges, and reconciliation.');
