import './qa_cache_rate_data.mjs';
import assert from 'node:assert/strict';
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { mkdir, writeFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import { metricFixture } from './metric-interface-fixture.mjs';
import { uiTestServer } from './ui-test-server.mjs';

const output = resolve(process.argv[2] || `.local-data/cache-rate-${Date.now()}`);
await mkdir(output, {recursive:true});
const server = await uiTestServer();
const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'msedge'});
const day = (date, input, cached, extra = {}) => ({day:date, input_tokens:input, cached_tokens:cached,
  observations:1, input_available:1, cached_available:1, ...extra});
function fixtureData() {
  const fixture = metricFixture();
  fixture.date_bounds = {start:'2026-10-05',end:'2026-10-13'};
  fixture.cache_rate_timeline = [day('2026-10-05',100,100), day('2026-10-06',900,0), day('2026-10-12',200,20)];
  fixture.usage_metrics.reasoning_share_percent = 50;
  fixture.usage_metrics.reasoning_share_basis = {reasoning_tokens:5, output_tokens:10, included_responses:1, total_responses:2};
  return fixture;
}
let fixture = fixtureData();
const errors = [], requests = [];
try {
  const page = await browser.newPage({viewport:{width:1440,height:1100}, timezoneId:'Pacific/Auckland'});
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/*', async route => {
    const action = route.request().url().split('/').pop();
    const args = route.request().postDataJSON();
    let value = {};
    if (action === 'dashboard') {
      requests.push(args);
      value = structuredClone(fixture); value.filters = args;
      if (args.range === 'custom') value.date_bounds = {start:args.start,end:args.end};
      if (args.project_id || args.model || args.source_id || args.provider)
        value.cache_rate_timeline = [day('2026-10-05',100,25)];
    }
    if (action === 'status') value = {...fixture.job, revision:fixture.revision};
    if (action === 'live_status') value = {ready:true, job:{...fixture.job,revision:fixture.revision},
      desktop:{available:false}, provider_allowances:[]};
    await route.fulfill({json:value});
  });
  await page.clock.install();
  const panel = page.locator('#cache-rate');
  const rows = panel.locator('tbody tr');
  const enter = async () => { await page.locator('[data-page="usage"]').click(); await expect(panel).toBeVisible(); };
  const reload = async () => { await page.reload(); await enter(); };
  const table = async () => { if (await panel.locator('details').getAttribute('open') === null) await panel.locator('summary').click(); };
  await page.goto(server.url); await enter();
  await expect(panel.locator('[data-cache-mode="daily"]')).toHaveAttribute('aria-pressed','true');
  await expect(page.locator('#reasoning-share')).toContainText('Recorded subset · 1 of 2 responses');
  await expect(page.locator('#reasoning-share .usage-metric-value')).toHaveText('50%');
  await panel.locator('summary').focus(); await page.keyboard.press('Enter');
  await expect(rows).toHaveCount(9);
  await expect(rows.nth(0)).toContainText('100%');
  await expect(rows.nth(1).locator('td').first()).toHaveText('0%');
  await expect(rows.nth(2)).toContainText('No recorded usage');
  await panel.locator('[data-cache-mode="weekly"]').focus(); await page.keyboard.press('Enter');
  await expect(rows).toHaveCount(2);
  assert.deepEqual(await rows.nth(0).locator('th,td').allTextContents(), [
    'Oct 5, 2026 – Oct 11, 2026','10%','100','1,000','Complete counter coverage · input 2/2 · cached 2/2 responses',
  ]);
  await expect(rows.nth(1)).toContainText('Oct 12, 2026 – Oct 13, 2026');
  const box = await panel.locator('canvas').boundingBox();
  await page.mouse.move(box.x + box.width * .2, box.y + box.height * .5);
  await panel.screenshot({path:resolve(output,'weekly.png')});
  for (let i = 0; i < 5; i++) { await page.locator('[data-page="overview"]').click(); await enter(); }
  await expect(panel.locator('[data-cache-mode="weekly"]')).toHaveAttribute('aria-pressed','true');
  await expect(rows).toHaveCount(2); await expect(panel.locator('canvas')).toHaveCount(1);
  fixture.cache_rate_timeline[0].cached_tokens = 50; fixture.revision++;
  await page.clock.runFor(4100);
  await expect(rows.nth(0).locator('td').first()).toHaveText('5%');
  await expect(panel.locator('[data-cache-mode="weekly"]')).toHaveAttribute('aria-pressed','true');
  await panel.locator('[data-cache-mode="daily"]').click();
  await panel.screenshot({path:resolve(output,'daily.png')});

  // Gap reasons survive daily-to-weekly aggregation, while a known zero remains zero.
  fixture.cache_rate_timeline.push(day('2026-10-08',0,0), day('2026-10-09',100,0,{cached_available:0}));
  await reload(); await table();
  await expect(rows.nth(3)).toContainText('No input tokens');
  await expect(rows.nth(4)).toContainText('Input or cached-read counters missing');
  await panel.locator('[data-cache-mode="weekly"]').click();
  await expect(rows.nth(0).locator('td').first()).toHaveText('Unavailable');
  fixture.cache_rate_timeline = [day('2026-10-05',100,101), day('2026-10-06',900,0)];
  await reload(); await table(); await expect(rows.nth(0)).toContainText('Invalid cached-read/input ratio');

  // Applied filter changes update the graph; draft dates do not change its snapshot.
  fixture = fixtureData(); await reload(); await table();
  await page.locator('#filter-range').selectOption('custom');
  const before = await panel.locator('#cache-rate-period').textContent();
  await page.locator('#date-start').fill('2026-10-06'); await page.locator('#date-end').fill('2026-10-13');
  await expect(panel.locator('#cache-rate-period')).toHaveText(before);
  await page.locator('#date-apply').click();
  await expect(rows).toHaveCount(8); await expect(rows.first()).toContainText('Oct 6, 2026');
  await page.locator('#filter-range').selectOption('all');
  for (const [selector,value] of [['#filter-project','fixture-project'],['#filter-model','fixture-model'],['#filter-source','fixture-source']]) {
    await page.locator(selector).selectOption(value);
    await expect(rows.first().locator('td').first()).toHaveText('25%');
    await expect.poll(() => requests.at(-1)[selector === '#filter-project' ? 'project_id' : selector === '#filter-source' ? 'source_id' : 'model']).toBe(value);
    await page.locator(selector).selectOption('');
  }

  fixture.date_bounds = {start:'2024-01-01',end:'2026-12-31'}; await reload(); await table();
  await expect(rows).toHaveCount(16);
  await panel.locator('#cache-previous').focus(); await page.keyboard.press('Enter');
  await expect(rows).toHaveCount(90); await expect(panel.locator('#cache-previous')).toBeFocused();
  await panel.locator('#cache-date').fill('2024-02-29'); await panel.locator('#cache-date').press('Tab');
  await expect(rows.first()).toContainText('Jan 1, 2024'); await expect(panel.locator('#cache-previous')).toBeDisabled();
  await page.setViewportSize({width:390,height:844});
  await panel.screenshot({path:resolve(output,'narrow.png')});
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await panel.locator('[data-cache-mode="weekly"]').click();
  assert(await rows.count() <= 90);
  await page.setViewportSize({width:1440,height:1100});
  fixture = fixtureData(); delete fixture.cache_rate_timeline; await reload();
  await expect(panel).toContainText('unavailable in this snapshot');
  fixture.cache_rate_timeline = []; fixture.date_bounds.start = null; await reload();
  await expect(panel).toContainText('No observed date range');

  // Exercise the Python exporter and controls in a self-contained file with networking blocked.
  fixture = fixtureData();
  const json = resolve(output,'fixture.json'), html = resolve(output,'report.html');
  await writeFile(json, JSON.stringify(fixture));
  execFileSync(process.env.PYTHON || 'python', ['-c', 'import json,sys; from codex_insights.report import export_html; export_html(json.load(open(sys.argv[1])),sys.argv[2])', json, html],
    {env:{...process.env,PYTHONPATH:resolve('src')}});
  const offline = await browser.newPage({viewport:{width:1440,height:1100}}), network = [];
  offline.on('pageerror', error => errors.push(error.message));
  offline.on('request', request => { if (/^https?:/.test(request.url())) network.push(request.url()); });
  await offline.route(/^https?:/, route => route.abort());
  await offline.goto(pathToFileURL(html).href); await offline.locator('[data-page="usage"]').click();
  const saved = offline.locator('#cache-rate');
  await saved.locator('summary').click(); await expect(saved.locator('tbody tr')).toHaveCount(9);
  await saved.locator('[data-cache-mode="weekly"]').click();
  await expect(saved.locator('tbody tr').first().locator('td').first()).toHaveText('10%');
  await expect(offline.locator('#reasoning-share')).toContainText('Recorded subset · 1 of 2 responses');
  await expect(offline.locator('#filter-project')).toBeDisabled();
  await saved.screenshot({path:resolve(output,'offline.png')});
  assert.deepEqual(network, []); assert.deepEqual(errors, []);
  console.log(`PASS browser cache rate: daily/weekly weighting, exact tables, null/zero/invalid states, keyboard paging, navigation/refresh, applied filters, narrow layout, recorded reasoning and offline export. Artifacts: ${output}`);
} finally { await browser.close(); server.close(); }
