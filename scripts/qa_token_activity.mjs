import './qa_token_activity_data.mjs';
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';

const [url, report, output = '.local-data/token-activity-ui'] = process.argv.slice(2);
if (!url) throw new Error('Pass an isolated demo server URL, and optionally an exported report path and screenshot directory.');
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const page = await browser.newPage({ viewport: { width: 1500, height: 1000 }, hasTouch: true });
const errors = [];
page.on('pageerror', error => errors.push(error.message));
let fixture = null, latest = null, revision = 0;
await page.route('**/api/dashboard', async route => {
  const response = await route.fetch(), data = await response.json();
  latest = { ...data, ...structuredClone(fixture || {}), revision: data.revision + revision };
  await route.fulfill({ response, json: latest });
});
await page.route('**/api/status', async route => {
  const response = await route.fetch(), data = await response.json();
  await route.fulfill({ response, json: { ...data, revision: data.revision + revision } });
});
const panel = page.locator('#token-activity');
async function filtered(id, value) {
  const response = page.waitForResponse('**/api/dashboard');
  await page.locator(id).selectOption(value);
  await response;
  const unavailable = latest.coverage.tokens?.state === 'unavailable';
  await expect(panel).toHaveAttribute('data-total-tokens', unavailable ? '' : String(latest.summary.total_tokens));
  if (unavailable) {
    await expect(panel.locator('.token-empty')).toHaveText('Token counters unavailable in this range.');
    await expect(panel.locator('.token-day, canvas')).toHaveCount(0);
  }
}
async function mode(value) {
  await page.locator(`#token-mode-${value}`).click();
  await expect(panel).toHaveAttribute('data-mode', value);
  await expect(page.locator(`#token-mode-${value}`)).toHaveAttribute('aria-pressed', 'true');
}
async function screenshot(name) {
  await page.mouse.move(0, 0);
  await page.keyboard.press('Escape');
  await panel.screenshot({ path: resolve(output, `${name}.png`) });
}

try {
  await page.clock.install();
  await page.goto(url);
  await expect(panel).toHaveAttribute('data-mode', 'daily');
  const base = structuredClone(latest);
  assert.equal(await page.locator('.token-day').count(), Math.round((Date.parse(base.date_bounds.end) - Date.parse(base.date_bounds.start)) / 86400000) + 1);
  await expect(panel).toHaveAttribute('data-total-tokens', String(base.summary.total_tokens));
  await expect(page.locator('#activity-chart')).toBeVisible();
  await screenshot('daily');
  await mode('weekly'); await expect(page.locator('#token-activity-chart')).toBeVisible(); await screenshot('weekly');
  await page.locator('[data-page="usage"]').click();
  await page.locator('[data-page="overview"]').click();
  await expect(panel).toHaveAttribute('data-mode', 'weekly');
  await panel.evaluate(element => { element.dataset.qaRender = 'before'; });
  revision++;
  await page.clock.runFor(2100);
  await expect(panel).not.toHaveAttribute('data-qa-render', 'before');
  await expect(panel).toHaveAttribute('data-mode', 'weekly');
  await mode('cumulative'); await screenshot('cumulative');

  // Real filtered totals, rather than an account lifetime counter, feed the panel.
  for (const [id, value] of [
    ['#filter-project', base.options.projects[0].id], ['#filter-model', base.options.models[0]],
    ['#filter-source', base.sources[0].id], ['#filter-range', '30'],
    ['#filter-project', ''], ['#filter-model', ''], ['#filter-source', ''], ['#filter-range', '7'],
  ]) {
    await filtered(id, value);
    await expect(panel).toHaveAttribute('data-mode', 'cumulative');
  }
  const applied = await panel.locator('.panel-heading p').textContent();
  await page.locator('#filter-range').selectOption('custom');
  await page.locator('#date-start').fill('2026-01-01');
  await page.locator('#date-end').fill('2026-01-04');
  await expect(panel.locator('.panel-heading p')).toHaveText(applied);
  await mode('daily');
  await expect(panel.locator('.panel-heading p')).toHaveText(applied);
  await page.locator('#date-apply').click();
  await expect(page.locator('.token-day')).toHaveCount(0);
  await expect(panel.locator('.panel-heading p')).toContainText('Jan 1, 2026 – Jan 4, 2026');
  await expect(page.locator('.token-empty')).toHaveText('Token counters unavailable in this range.');
  await expect(panel).toHaveAttribute('data-total-tokens', '');

  // Check exact tooltips, touch, roving focus, and stable focus/scroll on refresh.
  fixture = {
    coverage: { ...base.coverage, tokens: { ...base.coverage.tokens, state: 'complete' } },
    date_bounds: { start: '2026-01-01', end: '2026-12-31' },
    filters: { ...base.filters, range: 'all' },
    timeline: [{ day: '2026-10-05', tokens: 1250000, cost: 0, prompts: 1, lines: 0 }],
    summary: { ...base.summary, total_tokens: 1250000 },
  };
  await page.reload(); await expect(panel).toHaveAttribute('data-mode', 'daily');
  const day = page.locator('#token-day-2026-10-05'), tooltip = page.locator('#token-activity-tooltip');
  await day.hover(); await expect(tooltip).toContainText('1,250,000 tokens');
  await expect(tooltip).toContainText('Oct 5, 2026');
  await day.tap(); await expect(day).toBeFocused(); await expect(tooltip).toBeVisible();
  await page.keyboard.press('ArrowRight'); await expect(page.locator('#token-day-2026-10-12')).toBeFocused();
  await expect(tooltip).toContainText('0 tokens');
  await page.keyboard.press('ArrowUp'); await expect(page.locator('#token-day-2026-10-11')).toBeFocused();
  await page.keyboard.press('Home'); await expect(page.locator('#token-day-2026-01-01')).toBeFocused();
  await page.keyboard.press('End'); await expect(page.locator('#token-day-2026-12-31')).toBeFocused();
  await page.keyboard.press('Escape'); await expect(tooltip).toBeHidden();
  await page.setViewportSize({ width: 500, height: 850 });
  const scroll = page.locator('#token-calendar-scroll-2026');
  await scroll.evaluate(element => { element.scrollLeft = 600; });
  await day.evaluate(element => element.focus({ preventScroll: true }));
  const left = await scroll.evaluate(element => element.scrollLeft);
  assert(left > 0);
  fixture.timeline[0].tokens = 1500000; fixture.summary.total_tokens = 1500000; revision++;
  await page.clock.runFor(2100);
  await expect(day).toHaveAttribute('data-tokens', '1500000');
  await expect(day).toBeFocused();
  assert.equal(await scroll.evaluate(element => element.scrollLeft), left);
  await expect(tooltip).toContainText('1,500,000 tokens');
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await screenshot('narrow-calendar');
  await page.keyboard.press('Home');
  await expect(tooltip).toBeVisible(); await expect(tooltip).toContainText('Jan 1, 2026');
  await page.keyboard.press('End');
  await expect(tooltip).toBeVisible(); await expect(tooltip).toContainText('Dec 31, 2026');
  await page.locator('#token-mode-weekly').focus(); await page.keyboard.press('Enter');
  await expect(panel).toHaveAttribute('data-mode', 'weekly');
  await expect(page.locator('#token-mode-weekly')).toBeFocused();
  await screenshot('narrow-weekly');
  await mode('cumulative'); await screenshot('narrow-cumulative');
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));

  fixture = {
    ...fixture, date_bounds: { start: '2025-12-29', end: '2026-01-06' },
    timeline: [{ day: '2025-12-31', tokens: 100 }, { day: '2026-01-01', tokens: 25 }],
    summary: { ...base.summary, total_tokens: 125 },
  };
  await page.setViewportSize({ width: 1500, height: 1000 });
  await page.reload(); await expect(page.locator('.token-year')).toHaveCount(2);
  await expect(page.locator('#token-day-2025-12-31')).toHaveAttribute('data-level', '4');
  await expect(page.locator('#token-day-2026-01-01')).toHaveAttribute('data-level', '1');
  await expect(page.locator('.token-day')).toHaveCount(9);
  assert.equal(await page.locator('.token-padding[tabindex]').count(), 0);
  await screenshot('year-boundary');
  fixture = { ...fixture, date_bounds: { start: null, end: '2026-10-09' }, timeline: [], summary: { ...base.summary, total_tokens: 0 } };
  await page.reload(); await expect(page.locator('.token-empty')).toBeVisible();
  for (const value of ['weekly', 'cumulative', 'daily']) {
    await mode(value);
    await expect(panel).toHaveAttribute('data-total-tokens', '0');
    await expect(page.locator('.token-empty')).toHaveText('No token activity in this range.');
  }
  // Unavailable counters stay distinct from recorded zeroes in every view.
  const recordedCoverage = fixture.coverage;
  fixture = { ...fixture, coverage: { ...base.coverage, tokens: { ...base.coverage.tokens, state: 'unavailable' } } };
  await page.reload();
  for (const value of ['weekly', 'cumulative', 'daily']) {
    await mode(value);
    await expect(panel).toHaveAttribute('data-total-tokens', '');
    await expect(page.locator('.token-empty')).toHaveText('Token counters unavailable in this range.');
    await expect(panel.locator('.token-day, canvas')).toHaveCount(0);
  }
  fixture.coverage = recordedCoverage;
  fixture = { ...fixture, date_bounds: { start: '2026-10-09', end: '2026-10-09' }, timeline: [{ day: '2026-10-09', tokens: 9876543210 }], summary: { ...base.summary, total_tokens: 9876543210 } };
  await page.reload(); await expect(page.locator('.token-day')).toHaveCount(1);
  await page.locator('.token-day').focus(); await expect(tooltip).toContainText('9,876,543,210 tokens');
  for (const value of ['weekly', 'cumulative']) { await mode(value); await expect(page.locator('#token-activity-chart')).toBeVisible(); }

  if (report) {
    const external = [];
    page.on('request', request => { if (/^https?:/.test(request.url())) external.push(request.url()); });
    await page.goto(pathToFileURL(resolve(report)).href);
    await expect(panel).toHaveAttribute('data-mode', 'daily');
    await expect(page.locator('#filter-range')).toBeDisabled();
    for (const value of ['weekly', 'cumulative', 'daily']) await mode(value);
    await page.locator('.token-day').first().focus(); await expect(tooltip).toBeVisible();
    assert.deepEqual(external, []);
  }
  assert.deepEqual(errors, []);
  console.log('Token activity UI checks passed: three modes, filters, drafts, touch/tooltips, keyboard, refresh retention, narrow layouts, empty/single-day views, and offline report.');
} finally { await browser.close(); }
