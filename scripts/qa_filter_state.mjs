import assert from 'node:assert/strict';
import { filterFixture } from './dashboard-fixture.mjs';
import { uiTestServer } from './ui-test-server.mjs';
import { createServer } from '../frontend/node_modules/vite/dist/node/index.js';
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';

// An optional isolated server URL exercises production assets. API responses
// remain synthetic in either mode; no live accounts or logs are accessed.
const production = process.argv.includes('--production');
const server = production ? await uiTestServer() : process.argv[2] ? null : await createServer({ root: 'frontend', configFile: false, server: { host: '127.0.0.1', port: 0 } });
if (!production) await server?.listen();
const url = production ? server.url : process.argv[2] || server.resolvedUrls.local[0];
const browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' });
const defaults = filterFixture();
const job = { running: false, message: '', error: null, progress: {}, revision: 1 };
const equivalents = { words: 0, novels: 0, pages: 0, stack_meters: 0, reading_years: 0, typing_years: 0, floppy_disks: 0 };
function fixture(filters) {
  const total = filters.range === 'all' ? 1000 : filters.range === '7' ? 700 : 10;
  const timeline = [{ day: '2026-09-01', tokens: total, cost: 1, prompts: 1, lines: 0 }];
  return { filters, summary: { total_tokens: total, output_tokens: 0, cached_tokens: 0, reasoning_tokens: 0,
    cost: 1, chats: 1, lines_added: 0, lines_removed: 0, priced_percent: 100, active_days: 1,
    current: 0, longest: 1, prompts: 1, input_tokens: total, cache_write_tokens: 0, change_coverage: '' },
    timeline, projects: [], models: [], heatmap: [], tiers: [], efforts: [], agents: [],
    highlights: { busiest: timeline[0], expensive: timeline[0], milestone: 10000 },
    equivalents: { total: equivalents, output: equivalents }, options: { projects: [], models: [] },
    sources: [], timezone: 'UTC', revision: job.revision, generated_at: '2026-09-02T12:00:00Z',
    date_bounds: { start: '2026-09-01', end: '2026-09-01' }, demo: true, exporter: false,
    coverage: { conflicts: 0, parse_errors: 0, replay_tokens: 0, unresolved: 0 },
    settings: { device_label: 'Synthetic', assumed_fast_percent: 0 }, job };
}
const context = await browser.newContext();
const page = await context.newPage();
const errors = [], exports = [], requests = [], held = [];
let hold = false, reject = false;
page.on('pageerror', error => errors.push(error.message));
await context.route('**/api/*', async route => {
  const action = route.request().url().split('/').pop();
  const args = route.request().postDataJSON();
  if (action === 'dashboard') {
    requests.push(args);
    if (hold) { held.push({ route, args }); return; }
    if (reject) return route.fulfill({ status: 500, json: {error:'Synthetic query failure'} });
    return route.fulfill({ json: fixture(args) });
  }
  if (action === 'export_html') { exports.push(args); return route.fulfill({json:{status:'cancelled'}}); }
  if (action === 'live_status') return route.fulfill({json:{ready:true,job,desktop:{available:false},usage_limits:{enabled:false},provider_allowances:[]}});
  if (action === 'status') return route.fulfill({json:job});
  return route.fulfill({json:{}});
});
const saved = () => page.evaluate(() => JSON.parse(localStorage.getItem('insights-filters')));
const total = value => expect(page.locator('#token-activity')).toHaveAttribute('data-total-tokens', String(value));
async function exportView() {
  const count = exports.length;
  await page.locator('#export-html').click();
  await page.locator('#report-save').click();
  await expect.poll(() => exports.length).toBe(count + 1);
  return exports.at(-1).filters;
}
try {
  await page.goto(url); await total(1000);
  await page.locator('#filter-range').selectOption('custom');
  assert.equal((await saved()).range, 'all');
  await page.reload(); await total(1000);
  await expect(page.locator('#filter-range')).toHaveValue('all');
  for (const raw of ['{', 'null', '[]', '{}', JSON.stringify({...defaults, range:'custom'}),
    JSON.stringify({...defaults, range:'custom', start:'2026-10-10', end:'2026-10-01'})]) {
    await page.evaluate(raw => localStorage.setItem('insights-filters',raw), raw);
    await page.reload(); await total(1000);
    await expect(page.locator('#toast')).toContainText('reset to All time');
    assert.deepEqual(await saved(), defaults);
  }
  await page.locator('#filter-range').selectOption('custom');
  await page.locator('#date-start').fill('2026-10-10');
  await page.locator('#date-end').fill('2026-10-01');
  const before = requests.length;
  await page.locator('#date-apply').click();
  await expect(page.locator('#toast')).toContainText('From must be on or before To');
  assert.equal(requests.length,before); assert.deepEqual(await saved(),defaults);
  await page.locator('#date-start').fill('2026-09-01');
  await page.locator('#date-end').fill('2026-09-01');
  await page.locator('#date-apply').click(); await total(10);
  await page.locator('#filter-range').selectOption('all'); await total(1000);
  await page.locator('#filter-range').selectOption('custom');
  await expect(page.locator('#date-start')).toHaveValue('2026-09-01');
  assert.deepEqual(await exportView(), defaults); await total(1000);
  hold = true;
  await page.locator('#date-apply').click();
  await expect.poll(() => held.length).toBe(1);
  assert.deepEqual(await exportView(),defaults); // Export while custom request is pending.
  await page.locator('#filter-range').selectOption('7');
  await expect.poll(() => held.length).toBe(2);
  await held[1].route.fulfill({json:fixture(held[1].args)}); await total(700);
  await held[0].route.fulfill({json:fixture(held[0].args)});
  hold = false;
  assert.equal((await exportView()).range,'7'); await total(700);
  assert.equal((await saved()).range,'7');
  reject = true;
  await page.locator('#filter-range').selectOption('30');
  await expect(page.locator('#toast')).toContainText('Synthetic query failure');
  assert.equal((await saved()).range,'7'); await total(700);
  reject = false;
  await page.reload(); await total(700);
  await page.locator('#filter-range').selectOption('custom');
  await page.locator('#date-start').fill('2026-08-01');
  await page.locator('[data-page="usage"]').click();
  await expect(page.locator('#date-start')).toHaveValue('2026-08-01');
  await page.locator('[data-page="overview"]').click();
  await expect(page.locator('#date-start')).toHaveValue('2026-08-01');
  assert.equal((await exportView()).range,'7');
  // A completion while the export modal is open cannot change its captured view.
  hold = true;
  await page.locator('#filter-range').selectOption('all');
  await expect.poll(() => held.length).toBe(3);
  await page.locator('#export-html').click();
  await held[2].route.fulfill({json:fixture(held[2].args)}); await total(1000);
  const exportCount = exports.length;
  await page.locator('#report-save').click();
  await expect.poll(() => exports.length).toBe(exportCount + 1);
  assert.equal(exports.at(-1).filters.range,'7');
  // A background response arriving after date editing begins is deferred.
  await page.locator('#filter-range').selectOption('custom');
  await page.locator('h1').click();
  job.revision++;
  await expect.poll(() => held.length).toBe(4);
  assert.equal(held[3].args.range,'all');
  await page.locator('#date-start').fill('2026-08-05');
  await held[3].route.fulfill({json:fixture(held[3].args)});
  hold = false;
  await expect(page.locator('#date-start')).toHaveValue('2026-08-05');
  await total(1000);
  assert.equal((await exportView()).range,'all');
  const beforeRefresh = requests.length;
  await page.locator('[data-page="usage"]').click();
  await expect.poll(() => requests.length).toBeGreaterThan(beforeRefresh);
  await expect(page.locator('#date-start')).toHaveValue('2026-08-05');
  assert.deepEqual(errors,[]);
  console.log('Browser filter regressions passed: startup recovery, invalid Apply, draft exports, pending exports, out-of-order responses, failed loads, navigation, modal snapshots, background date editing.');
} finally { await browser.close(); await server?.close(); }
