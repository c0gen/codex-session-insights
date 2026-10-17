import { chromium } from '../frontend/node_modules/@playwright/test/index.mjs';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const [url, output = '.local-data/merge-allowance-ui-checks'] = process.argv.slice(2);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const context = await browser.newContext();
const errors = [];
const now = Math.floor(Date.now() / 1000);
const rate = value => ({ value, status: 'available', observed_seconds: 300, updated_at: now });
let limits = { enabled: true, allowed: true, status: 'available', refreshing: false, stale: false,
  last_success_at: now, next_refresh_at: now + 60, error: null, error_code: null,
  token_burn_rate: rate(12400),
  buckets: [{ id: 'codex', name: 'Codex', windows: [{ id: 'primary', remaining_percent: 51, window_duration_mins: 10080, resets_at: now + 3600, burn_rate: rate(2.4) }] },
    { id: 'other', name: 'Other allowance', windows: [{ id: 'primary', remaining_percent: 83, window_duration_mins: 300, resets_at: now + 1800, burn_rate: rate(7.2) }, { id: 'secondary', remaining_percent: null, window_duration_mins: null, resets_at: null, burn_rate: { ...rate(null), status: 'unavailable', observed_seconds: 0 } }] }] };
let desktop = { available: true, preferences: { tray_enabled: true, widget_enabled: false, always_on_top: true,
  metrics: ['tokens', 'cost', 'lines'], show_usage_remaining: false, usage_remaining_bucket: 'codex' }, revision: 0, tray_active: true, settings_request: 0 };
let revisionOffset = 0, refreshes = 0, failNext = false, mergeRequests = [], mockJob;
let fakeSequence = 99998;

await context.route('**/api/*', async route => {
  const action = route.request().url().split('/').pop();
  if (action === 'usage_limits') return route.fulfill({ json: limits });
  if (action === 'refresh_usage_limits') { refreshes++; return route.fulfill({ json: { status: 'started' } }); }
  if (action === 'usage_limits_settings') {
    limits = { ...limits, enabled: route.request().postDataJSON().enabled };
    return route.fulfill({ json: { status: 'started' } });
  }
  if (action === 'desktop_state') return route.fulfill({ json: desktop });
  if (action === 'desktop_settings') {
    desktop.preferences = { ...desktop.preferences, ...route.request().postDataJSON() };
    desktop.revision++;
    return route.fulfill({ json: desktop });
  }
  if (action === 'widget_layout' || action === 'widget_command') return route.fulfill({ json: { status: 'accepted' } });
  if (action === 'merge_projects') {
    mergeRequests.push(route.request().postDataJSON());
    if (failNext) {
      const id = ++fakeSequence;
      mockJob = { running: false, message: 'Ready', progress: {}, error: null,
        queued: [{ id, message: 'Merging project groups', origin: 'user' }], completed: [] };
      return route.fulfill({ json: { status: 'queued', job_id: id, message: 'Merging project groups' } });
    }
  }
  if (action === 'dashboard' || action === 'widget_summary' || action === 'status') {
    const response = await route.fetch();
    const data = await response.json();
    data.revision += revisionOffset;
    if (action === 'status' && mockJob) Object.assign(data, mockJob);
    if (action !== 'status') { data.desktop = desktop; data.usage_limits = limits; data.demo = false; }
    return route.fulfill({ json: data });
  }
  return route.continue();
});
const page = await context.newPage({ viewport: { width: 1100, height: 800 } });
page.on('pageerror', error => errors.push(error.message));
const widget = await context.newPage({ viewport: { width: 240, height: 160 } });
widget.on('pageerror', error => errors.push(error.message));
try {
  await page.setViewportSize({ width: 1100, height: 800 });
  await widget.setViewportSize({ width: 240, height: 160 });
  await page.goto(url);
  await page.locator('.kpi').first().waitFor();
  // Overview shows the compact limits row; full allowance cards live on Accounts.
  const codexChip = page.locator('#limit-chip-codex');
  await codexChip.waitFor();
  assert.match(await codexChip.textContent(), /51% left/);
  assert.match(await codexChip.textContent(), /Weekly/);
  assert.match(await codexChip.getAttribute('aria-label'), /Weekly: 51% left, resets/);
  assert.match(await page.locator('#limits-row .burn-rate-tokens').textContent(), /12\.4K tokens\/min/);
  await codexChip.click();
  await page.locator('.nav-item[data-page="accounts"][aria-current="page"]').waitFor();
  await page.locator('.nav-item[data-page="overview"]').click();
  await page.locator('#limit-chip-codex').waitFor();
  await page.locator('[data-page=projects]').click();
  const choices = await page.locator('[data-select-project]').evaluateAll(inputs => inputs.map(i => ({ id: i.dataset.selectProject, name: i.getAttribute('aria-label').slice(7) })));
  assert.ok(choices.length >= 3, 'Start this check against a fresh demo index');
  const first = choices[0], second = choices[1];
  await page.locator('[data-select-project]').nth(0).check();
  await page.locator('[data-select-project]').nth(1).check();
  await page.locator('#project-search').fill(first.name);
  await page.getByRole('heading', { name: 'Your projects' }).click();
  assert.equal(await page.locator('[data-select-project]:checked').count(), 2);
  await page.setViewportSize({ width: 500, height: 700 });
  await page.locator('.table-scroll').evaluate(element => { element.scrollLeft = 120; });
  const scroll = await page.locator('.table-scroll').evaluate(element => element.scrollLeft);
  revisionOffset++;
  await page.waitForTimeout(2600);
  assert.equal(await page.locator('#project-search').inputValue(), first.name);
  assert.equal(await page.locator('[data-select-project]:checked').count(), 2);
  assert.equal(await page.locator('.table-scroll').evaluate(element => element.scrollLeft), scroll);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: resolve(output, 'narrow-dashboard.png'), fullPage: true });
  await page.setViewportSize({ width: 1100, height: 800 });
  await page.locator('#merge-selected').click();
  await page.locator('#merge-search').fill(second.name);
  await page.locator('#merge-destinations input').check();
  assert.match(await page.locator('#merge-preview').textContent(), new RegExp(`Retained name: ${second.name}`));
  assert.match(await page.locator('#merge-preview').textContent(), /Source groups \(1\)/);
  await page.screenshot({ path: resolve(output, 'merge-preview.png') });
  await page.locator('#merge-save').click();
  await page.locator('[role=dialog]').waitFor({ state: 'hidden' });
  await page.locator('#undo-project-merge').waitFor({ state: 'visible' });
  await page.waitForFunction(expected => document.querySelectorAll('[data-select-project]').length === expected, choices.length - 1);
  assert.deepEqual(new Set(mergeRequests[0].sources), new Set([first.id, second.id]));
  assert.equal(mergeRequests[0].target, second.id);
  assert.equal(await page.locator('[data-select-project]').count(), choices.length - 1);
  assert.equal(await page.locator('#project-search').inputValue(), first.name);
  await page.locator('#project-search').fill('');
  await page.getByRole('heading', { name: 'Your projects' }).click();
  assert.match(await page.locator('#project-merge-status').textContent(), /Merged/);
  await page.reload();
  await page.locator('[data-page=projects]').click();
  await page.locator('#undo-project-merge').waitFor({ state: 'visible' });
  await page.locator('#undo-project-merge').click();
  await page.waitForFunction(expected => document.querySelectorAll('[data-select-project]').length === expected, choices.length);
  assert.match(await page.locator('#project-merge-status').textContent(), /undone/);
  await page.reload();
  await page.locator('[data-page=projects]').click();
  assert.equal(await page.locator('#undo-project-merge').isHidden(), true);
  // Single-project action, queued/running feedback, no duplicate submissions,
  // and a failed merge with its draft available for retry.
  failNext = true;
  await page.locator('.merge-project').first().click();
  await page.locator('#merge-save').click();
  await page.waitForFunction(() => document.querySelector('#merge-feedback')?.textContent.includes('queued'));
  await page.locator('#merge-save').evaluate(button => { button.click(); button.click(); });
  assert.equal(mergeRequests.length, 2);
  mockJob = { ...mockJob, running: true, id: 99999, origin: 'user', cancelable: false, queued: [] };
  await page.waitForFunction(() => document.querySelector('#merge-feedback')?.textContent.includes('Merging'));
  mockJob = { ...mockJob, running: false, completed: [{ id: 99999, origin: 'user', message: 'Merging project groups', state: 'failed', error: 'Destination project is no longer indexed', result: null }] };
  await page.waitForFunction(() => document.querySelector('#merge-feedback')?.textContent.includes('no longer indexed'));
  assert.equal(await page.locator('#merge-save').isEnabled(), true);
  await page.keyboard.press('Escape');
  mockJob = undefined;
  // Closing a pending merge then opening Settings must keep that new draft
  // when the merge completes in the background.
  await page.locator('.merge-project').first().click();
  await page.locator('#merge-save').click();
  await page.waitForFunction(() => document.querySelector('#merge-feedback')?.textContent.includes('queued'));
  await page.keyboard.press('Escape');
  await page.locator('#settings-open').click();
  await page.locator('#device-label').fill('Unsaved label');
  const deferred = mergeRequests.at(-1);
  const destination = choices.find(p => p.id === deferred.target);
  mockJob = { ...mockJob, running: false, queued: [], completed: [{ id: fakeSequence, origin: 'user', message: 'Merging project groups', state: 'completed', error: null,
    result: { operation_id: 'simulated-operation', sources: [choices.find(p => p.id === deferred.sources[0])], target: destination, sessions: 1, identities: 1, completed_at: new Date().toISOString() } }] };
  await page.waitForFunction(() => document.querySelector('#project-merge-status')?.textContent.includes('Merged'));
  assert.equal(await page.locator('#device-label').inputValue(), 'Unsaved label');
  assert.equal(await page.locator('[role=dialog]').count(), 1);
  mockJob = undefined;
  // Allowance changes keep arriving in the Overview limits row while a settings draft is open.
  await page.keyboard.press('Escape');
  await page.locator('.nav-item[data-page="overview"]').click();
  await page.locator('#settings-open').click();
  await page.locator('#device-label').fill('Unsaved label');
  limits = { ...limits, stale: true, status: 'stale', error: 'Connection unavailable; retrying', error_code: 'connection' };
  await page.locator('#limit-chip-codex .allowance-stale').waitFor();
  assert.match(await page.locator('#limit-chip-codex').textContent(), /51% left/);
  assert.match(await page.locator('#limit-chip-codex').getAttribute('aria-label'), /Connection unavailable; retrying/);
  await page.keyboard.press('Escape');
  limits = { ...limits, stale: false, status: 'available', error: null, error_code: null,
    buckets: limits.buckets.map(b => b.id === 'codex' ? { ...b, windows: [{ ...b.windows[0], remaining_percent: 49, resets_at: now - 1 }] } : b) };
  // A passed reset never implies a refilled window.
  await page.waitForFunction(() => document.querySelector('#limit-chip-codex')?.textContent.includes('Awaiting reading'));
  assert.match(await page.locator('#limit-chip-codex').getAttribute('aria-label'), /Weekly: awaiting new reading/);
  assert.match(await page.locator('#limits-row .burn-rate-tokens').textContent(), /12\.4K tokens\/min/);
  await page.locator('#settings-open').click();
  await page.locator('#live-usage-enabled').uncheck();
  await page.waitForFunction(() => !document.querySelector('#limit-chip-codex'));
  await page.locator('#live-usage-enabled').check();
  await page.waitForFunction(() => !!document.querySelector('#limit-chip-codex'));
  await page.locator('[data-desktop=show_usage_remaining]').check();
  await page.waitForFunction(() => !document.querySelector('[data-desktop=show_usage_remaining]').disabled);
  assert.deepEqual(desktop.preferences.metrics, ['tokens', 'cost', 'lines']);
  await page.keyboard.press('Escape');
  await widget.goto(url + '/widget/index.html');
  await widget.locator('#widget-allowance .allowance-window').waitFor();
  assert.equal(await widget.locator('.burn-rate').count(), 0);
  await widget.locator('.allowance-bucket').selectOption('other');
  await widget.waitForFunction(() => document.querySelector('#widget-allowance')?.textContent.includes('83% remaining'));
  assert.equal(desktop.preferences.usage_remaining_bucket, 'other');
  const box = await widget.locator('#widget').boundingBox();
  assert.equal(box.width, 240);
  await widget.setViewportSize({ width: 240, height: Math.ceil(box.height) });
  assert.equal(await widget.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight), true);
  await widget.screenshot({ path: resolve(output, 'widget-allowance.png') });
  limits = { ...limits, buckets: [], status: 'unavailable', last_success_at: null, error: 'Sign in to Codex with ChatGPT, then refresh allowance.' };
  await widget.waitForFunction(() => document.querySelector('#widget-allowance')?.textContent.includes('Sign in to Codex'));
  await page.waitForFunction(() => document.querySelector('#limit-chip-codex')?.getAttribute('aria-label').includes('Sign in to Codex'));
  assert.match(await page.locator('#limit-chip-codex').textContent(), /Unavailable/);
  assert.deepEqual(errors, []);
  console.log('Merge/allowance browser checks passed: bulk + single merge, selected destination, search/selection/scroll retention, feedback, duplicate prevention, undo, live cached updates, compact limits row stale/reset/unavailable states and Accounts link, widget buckets, narrow dashboard and 240px widget.');
} finally { await browser.close(); }
