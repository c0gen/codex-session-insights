import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
import { accountIds as ids, accountFixture } from './account-ui-fixture.mjs';

const [url, output = '.local-data/account-dedup-ui'] = process.argv.slice(2);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const errors = [], actions = [];
let switched = false;
const accounts = { allowed: true, enabled: true, error: null, login: { status: 'idle' }, accounts: [
  accountFixture('current', 'Current Codex'), accountFixture(ids.saved, 'Saved personal'),
  accountFixture(ids.work, 'Work', 40), accountFixture(ids.duplicate, 'Another personal sign-in') ] };
let desktop = { available: true, revision: 1, tray_active: true, error: null, settings_request: 0, preferences: {
  metrics: ['tokens'], tray_enabled: true, widget_enabled: true, always_on_top: true, show_usage_remaining: true,
  usage_remaining_bucket: 'codex', widget_account_ids: [ids.saved, 'current', ids.duplicate, ids.work], widget_account_buckets: {},
} };
function grouped() {
  const personal = accounts.accounts.filter(account => account.id !== ids.work && (!switched || account.id !== 'current'));
  const representative = personal.find(account => account.enabled && account.id === 'current') || personal.find(account => account.enabled) || personal.find(account => account.id === 'current') || personal[0];
  return { ...accounts, accounts: accounts.accounts.map(account => ({ ...account,
    display_id: personal.includes(account) ? representative.id : account.id })) };
}
async function routes(context) {
  await context.route('**/api/*', async route => {
    const action = route.request().url().split('/').pop(), args = route.request().postDataJSON();
    if (action === 'accounts') return route.fulfill({ json: grouped() });
    if (action === 'desktop_state') return route.fulfill({ json: desktop });
    if (action === 'desktop_settings') {
      desktop = { ...desktop, revision: desktop.revision + 1, preferences: { ...desktop.preferences, ...args } };
      return route.fulfill({ json: desktop });
    }
    if (action.startsWith('account_')) {
      actions.push({ action, args });
      if (action === 'account_settings') Object.assign(accounts.accounts.find(account => account.id === args.id), args);
      if (action === 'account_remove') accounts.accounts = accounts.accounts.filter(account => account.id !== args.id);
      return route.fulfill({ json: { status: 'started' } });
    }
    if (action === 'widget_layout' || action === 'widget_command') return route.fulfill({ json: { status: 'accepted' } });
    if (action === 'dashboard' || action === 'widget_summary') {
      const response = await route.fetch(), data = await response.json();
      data.demo = false; data.desktop = desktop;
      data.settings && (data.settings.live_usage_enabled = true);
      if (action === 'widget_summary') { data.accounts = grouped(); data.provider_allowances = []; }
      return route.fulfill({ json: data });
    }
    return route.continue();
  });
}
try {
  const context = await browser.newContext({ viewport: { width: 1500, height: 1100 } });
  await routes(context);
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  await page.getByRole('button', { name: 'Accounts', exact: true }).click();
  await expect(page.locator('.account-card')).toHaveCount(2);
  await expect(page.locator('.account-allowance')).toHaveCount(2);
  const current = page.locator('.account-card[data-account-id="current"]');
  await expect(current.locator('details')).not.toHaveAttribute('open');
  await current.locator('summary').click();
  await expect(current.locator('.account-connection')).toHaveCount(2);
  await expect(page.locator('.account-history')).toHaveCount(2);
  const hiddenSaved = current.locator(`.account-connection:has([data-account-id="${ids.saved}"])`);
  await hiddenSaved.getByRole('button', { name: 'Rename', exact: true }).click();
  await page.locator('#account-label-edit').fill('Saved <personal>');
  await page.getByRole('button', { name: 'Save label', exact: true }).click();
  await expect(current.locator('details')).toHaveAttribute('open');
  await expect(current.locator('.account-connection strong').first()).toHaveText('Saved <personal>');
  assert.equal(await page.locator('personal').count(), 0);
  // A background poll keeps the open disclosure and focus on its controls.
  const reconnect = hiddenSaved.getByRole('button', { name: 'Reconnect', exact: true });
  await reconnect.focus();
  accounts.accounts[0].plan = 'plus';
  await expect(current.locator('.account-card-heading p')).toContainText('plus');
  assert.equal(await reconnect.evaluate(el => el === document.activeElement), true);
  await current.locator(':scope > .account-controls').getByRole('button', { name: 'Pause', exact: true }).click();
  const activeSaved = page.locator(`.account-card[data-account-id="${ids.saved}"]`);
  await expect(activeSaved).toBeVisible();
  await expect(page.locator('.account-card')).toHaveCount(2);
  await expect(activeSaved.locator('details')).toHaveAttribute('open');
  const enableCurrent = activeSaved.locator('[data-account-id="current"][data-account-action="enable"]');
  await expect(enableCurrent).toBeFocused();
  await enableCurrent.click();
  await expect(current).toBeVisible();
  await expect(current.locator(':scope > .account-controls [data-account-action="disable"]')).toBeFocused();
  await page.setViewportSize({ width: 430, height: 850 });
  await page.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth);
  await page.screenshot({ path: resolve(output, 'deduplicated-accounts-narrow.png'), fullPage: true });
  await page.setViewportSize({ width: 1200, height: 900 });
  await page.locator('#settings-open').click();
  const picker = page.locator('#widget-accounts');
  await expect(picker.locator('input')).toHaveCount(2);
  await expect(picker.locator('input:checked')).toHaveCount(2);
  await picker.getByRole('button', { name: 'Move Work up', exact: true }).click();
  await expect(picker).not.toHaveAttribute('data-saving');
  assert.deepEqual(desktop.preferences.widget_account_ids, [ids.work, ids.saved, 'current', ids.duplicate]);
  await page.keyboard.press('Escape');
  const widget = await context.newPage();
  widget.on('pageerror', error => errors.push(error.message));
  await widget.setViewportSize({ width: 240, height: 600 });
  await widget.goto(url + '/widget/index.html');
  await expect(widget.locator('.widget-account')).toHaveCount(2);
  assert.deepEqual(await widget.locator('.widget-account h2').allTextContents(), ['Work · Pro', 'Current Codex · Plus']);
  const personal = widget.locator('.widget-account[data-account-id="current"]');
  await personal.locator('.allowance-bucket').selectOption('other');
  await expect(personal.locator('.allowance-bucket')).toHaveValue('other');
  await expect.poll(() => desktop.preferences.widget_account_buckets[ids.saved]).toBe('other');
  assert.equal(desktop.preferences.widget_account_buckets.current, undefined);
  await personal.locator('.allowance-refresh').click();
  await expect.poll(() => actions.some(entry => entry.action === 'account_refresh' && entry.args.id === 'current')).toBe(true);
  await widget.screenshot({ path: resolve(output, 'deduplicated-widget.png') });
  switched = true;
  await expect(widget.locator('.widget-account')).toHaveCount(3);
  assert.deepEqual(await widget.locator('.widget-account h2').allTextContents(), ['Work · Pro', 'Saved <personal> · Pro', 'Current Codex · Plus']);
  await expect(widget.locator(`[data-account-id="${ids.saved}"] .allowance-bucket`)).toHaveValue('other');
  await expect(page.locator('.account-card')).toHaveCount(3);
  switched = false;
  await expect(page.locator('.account-card')).toHaveCount(2);
  await page.locator('#settings-open').click();
  await expect(picker.locator('input')).toHaveCount(2);
  await picker.locator('[data-widget-account="current"]').uncheck();
  await expect(picker).not.toHaveAttribute('data-saving');
  assert.deepEqual(desktop.preferences.widget_account_ids, [ids.work]);
  await picker.locator('[data-widget-account="current"]').check();
  await expect(picker).not.toHaveAttribute('data-saving');
  assert.deepEqual(desktop.preferences.widget_account_ids, [ids.work, 'current']);
  await page.keyboard.press('Escape');
  if (!await current.locator('details').evaluate(el => el.open)) await current.locator('summary').click();
  const hiddenDuplicate = current.locator(`.account-connection:has([data-account-id="${ids.duplicate}"])`);
  await hiddenDuplicate.getByRole('button', { name: 'Remove', exact: true }).click();
  await page.locator('#account-remove-confirm').click();
  await expect.poll(() => accounts.accounts.length).toBe(3);
  await expect(page.locator('.account-card')).toHaveCount(2);
  assert(actions.some(entry => entry.action === 'account_remove' && entry.args.id === ids.duplicate));
  assert.deepEqual(errors, []);
  console.log('Account dedup browser checks passed: one card/row/choice, hidden controls, pause/resume, focus, narrow layout, alias buckets, refresh, reorder, switches, toggles and removal.');
} finally { await browser.close(); }
