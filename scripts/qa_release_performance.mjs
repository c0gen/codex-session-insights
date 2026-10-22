import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { metricFixture } from './metric-interface-fixture.mjs';
import { accountFixture } from './account-ui-fixture.mjs';
import { uiTestServer } from './ui-test-server.mjs';

const output = process.argv[2] || '.local-data/release-ui';
await mkdir(output, { recursive: true });
const server = await uiTestServer();
const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge'});
const errors = [], requests = [], assets = [], timings = [];
try {
  const context = await browser.newContext({viewport: {width: 1440, height: 1000}});
  const page = await context.newPage();
  page.on('pageerror', e => errors.push(e.message));
  page.on('request', r => { if (/\/assets\//.test(r.url())) assets.push(r.url()); });
  const fixture = metricFixture();
  fixture.demo = false;
  const account = accountFixture('current', 'Current Codex');
  const rate = {status: 'available', value: 1000, observed_seconds: 300, updated_at: Date.now()/1000};
  const limits = {...account.allowance, token_burn_rate: rate, cost_burn_rate: {...rate, value: .1, priced_tokens: 1000, total_tokens: 1000}};
  const accounts = {enabled: true, allowed: true, error: null, login: {status: 'idle'}, accounts: [account], token_burn_rate: rate};
  let delay = 700, calls = 0, analyticsActive = false, analyticsStep = 0, projectionPending = false;
  await page.route('**/api/*', async route => {
    const action = route.request().url().split('/').pop(), args = route.request().postDataJSON();
    requests.push(action);
    let value = {};
    if (action === 'bootstrap') value = projectionPending
      ? {ready: true, projection: {pending: true, readable: false}, cached_overview: null}
      : {ready: false, cached_overview: {...fixture, cached_at: fixture.generated_at}};
    if (action === 'dashboard') {
      calls++;
      await new Promise(r => setTimeout(r, delay));
      const {_view, ...filters} = args;
      if (analyticsActive) {
        analyticsStep++;
        fixture.revision++;
        fixture.summary.total_tokens += 100;
        fixture.generated_at = new Date(Date.parse(fixture.generated_at) + 1000).toISOString();
      }
      value = {...fixture, filters, usage_limits: limits, analytics_refreshing: analyticsActive};
    }
    if (action === 'live_status') value = {ready: true, projection: {pending: projectionPending, readable: !projectionPending},
      job: {...fixture.job, revision: fixture.revision + Number(analyticsActive)}, desktop: {available: false},
      provider_allowances: [], usage_limits: limits, ...(args.accounts ? {accounts} : {})};
    if (action === 'accounts') value = accounts;
    if (action === 'usage_limits') value = limits;
    await route.fulfill({json: value});
  });
  for (let run=0; run<5; run++) {
    const started = performance.now();
    await page.goto(server.url, {waitUntil: 'domcontentloaded'});
    await expect(page.locator('h1')).toHaveText('Overview');
    await expect(page.locator('#cached-overview-notice')).toContainText('Cached overview');
    timings.push(performance.now()-started);
    await expect(page.locator('#update-label')).toHaveText(/^Results · /);
  }
  assert(assets.every(url => !/gallery-.*\.js/.test(url)), 'Overview must not request the 3D chunk');
  const before = calls;
  await page.waitForTimeout(4500);
  assert.equal(calls, before, 'idle live polling must not reload analytics');
  assert(requests.includes('live_status'));
  const intervalRequests = requests.slice(-2);
  assert(intervalRequests.every(name => name === 'live_status'), 'idle requests are consolidated');
  delay = 0;
  await page.locator('[data-page="usage"]').click();
  await expect(page.locator('h1')).toHaveText('Usage & Cost');
  await expect(page.locator('#model-chart')).toBeVisible();
  await page.locator('[data-page="accounts"]').click();
  await expect(page.locator('h1')).toHaveText('Accounts');
  await expect(page.locator('.account-card')).toHaveCount(1);
  await page.locator('[data-page="visualizations"]').click();
  await expect(page.locator('#world-viewport')).toHaveAttribute('data-ready', 'true', {timeout: 20000});
  await expect(page.getByText('Loading visualizations…', {exact: true})).toHaveCount(0);
  assert(assets.some(url => /gallery-.*\.js/.test(url)), '3D navigation must load its own chunk');
  await page.screenshot({path: `${output}/gallery.png`, fullPage: true});
  await page.locator('[data-page="overview"]').click();
  await expect(page.locator('h1')).toHaveText('Overview');
  // Drive real production rendering/polling through rapid maintenance changes.
  await page.clock.install();
  const resultsTop = () => page.locator('#dashboard-results').evaluate(el => el.getBoundingClientRect().top);
  const stableTop = await resultsTop();
  fixture.job = {running: true, id: 42, origin: 'user', cancelable: true,
    message: 'Rebuilding index', progress: {sessions: 1}, completed: []};
  await page.clock.runFor(2100);
  await expect(page.locator('#job-banner')).toBeVisible();
  assert.equal(await resultsTop(), stableTop, 'maintenance notice must not move the dashboard');
  fixture.job = {...fixture.job, running: false, state: 'completed', completed: [
    {id: 42, origin: 'user', message: 'Rebuilding index', state: 'completed', error: null, result: {}}]};
  await page.clock.runFor(2100);
  await expect(page.locator('#job-banner')).toContainText('Completed');
  await page.clock.runFor(3500);
  await expect(page.locator('#job-banner')).toBeVisible();
  assert.equal(await resultsTop(), stableTop);
  await page.screenshot({path: `${output}/stable-status.png`, fullPage: true});
  await page.clock.runFor(2200);
  await expect(page.locator('#job-banner')).toBeHidden();
  analyticsActive = true;
  const shown = [];
  for (let run = 0; run < 3; run++) {
    const previousStep = analyticsStep;
    await page.clock.runFor(2300);
    await expect.poll(() => analyticsStep).toBeGreaterThan(previousStep);
    await expect(page.locator('#analytics-refresh-notice')).toContainText('Updating metrics');
    shown.push(await page.locator('#total-tokens-kpi strong').first().textContent());
    assert.equal(await resultsTop(), stableTop, 'analytics notice must not move the dashboard');
  }
  assert.equal(new Set(shown).size, 3, 'displayed totals must advance while indexing continues');
  analyticsActive = false;
  await page.clock.runFor(2300);
  await expect(page.locator('#analytics-refresh-notice')).toContainText('Metrics updated');
  projectionPending = true;
  await page.reload();
  await expect(page.locator('.panel.loading[role="status"]')).toContainText('Verifying the accepted configuration');
  projectionPending = false;
  await page.clock.runFor(2300);
  await expect(page.locator('h1')).toHaveText('Overview');
  await page.screenshot({path: `${output}/overview.png`, fullPage: true});
  timings.sort((a,b)=>a-b);
  const result = {cached_overview_p95_ms: Math.round(timings.at(-1)), runs: timings.length,
    no_gallery_on_startup: true, consolidated_idle_polling: true, deferred_tabs: true,
    stable_status_layout: true, readable_completions: true, advancing_displayed_totals: shown,
    legacy_projection_loading_recovers: true, errors};
  assert.deepEqual(errors, []);
  assert(result.cached_overview_p95_ms <= 3000);
  await writeFile(`${output}/results.json`, JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} finally { await browser.close(); server.close(); }
