import assert from 'node:assert/strict';
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { build } from '../frontend/node_modules/esbuild/lib/main.js';
import { mkdir } from 'node:fs/promises';
import { metricFixture } from './metric-interface-fixture.mjs';
import { coverageFixture, filterFixture } from './dashboard-fixture.mjs';
import { uiTestServer } from './ui-test-server.mjs';

const server = await uiTestServer();
const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge'});
const fixture = metricFixture(); fixture.demo = false;
const indexed = total_tokens => ({total_tokens, state: 'complete', sessions: 1});
fixture.indexed_token_totals = {codex: indexed(700000), claude_code: indexed(200000), antigravity: indexed(300000)};
let total = {total_tokens: 1000000, accounts: 1, reported_accounts: 1, identity_complete: true, stale: false};
let exports = [], errors = [];
try {
  const page = await browser.newPage({viewport: {width: 1440, height: 1000}});
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(filters => localStorage.setItem('insights-filters', JSON.stringify(filters)),
    filterFixture({project_id: 'removed-project', source_id: 'removed-source', model: 'removed-model', range: '7'}));
  await page.route('**/api/*', async route => {
    const action = route.request().url().split('/').pop(), args = route.request().postDataJSON();
    let value = {};
    if (action === 'dashboard') {
      const filters = {...args};
      for (const key of ['project_id', 'source_id', 'model']) if (filters[key]?.startsWith('removed-')) filters[key] = '';
      value = {...fixture, filters, account_token_total: total};
    }
    if (action === 'accounts') value = {accounts: [], login: {status:'idle'}, allowed:false, enabled:true, token_total: total};
    if (action === 'provider_allowances') value = [];
    if (action === 'status') value = {...fixture.job, revision: fixture.revision};
    if (action === 'export_html') { exports.push(args); value = {status:'cancelled'}; }
    await route.fulfill({json:value});
  });
  await page.goto(server.url);
  await expect(page.locator('#toast')).toContainText('no longer available');
  assert.deepEqual(await page.evaluate(() => JSON.parse(localStorage.getItem('insights-filters'))), filterFixture({range:'7'}));
  await page.locator('#export-html').click(); await page.locator('#report-save').click();
  await expect.poll(() => exports.length).toBe(1);
  assert.deepEqual(exports[0].filters, filterFixture({range:'7'}));
  await expect(page.locator('#total-tokens-kpi > strong')).toHaveText('1.5M');
  await expect(page.locator('#text-equivalent-notes')).toContainText('1,500,000 tokens');
  const values = () => page.locator('#text-equivalent-values').innerText();
  const before = await values();
  await page.locator('#equivalents-more').click();
  const extraBefore = await page.locator('#extra-equivalents').innerText();
  total = {...total, total_tokens: 2000000};
  await expect(page.locator('#text-equivalent-notes')).toContainText('2,500,000 tokens');
  assert.notEqual(await values(), before);
  assert.notEqual(await page.locator('#extra-equivalents').innerText(), extraBefore);
  await expect(page.locator('#extra-equivalents')).toBeVisible();
  const totalPaper = await page.locator('#paper-stack-value strong').innerText();
  await page.locator('[data-basis="output"]').click();
  const output = await values();
  assert.notEqual(await page.locator('#paper-stack-value strong').innerText(), totalPaper);
  await expect(page.locator('#text-equivalent-notes')).toContainText('20 tokens');
  total = {...total, total_tokens: 3000000};
  await expect(page.locator('#total-tokens-kpi > strong')).toHaveText('3.5M');
  assert.equal(await values(), output);
  await expect(page.locator('[data-basis="output"]')).toHaveAttribute('aria-pressed','true');
  await page.locator('[data-page="usage"]').click(); await page.locator('[data-page="overview"]').click();
  assert.equal(await values(), output);
  await page.locator('[data-basis="total"]').click();
  await page.locator('#filter-provider').selectOption('claude_code');
  await expect(page.locator('#text-equivalent-notes')).toContainText('3,500,000 tokens');
  await page.setViewportSize({width:850,height:700});
  for (const name of ['Overview','Usage & Cost','Projects','Accounts','Sources'])
    await expect(page.getByRole('navigation').getByRole('button',{name,exact:true})).toBeVisible();
  await expect(page.getByRole('button',{name:'Overview',exact:true})).toHaveAttribute('aria-current','page');
  await expect(page.getByRole('button',{name:'Settings',exact:true})).toBeVisible();
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await mkdir('.local-data/dashboard-fix-ui',{recursive:true});
  await page.screenshot({path:'.local-data/dashboard-fix-ui/combined-narrow.png',fullPage:true});

  fixture.demo = true; fixture.coverage = coverageFixture('unavailable');
  fixture.summary.total_tokens = fixture.summary.output_tokens = 0;
  fixture.usage_metrics.cache_discount_usd = 0; fixture.usage_metrics.cache_discount_total_tokens = 0;
  await page.reload();
  await expect(page.locator('#token-activity')).toContainText('Token counters unavailable');
  await expect(page.locator('#token-activity .token-day')).toHaveCount(0);
  await expect(page.locator('#token-activity')).not.toContainText('0 analyzed tokens');
  await expect(page.locator('#text-equivalent-values strong')).toHaveText(['—','—','—','—']);
  await page.locator('[data-page="usage"]').click();
  await expect(page.locator('#cache-discount .usage-metric-value')).toHaveText('Unavailable');
  await expect(page.locator('#cache-discount')).not.toContainText('No cached reads');

  // Inspect the real chart module's datasets, not just a screenshot of an empty bar.
  const compiled = await build({entryPoints:['frontend/src/charts.ts'],bundle:true,format:'esm',write:false});
  const chartPage = await browser.newPage();
  await chartPage.setContent('<div style="height:300px;width:600px"><canvas id="model-chart"></canvas></div>');
  const result = await chartPage.evaluate(async source => {
    const m = await import('data:text/javascript;base64,' + source);
    m.modelChart({models:[{name:'missing',tokens:1,cost:null},{name:'zero',tokens:0,cost:0},{name:'priced',tokens:1,cost:2}]},'cost');
    const chart=m.Chart.getChart(document.querySelector('canvas'));
    return {values:chart.data.datasets[0].data, labels:chart.data.labels,
      missing:chart.options.plugins.tooltip.callbacks.label({raw:null}), zero:chart.options.plugins.tooltip.callbacks.label({raw:0})};
  },Buffer.from(compiled.outputFiles[0].text).toString('base64'));
  assert.deepEqual(result,{values:[null,0,2],labels:['missing · Unpriced','zero','priced'],missing:'Unpriced',zero:'$0.00'});
  assert.deepEqual(errors,[]);
  console.log('Dashboard browser checks passed: recovered filters/export, combined equivalents/polling/basis, unavailable counters, nullable costs and named narrow navigation.');
} finally {await browser.close(); server.close();}
