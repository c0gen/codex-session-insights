import './qa_metric_interface_data.mjs';
import assert from 'node:assert/strict';
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { createServer } from 'node:http';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import { metricFixture } from './metric-interface-fixture.mjs';

const output = resolve(process.argv[2] || `.local-data/metric-interface-${Date.now()}`);
await mkdir(output, { recursive: true });
const dist = resolve('frontend/dist');
const server = createServer(async (request, response) => {
  try {
    const path = resolve(dist, '.' + (request.url === '/' ? '/index.html' : request.url));
    if (!path.startsWith(dist + '/'.replace('/', process.platform === 'win32' ? '\\' : '/'))) throw new Error('Bad path');
    const body = await readFile(path);
    response.setHeader('Content-Type', ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' })[extname(path)] || 'application/octet-stream');
    response.end(body);
  } catch { response.writeHead(404); response.end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const page = await browser.newPage({ viewport: { width: 1440, height: 1100 }, timezoneId: 'Pacific/Auckland' });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
let fixture = metricFixture(), requests = [], revision = 1;
await page.route('**/api/*', async route => {
  const action = new URL(route.request().url()).pathname.split('/').at(-1);
  const filters = route.request().postDataJSON();
  let json = {};
  if (action === 'dashboard') {
    requests.push(filters);
    json = structuredClone(fixture);
    json.filters = filters;
    json.revision = revision;
    if (filters.range === 'custom') json.date_bounds = { start: filters.start, end: filters.end };
    if (filters.project_id || filters.model || filters.source_id) json.usage_metrics.cache_reuse_percent = 75;
  } else if (action === 'status') json = { ...fixture.job, revision };
  await route.fulfill({ json });
});
const panel = page.locator('#daily-sessions');
async function enter() { await page.locator('[data-page="usage"]').click(); await expect(panel).toBeVisible(); }
async function reload() { await page.reload(); await enter(); }
async function openCounts() { if (!(await panel.locator('details').getAttribute('open') !== null)) await panel.locator('summary').click(); }
try {
  await page.clock.install();
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await enter();
  await expect(page.locator('#cache-discount')).toContainText('$0.0000125');
  await expect(page.locator('#cache-discount')).toContainText('Priced subtotal only');
  await expect(page.locator('#cache-reuse .usage-metric-value')).toHaveText('50%');
  await expect(page.locator('#reasoning-share .usage-metric-value')).toHaveText('25%');
  await page.locator('.usage-metrics').screenshot({ path: resolve(output, 'metrics.png') });
  await expect(panel).toContainText('America/New_York');
  await panel.locator('summary').focus(); await page.keyboard.press('Enter');
  await expect(panel.locator('table')).toBeVisible();
  await expect(panel.locator('tbody tr')).toHaveCount(4);
  assert.deepEqual(await panel.locator('tbody tr').nth(0).locator('th,td').allTextContents(), ['2026-03-07', '4', '2', '1']);
  assert.deepEqual(await panel.locator('tbody tr').nth(1).locator('th,td').allTextContents(), ['2026-03-08', '0', '0', '0']);
  await expect(panel.locator('thead')).toHaveText('DateMain chatsSpawned sub-agentsSystem agents');
  // Trigger the real chart tooltip and inspect its accessible alternative in the same window.
  const canvas = panel.locator('canvas'), box = await canvas.boundingBox();
  await page.mouse.move(box.x + box.width * .17, box.y + box.height * .4);
  await panel.screenshot({ path: resolve(output, 'daily-counts.png') });
  await page.locator('#cache-discount .info').focus();
  await expect(page.locator('#cache-discount .info')).toHaveAttribute('aria-label', /Exact signed difference: 0.0000125 USD/);
  for (let i = 0; i < 8; i++) { await page.locator('[data-page="overview"]').click(); await enter(); }
  await expect(panel.locator('canvas')).toHaveCount(1);
  await expect(panel.locator('table')).toBeVisible();
  // Applied snapshot survives draft custom dates and navigation.
  await page.locator('#filter-range').selectOption('custom');
  await page.locator('#date-start').fill('2026-11-01'); await page.locator('#date-end').fill('2026-11-03');
  const applied = await panel.locator('#daily-sessions-period').textContent();
  await page.locator('[data-page="overview"]').click(); await enter();
  await expect(page.locator('#date-start')).toHaveValue('2026-11-01');
  await expect(panel.locator('#daily-sessions-period')).toHaveText(applied);
  await page.locator('#date-apply').click();
  await expect(panel.locator('#daily-sessions-period')).toContainText('Nov 1, 2026 – Nov 3, 2026');
  await expect(panel.locator('tbody tr')).toHaveCount(3);
  await expect(panel).toContainText('No active sessions in these dates');
  for (const [selector, value] of [['#filter-project', 'fixture-project'], ['#filter-model', 'fixture-model'], ['#filter-source', 'fixture-source']]) {
    await page.locator(selector).selectOption(value);
    await expect(page.locator('#cache-reuse .usage-metric-value')).toHaveText('75%');
    await expect.poll(() => requests.at(-1)[selector.replace('#filter-', '') === 'project' ? 'project_id' : selector.replace('#filter-', '') === 'source' ? 'source_id' : 'model']).toBe(value);
  }
  await page.evaluate(() => localStorage.clear()); await reload();
  // Automatic revision refresh uses the new metrics and does not multiply charts/listeners.
  fixture.usage_metrics.cache_reuse_percent = 12.5; revision++;
  await page.clock.runFor(4100);
  await expect(page.locator('#cache-reuse .usage-metric-value')).toHaveText('12.5%');
  await expect(panel.locator('canvas')).toHaveCount(1);
  // Paging stays bounded, is keyboard operable, and allows old calendar dates directly.
  fixture.date_bounds = { start: '2024-01-01', end: '2026-12-31' }; await reload();
  await openCounts(); await expect(panel.locator('tbody tr')).toHaveCount(16);
  await panel.locator('#session-previous').focus(); await page.keyboard.press('Enter');
  await expect(panel.locator('tbody tr')).toHaveCount(90);
  await expect(panel.locator('#session-previous')).toBeFocused();
  await panel.locator('#session-date').fill('2024-02-29'); await panel.locator('#session-date').press('Tab');
  await expect(panel.locator('tbody tr').first()).toContainText('2024-01-01');
  await expect(panel.locator('#session-previous')).toBeDisabled();
  assert.equal(await panel.locator('tbody tr').count(), 90);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(panel.locator('summary')).toBeVisible();
  assert(await panel.evaluate(node => node.getBoundingClientRect().right <= innerWidth));
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await panel.screenshot({ path: resolve(output, 'narrow.png') });
  await page.setViewportSize({ width: 1440, height: 1100 });
  fixture = metricFixture();
  Object.assign(fixture.usage_metrics, { cache_discount_usd: -0.0000000001, cache_discount_priced_tokens: 50, cache_discount_coverage_percent: 100 });
  await reload(); await expect(page.locator('#cache-discount')).toContainText('Estimated surcharge');
  await expect(page.locator('#cache-discount .usage-metric-value')).toHaveText('−$1.000e-10');
  Object.assign(fixture.usage_metrics, { cache_discount_usd: 0, cache_discount_total_tokens: 0, cache_discount_priced_tokens: 0, cache_discount_coverage_percent: null, cache_reuse_percent: 0, reasoning_share_percent: 0 });
  await reload(); await expect(page.locator('#cache-discount')).toContainText('not applicable');
  await expect(page.locator('#cache-reuse .usage-metric-value')).toHaveText('0%');
  Object.assign(fixture.usage_metrics, { cache_discount_usd: null, cache_discount_total_tokens: 50, cache_reuse_percent: null, reasoning_share_percent: null });
  await reload(); await expect(page.locator('#cache-discount')).toContainText('No applicable cache prices');
  await expect(page.locator('#reasoning-share .usage-metric-value')).toHaveText('Unavailable');
  fixture.date_bounds.start = null; await reload(); await expect(panel).toContainText('No observed date range');
  delete fixture.usage_metrics; delete fixture.daily_sessions; await reload();
  await expect(panel).toContainText('unavailable in this snapshot');
  await expect(page.locator('#cache-discount .usage-metric-value')).toHaveText('Unavailable');
  // Exercise the real Python report exporter using synthetic JSON only.
  fixture = metricFixture();
  const fixturePath = resolve(output, 'fixture.json'), reportPath = resolve(output, 'report.html');
  await writeFile(fixturePath, JSON.stringify(fixture));
  execFileSync(process.env.PYTHON || 'python', ['-c', 'import json,sys; from codex_insights.report import export_html; export_html(json.load(open(sys.argv[1])),sys.argv[2])', fixturePath, reportPath], { env: { ...process.env, PYTHONPATH: resolve('src') } });
  const offline = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const network = [];
  offline.on('pageerror', error => errors.push(error.message));
  offline.on('request', request => { if (/^https?:/.test(request.url())) network.push(request.url()); });
  await offline.route(/^https?:/, route => route.abort());
  await offline.goto(pathToFileURL(reportPath).href);
  await offline.locator('[data-page="usage"]').click();
  await expect(offline.locator('#cache-discount')).toContainText('$0.0000125');
  await offline.locator('#daily-sessions summary').click();
  await expect(offline.locator('#daily-sessions tbody tr')).toHaveCount(4);
  await expect(offline.locator('#filter-project')).toBeDisabled();
  await offline.locator('#daily-sessions').screenshot({ path: resolve(output, 'offline.png') });
  assert.deepEqual(network, []); assert.deepEqual(errors, []);
  console.log(`PASS browser metrics: card states, exact tables, keyboard paging, gaps/DST, filters/drafts, revision refresh, eight navigation cycles, narrow layout, real offline export without network. Artifacts: ${output}`);
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
