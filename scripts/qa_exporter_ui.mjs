import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { metricFixture } from './metric-interface-fixture.mjs';
import { uiTestServer } from './ui-test-server.mjs';

const output = process.argv[2] || '.local-data/exporter-ui';
await mkdir(output, {recursive: true});
const server = await uiTestServer();
const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge'});
try {
  const page = await browser.newPage({viewport: {width: 1050, height: 800}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const fixture = metricFixture();
  Object.assign(fixture, {exporter: true, demo: false, provider_setup: [], provider_allowances: []});
  let revision = 1, sequence = 0, warnings = ['1 offline source contains retained history. Latest activity could not be checked.'];
  let cancelled = false;
  const job = {running: false, message: 'Ready', error: null, progress: {}, queued: [], completed: []};
  await page.route('**/api/*', async route => {
    const action = route.request().url().split('/').pop();
    let result = {};
    if (action === 'dashboard') result = {...fixture, job, revision, filters: route.request().postDataJSON()};
    else if (action === 'status') result = {...job, revision};
    else if (action === 'provider_allowances') result = [];
    else if (action === 'export' || action === 'refresh') {
      if (action === 'export' && cancelled) result = {status: 'cancelled'};
      else {
        const id = ++sequence;
        job.completed.push({id, origin: 'user', message: action, state: 'completed', error: null,
          result: action === 'export' ? {warnings, refresh: {offline_sources: warnings.length}, sessions: 3} : {changed_files: 1}});
        revision++;
        result = {status: 'started', job_id: id, message: action};
      }
    }
    await route.fulfill({json: result});
  });
  await page.goto(server.url);
  await expect(page.locator('h1')).toHaveText('Mac Exporter');
  await page.locator('#export-snapshot').click();
  const notice = page.locator('.export-notice');
  await expect(notice).toContainText('Export saved with warnings');
  await expect(notice).toContainText('1 offline source');
  await page.locator('#refresh').click();
  await expect(notice).toContainText('Export saved with warnings');
  cancelled = true;
  await page.locator('#export-snapshot').click();
  await expect(notice).toContainText('1 offline source');
  await page.screenshot({path: `${output}/export-warning.png`, fullPage: true});
  cancelled = false;
  warnings = [];
  await page.locator('#export-snapshot').click();
  await expect(notice).toHaveText('Export saved');
  await page.setViewportSize({width: 850, height: 700});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.deepEqual(errors, []);
  console.log('Exporter UI: persistent warnings, refresh, cancelled save and clean export passed');
} finally {
  await browser.close();
  server.close();
}
