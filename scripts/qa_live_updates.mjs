import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { mkdir } from 'node:fs/promises';
import assert from 'node:assert/strict';

const [url, output = '.local-data/live-update-ui'] = process.argv.slice(2);
if (!url) throw new Error('Pass the URL of an isolated demo server.');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const context = await browser.newContext();
const page = await context.newPage();
const errors = [];
page.on('pageerror', error => errors.push(error.message));
let fixture, sequence = 0, revision = 1, requested;
let job = { running: false, message: 'Ready', origin: 'automatic', progress: {}, error: null, queued: [], completed: [] };

function automatic() {
  job = { ...job, id: ++sequence, origin: 'automatic', running: true, cancelable: true,
    message: 'Reading session updates', progress: { files: 6927, bytes_read: 12000, changed_files: 2 } };
}
function complete(state = 'completed', error = null) {
  const completion = { id: job.id, origin: job.origin, message: job.message, state, error, result: {} };
  job = { ...job, running: false, error, completed: [...job.completed, completion] };
}
function startQueued() {
  complete('cancelled');
  const next = job.queued.shift();
  job = { ...job, ...next, origin: 'user', running: true, cancelable: false, error: null, progress: {} };
}
function applyRequested() {
  if (requested.action === 'settings') {
    fixture.settings = { device_label: requested.args.device_label, assumed_fast_percent: requested.args.assumed_fast_percent };
    fixture.timezone = requested.args.timezone;
  } else if (requested.action === 'source_enabled') {
    fixture.sources.find(source => source.id === requested.args.id).enabled = Number(requested.args.enabled);
  }
  revision++;
  complete();
}

await context.route('**/api/*', async route => {
  const action = route.request().url().split('/').pop();
  if (action === 'dashboard') {
    if (!fixture) fixture = await (await route.fetch()).json();
    // Match the server's applied-filter contract, including custom date bounds.
    const filters = route.request().postDataJSON();
    const date_bounds = filters.range === 'custom'
      ? { start: filters.start, end: filters.end } : fixture.date_bounds;
    return route.fulfill({ json: { ...structuredClone(fixture), filters, date_bounds, desktop: { available: false }, revision, job: { ...job, revision } } });
  }
  if (action === 'status') return route.fulfill({ json: { ...job, revision } });
  if (action === 'cancel') {
    complete('cancelled');
    return route.fulfill({ json: { status: 'cancelling' } });
  }
  if (['settings', 'source_enabled', 'refresh'].includes(action)) {
    const args = route.request().postDataJSON();
    requested = { action, args };
    const id = ++sequence;
    const message = action === 'settings' ? 'Updating timezone and pricing'
      : action === 'source_enabled' ? 'Updating included sources' : 'Rebuilding index';
    const queued = job.running;
    if (queued) job.queued.push({ id, message, origin: 'user' });
    else job = { ...job, id, message, running: true, origin: 'user', cancelable: action === 'refresh', progress: {}, error: null };
    return route.fulfill({ json: { status: queued ? 'queued' : 'started', job_id: id, message } });
  }
  return route.continue();
});

async function tick() {
  await page.clock.runFor(2100);
}

try {
  await page.clock.install();
  await page.setViewportSize({ width: 1300, height: 760 });
  await page.goto(url);
  await page.locator('[data-page="sources"]').click();
  const controls = page.locator('.source-actions');
  const refresh = page.locator('#refresh');
  const banner = page.locator('#job-banner');
  const original = await controls.boundingBox();
  const button = await refresh.boundingBox();
  for (let i = 0; i < 4; i++) {
    automatic();
    await tick();
    await expect(refresh).toHaveAttribute('aria-label', 'Updating usage');
    await expect(banner).toBeHidden();
    await expect.poll(() => controls.boundingBox()).toEqual(original);
    await expect.poll(() => refresh.boundingBox()).toEqual(button);
    complete(); revision++;
    await tick();
    await expect(refresh).toHaveAttribute('aria-busy', 'false');
    await expect(banner).toBeHidden();
    await expect.poll(() => controls.boundingBox()).toEqual(original);
  }
  automatic();
  await tick();
  await expect(refresh).toHaveClass(/refreshing/);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  assert.equal(await refresh.locator('svg').evaluate(el => getComputedStyle(el).animationName), 'none');
  await page.screenshot({ path: `${output}/automatic.png` });
  await page.emulateMedia({ reducedMotion: 'no-preference' });

  await page.locator('#settings-open').click();
  const dialog = page.locator('[role="dialog"]');
  await page.locator('#device-label').fill('Unsaved label');
  await page.locator('#timezone').fill('UTC');
  await page.locator('#fast-share').fill('42');
  await page.locator('#device-label').focus();
  await page.locator('#device-label').evaluate(el => el.setSelectionRange(2, 7));
  await dialog.evaluate(el => el.dataset.identity = 'keep-editor');
  fixture.sources[0].segments = 42;
  for (let i = 0; i < 3; i++) {
    complete(); revision++;
    await tick();
    automatic();
    await tick();
    await expect(dialog).toHaveAttribute('data-identity', 'keep-editor');
    await expect(page.locator('#device-label')).toHaveValue('Unsaved label');
    await expect(page.locator('#timezone')).toHaveValue('UTC');
    await expect(page.locator('#fast-share')).toHaveValue('42');
    assert.deepEqual(await page.locator('#device-label').evaluate(el => [el === document.activeElement, el.selectionStart, el.selectionEnd]), [true, 2, 7]);
  }
  await page.keyboard.press('Escape');
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('.source-facts strong').first()).toHaveText('42');

  await page.locator('#settings-open').click();
  await page.locator('#device-label').fill('Saved during a scan');
  await page.locator('#timezone').fill(' UTC ');
  await page.locator('#fast-share').fill('15');
  await page.locator('#settings-save').click();
  await expect(page.locator('#settings-save')).toHaveText('Queued');
  await expect(dialog).toBeVisible();
  await expect(banner).toContainText('Queued');
  assert.equal(requested.action, 'settings');
  assert.equal(requested.args.timezone, 'UTC');
  startQueued();
  await tick();
  await expect(page.locator('#settings-save')).toHaveText('Saving…');
  applyRequested();
  await tick();
  await expect(dialog).toHaveCount(0);
  await expect(page.locator('#toast')).toHaveText('Settings saved.');
  await page.locator('#settings-open').click();
  await expect(page.locator('#device-label')).toHaveValue('Saved during a scan');
  await expect(page.locator('#timezone')).toHaveValue('UTC');
  await expect(page.locator('#fast-share')).toHaveValue('15');
  await page.keyboard.press('Escape');

  automatic();
  await tick();
  const included = page.locator('[data-enabled]').first();
  await included.uncheck();
  await expect(included).toBeDisabled();
  await expect(banner).toContainText('Queued');
  startQueued(); revision++;
  await tick();
  await expect(page.locator('[data-enabled]').first()).toBeDisabled();
  await expect(page.locator('[data-enabled]').first()).not.toBeChecked();
  applyRequested();
  await tick();
  await expect(page.locator('[data-enabled]').first()).toBeEnabled();
  await expect(page.locator('[data-enabled]').first()).not.toBeChecked();

  await page.locator('#settings-open').click();
  await page.locator('#device-label').fill('Keep this after a failure');
  await page.locator('#settings-save').click();
  await expect(page.locator('#settings-save')).toHaveText('Saving…');
  complete('failed', 'Simulated settings failure');
  await tick();
  await expect(dialog).toBeVisible();
  await expect(page.locator('#device-label')).toHaveValue('Keep this after a failure');
  await expect(page.locator('#settings-save')).toBeEnabled();
  await expect(page.locator('#toast')).toHaveText('Simulated settings failure');
  await page.keyboard.press('Escape');

  await page.locator('#rebuild-index').click();
  await expect(banner).toBeVisible();
  await expect(banner).toContainText('Rebuilding index');
  await page.locator('#cancel-job').click();
  await tick();
  await expect(banner).toBeHidden();

  await page.locator('[data-page="projects"]').click();
  await page.locator('#project-search').fill('little');
  const visible = await page.locator('tbody tr:visible').count();
  automatic(); revision++;
  await tick();
  await expect(page.locator('#project-search')).toHaveValue('little');
  await page.locator('h1').click();
  await expect(page.locator('#project-search')).toHaveValue('little');
  assert.equal(await page.locator('tbody tr:visible').count(), visible);
  complete();

  await page.locator('[data-page="overview"]').click();
  await page.locator('#filter-range').selectOption('custom');
  await page.locator('#date-start').fill('2026-09-01');
  await page.locator('#date-end').fill('2026-10-08');
  await page.locator('h1').click();
  automatic(); revision++;
  await tick();
  await expect(page.locator('#date-start')).toHaveValue('2026-09-01');
  await expect(page.locator('#date-end')).toHaveValue('2026-10-08');
  await page.locator('#date-apply').click();
  await expect(page.locator('#date-start')).toHaveValue('2026-09-01');
  await page.evaluate(() => window.scrollTo(0, 300));
  const scroll = await page.evaluate(() => window.scrollY);
  complete(); revision++;
  await tick();
  assert.equal(await page.evaluate(() => window.scrollY), scroll);
  assert.deepEqual(errors, []);
  console.log('Live update UI checks passed: stable layout, reduced motion, editing, queue/completion feedback, source changes, failures, manual progress/cancel, search, dates and scroll.');
} finally {
  await browser.close();
}
