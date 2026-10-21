/** Dollar burn display and refresh checks against an isolated demo server. */
import { chromium } from '../frontend/node_modules/@playwright/test/index.mjs';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
import { accountFixture } from './account-ui-fixture.mjs';

const [url, output = '.local-data/cost-burn-ui'] = process.argv.slice(2);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const context = await browser.newContext({ viewport: { width: 1100, height: 800 } });
const now = Math.floor(Date.now() / 1000), errors = [];
const rate = (value, extra = {}) => ({ value, status: 'available', observed_seconds: 300, updated_at: now, ...extra });
const cost = (value, extra = {}) => rate(value, { total_tokens: 62000, priced_tokens: 62000, ...extra });
const accounts = { enabled: true, allowed: true, error: null, login: { status: 'idle' },
  token_burn_rate: rate(12400), cost_burn_rate: cost(.53),
  accounts: [accountFixture('current', 'Current Codex'), accountFixture('a'.repeat(32), 'Research')] };
const limits = () => ({ ...accounts.accounts[0].allowance,
  token_burn_rate: accounts.token_burn_rate, cost_burn_rate: accounts.cost_burn_rate });
const desktop = { available: true, preferences: { tray_enabled: true, widget_enabled: true,
  always_on_top: true, metrics: ['tokens', 'cost', 'lines'], show_usage_remaining: true,
  usage_remaining_bucket: 'codex', widget_account_ids: ['current'], widget_account_buckets: {} },
  revision: 1, tray_active: true, settings_request: 0 };

await context.route('**/api/*', async route => {
  const action = route.request().url().split('/').pop();
  if (action === 'live_status') {
    const response = await route.fetch(), value = await response.json();
    return route.fulfill({json: {...value, ready: true, accounts, usage_limits: limits(), desktop}});
  }
  if (action === 'accounts') return route.fulfill({ json: accounts });
  if (action === 'usage_limits') return route.fulfill({ json: limits() });
  if (action === 'desktop_state') return route.fulfill({ json: desktop });
  if (['widget_layout', 'widget_command'].includes(action)) return route.fulfill({ json: { status: 'accepted' } });
  if (['dashboard', 'widget_summary'].includes(action)) {
    const response = await route.fetch(), data = await response.json();
    return route.fulfill({ json: { ...data, demo: false, accounts, usage_limits: limits(), desktop } });
  }
  return route.continue();
});

const page = await context.newPage();
page.on('pageerror', error => errors.push(error.message));
try {
  await page.goto(url);
  // Overview's compact limits row shows the value; Accounts keeps the full row.
  const dashboardRate = page.locator('#limits-row .burn-rate-cost');
  await dashboardRate.waitFor();
  assert.match(await dashboardRate.innerText(), /\$0\.53\/min/);
  assert.match(await dashboardRate.getAttribute('aria-label'), /USD per minute, not a subscription bill/);
  await dashboardRate.focus();
  accounts.cost_burn_rate = cost(.73);
  await page.waitForFunction(() => document.querySelector('#limits-row .burn-rate-cost')?.textContent.includes('$0.73/min'));
  assert.equal(await page.evaluate(() => document.activeElement?.id), 'limits-burn-cost', 'live updates keep focus on the rate');
  await page.locator('#limits-row').screenshot({ path: resolve(output, 'dashboard-dollar-burn.png') });

  await page.locator('[data-page=accounts]').click();
  const accountRate = page.locator('#accounts-token-burn .burn-rate-cost');
  await accountRate.waitFor();
  assert.match(await accountRate.innerText(), /Local dollar burn.*\$0\.73\/min/);
  assert.match(await accountRate.innerText(), /5m estimate.*API-equivalent.*100% priced/);
  assert.equal(await page.locator('#accounts-view .burn-rate-cost').count(), 1);
  assert.equal(await page.locator('.account-card .burn-rate-cost').count(), 0);
  await accountRate.focus();
  accounts.cost_burn_rate = cost(.19, { total_tokens: 1000, priced_tokens: 600, partial: true });
  await page.waitForFunction(() => document.querySelector('#accounts-token-burn .burn-rate-cost')?.textContent.includes('60% priced'));
  assert.equal(await accountRate.evaluate(node => document.activeElement === node), true);
  assert.match(await accountRate.innerText(), /\$0\.19\/min.*Partial/);
  assert.match(await accountRate.getAttribute('title'), /600 of 1,000 tokens.*priced subtotal/);

  accounts.cost_burn_rate = cost(null, { status: 'unavailable', priced_tokens: 0, partial: true });
  await page.waitForFunction(() => document.querySelector('#accounts-token-burn .burn-rate-cost')?.textContent.includes('Unavailable'));
  assert.match(await accountRate.innerText(), /0% priced/);
  assert.doesNotMatch(await accountRate.innerText(), /\$0\.00/);
  accounts.cost_burn_rate = cost(0, { total_tokens: 0, priced_tokens: 0 });
  await page.waitForFunction(() => document.querySelector('#accounts-token-burn .burn-rate-cost')?.textContent.includes('$0.00/min'));
  assert.match(await accountRate.innerText(), /No recent usage/);
  accounts.cost_burn_rate = cost(.00003);
  await page.waitForFunction(() => document.querySelector('#accounts-token-burn .burn-rate-cost')?.textContent.includes('<$0.01/min'));
  assert.match(await accountRate.getAttribute('title'), /0\.00003 USD\/min/);
  accounts.cost_burn_rate = cost(.53, { status: 'stale' });
  await page.waitForFunction(() => document.querySelector('#accounts-token-burn .burn-rate-cost')?.dataset.status === 'stale');
  assert.match(await accountRate.innerText(), /\$0\.53\/min.*Stale/);
  accounts.cost_burn_rate = rate(null, { status: 'collecting', observed_seconds: 0 });
  await page.waitForFunction(() => document.querySelector('#accounts-token-burn .burn-rate-cost')?.textContent.includes('Waiting for indexing'));

  const coverage = { state: 'partial', checked_at: now, reasons: [
    { code: 'file_error', label: 'File unreadable', count: 1, source_id: 'local', retry_at: now + 30 },
  ] };
  accounts.token_burn_rate = rate(12400, { partial: true, coverage });
  accounts.cost_burn_rate = cost(.53, { partial: true, coverage });
  await page.waitForFunction(() => document.querySelector('#accounts-token-burn')?.textContent.includes('File unreadable'));
  const coverageButton = accountRate.locator('[data-burn-sources]');
  await coverageButton.focus();
  accounts.cost_burn_rate = cost(.54, { partial: true, coverage });
  await page.waitForFunction(() => document.querySelector('#accounts-token-burn .burn-rate-cost')?.textContent.includes('$0.54/min'));
  assert.equal(await coverageButton.evaluate(node => document.activeElement === node), true);
  await coverageButton.click();
  await page.locator('#add-source').waitFor();
  await page.locator('[data-page=overview]').click();
  await dashboardRate.waitFor();
  await page.waitForFunction(() => document.querySelector('#limits-burn-cost')?.textContent.includes('File unreadable'));
  assert.match(await dashboardRate.innerText(), /Partial.*File unreadable/s);
  const compactCoverage = dashboardRate.locator('[data-burn-sources]');
  await compactCoverage.focus();
  accounts.cost_burn_rate = cost(.55, { partial: true, coverage });
  await page.waitForFunction(() => document.querySelector('#limits-burn-cost')?.textContent.includes('$0.55/min'));
  assert.equal(await compactCoverage.evaluate(node => document.activeElement === node), true);
  await page.setViewportSize({ width: 390, height: 800 });
  assert.equal(await dashboardRate.evaluate(node => node.scrollWidth <= node.clientWidth + 1), true);
  await page.locator('#limits-row').screenshot({ path: resolve(output, 'dashboard-coverage-reasons.png') });
  await page.locator('[data-page=accounts]').click();
  await accountRate.waitFor();
  accounts.token_burn_rate = rate(12400);
  accounts.cost_burn_rate = cost(.53);
  await page.setViewportSize({ width: 390, height: 800 });
  await page.waitForFunction(() => document.querySelector('#accounts-token-burn .burn-rate-cost')?.textContent.includes('$0.53/min'));
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.locator('#accounts-token-burn').screenshot({ path: resolve(output, 'accounts-dollar-burn-mobile.png') });
  await page.locator('[data-page=overview]').click();
  await dashboardRate.waitFor();
  // Check the changed row itself: existing overview charts can overflow at 390px.
  assert.equal(await page.locator('#limits-row').evaluate(root => {
    const rows = [root, ...root.querySelectorAll('.limit-chip, .limit-burn, .burn-rate')];
    return rows.every(row => row.getBoundingClientRect().right <= innerWidth
      && row.scrollWidth <= row.clientWidth + 1);
  }), true);
  await page.locator('#limits-row').screenshot({ path: resolve(output, 'dashboard-dollar-burn-mobile.png') });

  const widget = await context.newPage();
  widget.on('pageerror', error => errors.push(error.message));
  await widget.setViewportSize({ width: 240, height: 500 });
  await widget.goto(url + '/widget/index.html');
  await widget.locator('#widget').waitFor();
  assert.equal(await widget.locator('.burn-rate').count(), 0);
  assert.deepEqual(errors, []);
  console.log('Dollar burn UI passed: USD/min, pricing coverage, unavailable/idle/tiny/stale/collecting states, scope, focus retention, mobile layouts and compact widget.');
} finally { await browser.close(); }
