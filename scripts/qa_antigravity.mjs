import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { uiTestServer } from './ui-test-server.mjs';

const directory = resolve(process.argv[2]);
const fixtures = JSON.parse(await readFile(resolve(directory, 'dashboard-fixtures.json')));
const widget = JSON.parse(await readFile(resolve(directory, 'widget-fixture.json')));
const sample = JSON.parse(await readFile('tests/fixtures/antigravity-usage-1.3.5.json'));
const now = Date.now() / 1000;
const profile = {
  provider: 'antigravity', label: 'Antigravity · local profile', profile: 'local', identity_verified: false,
  source: 'Antigravity CLI /usage', status: 'available', received_at: now,
  check: { enabled: true, allowed: true, refreshing: false, status: 'available', last_success_at: now, error: null },
  buckets: sample.command.data.groups.flatMap(group => group.buckets.map(row => ({
    id: row.id, kind: row.window === 'weekly' ? 'seven_day' : 'five_hour', scope_label: group.name,
    remaining_percent: row.remaining_fraction * 100, resets_at: now + 3600,
    unit: 'percent', used: null, limit: null, stale: false,
  }))),
};
for (const data of Object.values(fixtures)) {
  data.demo = false;
  data.settings.antigravity_usage_enabled = true;
  data.provider_allowances = [profile];
}
widget.provider_allowances = [profile];
const server = await uiTestServer();
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const actions = [], errors = [];
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/*', async route => {
    const action = new URL(route.request().url()).pathname.split('/').pop();
    const args = route.request().postDataJSON();
    actions.push(action);
    let value = {};
    if (action === 'dashboard') value = { ...fixtures[args.provider || ''], filters: args };
    if (action === 'provider_allowances') value = [profile];
    if (action === 'status') value = { ...fixtures[''].job, revision: fixtures[''].revision };
    if (action === 'accounts') value = { enabled: false, allowed: false, accounts: [], login: { status: 'idle' } };
    if (action === 'widget_summary') value = widget;
    await route.fulfill({ json: value });
  });
  await page.goto(server.url);
  // Overview: one compact chip with the tightest window; full card on Accounts.
  const chip = page.locator('#limit-chip-antigravity');
  await expect(chip).toContainText('0% left');
  await expect(chip).toHaveAttribute('data-tone', 'critical');
  await expect(chip).toHaveAttribute('aria-label', /Weekly · Gemini Models: .*left/);
  await page.locator('.nav-item[data-page="accounts"]').click();
  const card = page.locator('#provider-allowance-cards [data-provider="antigravity"]');
  await expect(card).toContainText('Weekly · Gemini Models');
  await expect(card).toContainText('5-hour · Claude and GPT models');
  await expect(card).toContainText('0% remaining');
  await expect(card).toContainText('via Antigravity CLI /usage');
  await card.locator('[data-provider-usage-refresh]').click();
  await expect.poll(() => actions.filter(a => a === 'refresh_antigravity_usage').length).toBe(1);
  assert(!actions.includes('refresh_claude_usage'));
  await page.locator('#settings-open').click();
  await expect(page.locator('#antigravity-usage-enabled')).toBeChecked();
  await expect(page.locator('[role="dialog"]')).toContainText('read-only');
  await page.keyboard.press('Escape');
  await page.locator('[data-page="sources"]').click();
  await page.locator('#add-source').click();
  await expect(page.locator('#source-provider option[value="antigravity_legacy"]')).toHaveCount(0);
  await page.keyboard.press('Escape');
  await page.locator('[data-page="overview"]').click();
  await page.screenshot({ path: resolve(directory, 'antigravity-dashboard.png'), fullPage: true });
  profile.received_at = now - 1000;
  profile.buckets[0].resets_at = now - 1;
  profile.buckets.forEach(bucket => { bucket.stale = true; });
  await expect(chip).toContainText('Stale');
  await page.locator('.nav-item[data-page="accounts"]').click();
  await expect(card).toContainText('Stale');
  await expect(card).toContainText('Awaiting reading');
  await page.goto(`${server.url}/widget/index.html`);
  await expect(page.locator('#provider-allowances')).toContainText('Gemini Models');
  await expect(page.locator('#provider-allowances')).toContainText('Awaiting reading');
  await expect(page.locator('#provider-allowances')).toContainText('Stale');
  await page.locator('#widget-refresh-all').click();
  await expect.poll(() => actions.filter(a => a === 'refresh_antigravity_usage').length).toBe(2);
  await page.setViewportSize({ width: 260, height: 800 });
  await page.screenshot({ path: resolve(directory, 'antigravity-widget.png'), fullPage: true });
  assert.deepEqual(errors, []);
  console.log('Antigravity UI passed: grouped quotas, explicit zero, official source, Settings, provider-specific refresh, retired archive setup and stale/reset dashboard/widget states.');
} finally {
  await browser.close(); server.close();
}
