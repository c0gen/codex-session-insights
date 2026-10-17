import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { createServer } from '../frontend/node_modules/vite/dist/node/index.js';
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { metricFixture } from './metric-interface-fixture.mjs';
import { filterFixture } from './dashboard-fixture.mjs';
import { uiTestServer } from './ui-test-server.mjs';

const production = process.argv.includes('--production');
const server = production ? await uiTestServer() : await createServer({ root: 'frontend', configFile: false, server: { host: '127.0.0.1', port: 0 } });
if (!production) await server.listen();
const url = production ? server.url : server.resolvedUrls.local[0];
let browser;
const job = { running: false, message: '', error: null, progress: {}, revision: 1 };
function fixture(filters) {
  const data = metricFixture();
  const total = filters.project_id === 'project-a' ? 200 : filters.project_id === 'project-b' ? 400 : 1000;
  data.filters = filters; data.job = job; data.revision = job.revision;
  data.summary.total_tokens = data.timeline[0].tokens = total;
  data.options.projects = [{ id: 'project-a', name: 'Project A' }, { id: 'project-b', name: 'Project B' }];
  data.projects = data.options.projects.filter(p => !filters.project_id || p.id === filters.project_id).map(p => ({
    project_id: p.id, name: p.name, chats: 1, tokens: p.id === 'project-a' ? 200 : 400,
    cost: 0.01, added: 0, removed: 0, last_active: '2026-03-07', token_coverage: 'complete',
  }));
  return data;
}
try {
  browser = await chromium.launch({ headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1050 } });
  await page.clock.install();
  const held = [], requests = [], exports = [], errors = [];
  let hold = false;
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/*', async route => {
    const action = route.request().url().split('/').pop(), args = route.request().postDataJSON();
    if (action === 'dashboard') {
      requests.push(args);
      if (hold) { held.push({ route, args }); return; }
      return route.fulfill({ json: fixture(args) });
    }
    if (action === 'status') return route.fulfill({ json: job });
    if (action === 'provider_allowances') return route.fulfill({ json: [] });
    if (action === 'accounts') return route.fulfill({ json: { accounts: [], login: { status: 'idle' }, allowed: false, enabled: false } });
    if (action === 'export_html') { exports.push(args.filters); return route.fulfill({ json: { status: 'cancelled' } }); }
    return route.fulfill({ json: {} });
  });
  const select = (name, value) => page.locator('#filter-' + name).selectOption(value);
  const total = value => expect(page.locator('#token-activity')).toHaveAttribute('data-total-tokens', String(value));
  const saved = () => page.evaluate(() => JSON.parse(localStorage.getItem('insights-filters')));
  async function pending(action) {
    hold = true;
    const count = held.length;
    await action();
    await expect.poll(() => held.length).toBe(count + 1);
    return held[count];
  }
  async function release(request, error = '') {
    const response = page.waitForResponse(r => r.url().endsWith('/api/dashboard') && r.request().postData() === JSON.stringify(request.args));
    await request.route.fulfill(error ? { status: 500, json: { error } } : { json: fixture(request.args) });
    await (await response).finished();
    // Let the response handler run before checking that a stale response did nothing.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  }
  async function exportView() {
    const count = exports.length;
    await page.locator('#export-html').click(); await page.locator('#report-save').click();
    await expect.poll(() => exports.length).toBe(count + 1);
    return exports.at(-1);
  }
  const busy = value => expect(page.locator('#dashboard-results')).toHaveAttribute('aria-busy', String(value));
  const status = page.locator('#filter-feedback');
  await page.goto(url); await total(1000);
  await page.evaluate(() => { window.testChart = document.querySelector('#activity-chart'); });
  let request = await pending(() => select('project', 'project-a'));
  await expect(page.locator('#filter-project')).toHaveValue('project-a');
  await expect(page.locator('#filters-reset')).toBeVisible();
  await busy(true); await total(1000);
  await expect(status.locator('span')).toHaveText('Updating metrics… Showing previous results');
  assert.equal(await page.evaluate(() => window.testChart === document.querySelector('#activity-chart')), true);
  assert.deepEqual(await exportView(), filterFixture());
  await release(request); await total(200); await busy(false);
  await expect(status).toBeHidden();
  await expect(page.locator('.page-header p')).toHaveText('Project A');

  request = await pending(() => page.locator('#filters-reset').click());
  assert.deepEqual(request.args, filterFixture());
  await expect(page.locator('#filter-project')).toHaveValue('');
  await expect(page.locator('#filters-reset')).toHaveCount(0);
  await total(200); await busy(true);
  await expect(page.locator('.page-header p')).toHaveText('Project A');
  await mkdir('.local-data/project-filter-ui', { recursive: true });
  await page.screenshot({ path: '.local-data/project-filter-ui/pending.png', fullPage: true });
  await release(request); await total(1000);
  assert.deepEqual(await saved(), filterFixture());

  // All Projects preserves every other selection; Reset clears them all.
  hold = false;
  for (const [name, value] of [['range', '7'], ['model', 'fixture-model'], ['source', 'fixture-source'], ['provider', 'codex'], ['project', 'project-a']]) {
    await select(name, value);
    await expect.poll(async () => (await saved())[({ range:'range', model:'model', source:'source_id', provider:'provider', project:'project_id' })[name]]).toBe(value);
  }
  await total(200);
  const otherFilters = filterFixture({ range: '7', model: 'fixture-model', source_id: 'fixture-source', provider: 'codex' });
  request = await pending(() => select('project', ''));
  assert.deepEqual(request.args, otherFilters);
  await total(200);
  assert.deepEqual(await exportView(), { ...otherFilters, project_id: 'project-a' });
  await release(request); await total(1000);
  request = await pending(() => page.locator('#filters-reset').click());
  for (const name of ['project', 'model', 'source', 'provider']) await expect(page.locator('#filter-' + name)).toHaveValue('');
  await expect(page.locator('#filter-range')).toHaveValue('all');
  await release(request); await total(1000);

  // Project-row navigation enters the same pending/applied lifecycle.
  await page.locator('[data-page="projects"]').click();
  request = await pending(() => page.locator('tr[data-project="project-b"] .project-name').click());
  await expect(page.locator('#filter-project')).toHaveValue('project-b');
  await busy(true);
  await release(request); await total(400);

  const old = await pending(() => select('project', 'project-a'));
  request = await pending(() => page.locator('#filters-reset').click());
  await release(request); await total(1000);
  await release(old, 'Stale failure');
  await expect(status).toBeHidden(); await busy(false);
  assert.deepEqual(await saved(), filterFixture());

  const first = await pending(() => select('project', 'project-a'));
  const second = await pending(() => select('project', 'project-b'));
  await release(first); await total(1000); await busy(true);
  await release(second); await total(400); await busy(false);

  request = await pending(() => select('project', 'project-a'));
  await release(request, 'Synthetic query failure');
  await busy(false); await total(400);
  await expect(status).toContainText('Couldn’t update metrics. Showing previous results. Synthetic query failure');
  assert.equal((await saved()).project_id, 'project-b');
  assert.equal((await exportView()).project_id, 'project-b');
  await page.locator('[data-page="usage"]').click();
  await expect(status).toContainText('Synthetic query failure');
  await page.locator('[data-page="overview"]').click();
  const beforePolling = requests.length;
  job.revision++;
  await page.clock.runFor(6000);
  assert.equal(requests.length, beforePolling);
  await page.setViewportSize({ width: 850, height: 750 });
  await page.screenshot({ path: '.local-data/project-filter-ui/error-narrow.png', fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  request = await pending(() => page.locator('#filters-retry').click());
  await expect(status).toContainText('Updating metrics');
  await release(request); await total(200);
  await expect(status).toBeHidden();

  request = await pending(() => select('project', 'project-b'));
  await page.locator('[data-page="usage"]').click(); await busy(true);
  await expect(status).toContainText('Showing previous results');
  await page.locator('[data-page="overview"]').click(); await total(200);
  await release(request); await total(400);
  await select('range', 'custom');
  await page.locator('#date-start').fill('');
  await page.locator('#date-apply').click();
  await expect(page.locator('#toast')).toContainText('Choose valid From and To dates');
  request = await pending(() => page.locator('#filters-reset').click());
  await expect(page.locator('#date-start')).toHaveCount(0);
  assert.deepEqual(request.args, filterFixture());
  await release(request); await total(1000);

  const report = { ...fixture(filterFixture()), readonly: true };
  await page.addInitScript(report => { window.__INSIGHTS_REPORT__ = report; }, report);
  await page.reload(); await total(1000);
  for (const name of Object.keys({ range:1, project:1, model:1, source:1, provider:1 })) await expect(page.locator('#filter-' + name)).toBeDisabled();
  await expect(status).toBeHidden();
  assert.deepEqual(errors, []);
  console.log(`Project filter browser regressions passed (${production ? 'production' : 'development'}): immediate controls, unchanged charts, loading, reset, All Projects, exports, row navigation, races, failures/retry, polling, date drafts and read-only reports.`);
} finally {
  await browser?.close();
  await server.close();
}
