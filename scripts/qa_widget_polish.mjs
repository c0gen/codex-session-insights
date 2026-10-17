import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
import { accountFixture } from './account-ui-fixture.mjs';

const [url, output = '.local-data/widget-polish-ui'] = process.argv.slice(2);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const context = await browser.newContext();
const now = Date.parse('2026-10-14T16:53:00Z') / 1000;
const ids = ['current', 'a'.repeat(32), 'b'.repeat(32), 'c'.repeat(32)];
const alias = 'd'.repeat(32), hiddenId = 'e'.repeat(32);
const errors = [], requests = [], commands = [];
const accounts = { allowed: true, enabled: true, login: { status: 'idle' }, accounts: ids.map((id, i) => {
  const account = accountFixture(id, ['Current Codex', 'Personal account', 'acogen (CT)', 'cogenandy (CT)'][i], [72, 92, 0, 45][i]);
  account.plan = ['pro', 'self_serve_business_prolite', null, undefined][i];
  account.allowance.last_success_at = now;
  account.allowance.buckets = [account.allowance.buckets[0]];
  account.allowance.buckets[0].windows[0].resets_at = now + (6 - i) * 86400;
  account.allowance.reset_credits = { available_count: [3, 3, 0, 2][i], details_complete: false,
    credits: [{ id: 'reset', status: 'available', expires_at: now + 8 * 86400, expiration: 'dated' }] };
  return account;
}) };
accounts.accounts.push({ ...structuredClone(accounts.accounts[0]), id: alias, display_id: 'current', plan: 'plus' }, accountFixture(hiddenId, 'Hidden account'));
const state = { available: true, revision: 1, tray_active: true, settings_request: 0, preferences: {
  tray_enabled: true, widget_enabled: true, always_on_top: true, widget_details_expanded: false,
  widget_height_css_px: null, metrics: ['tokens', 'cost', 'lines'], show_usage_remaining: true,
  widget_account_ids: [...ids, alias], widget_account_buckets: {}, usage_remaining_bucket: 'codex',
} };
let providerData = [
  { provider: 'claude_code', received_at: null, buckets: [] },
  { provider: 'antigravity', received_at: now, buckets: [] },
];
let failSummary = false, failSettings = false, failId = null, summaryReads = 0;
const desktopReads = [];
await context.route('**/api/*', async route => {
  const action = route.request().url().split('/').pop(), args = route.request().postDataJSON();
  if (action === 'widget_layout' || action === 'widget_command') {
    commands.push({ action, args });
    return route.fulfill({ json: { status: 'accepted' } });
  }
  if (action === 'desktop_state') {
    desktopReads.push({ page: route.request().frame().url(), request: structuredClone(state.account_request) });
    return route.fulfill({ json: state });
  }
  if (action === 'desktop_settings') {
    if (failSettings) return route.fulfill({ status: 400, json: { error: 'Synthetic save failure' } });
    Object.assign(state.preferences, args); state.revision++;
    return route.fulfill({ json: state });
  }
  if (action === 'desktop_command') {
    commands.push({ action, args });
    if (args.command === 'show_account') state.account_request = { sequence: (state.account_request?.sequence || 0) + 1, account_id: args.account_id };
    return route.fulfill({ json: { status: 'accepted' } });
  }
  if (action === 'accounts') return route.fulfill({ json: accounts });
  if (action === 'account_refresh') {
    requests.push(args.id);
    await new Promise(resolve => setTimeout(resolve, 200));
    return args.id === failId ? route.fulfill({ status: 500, json: { error: 'Synthetic refresh failure' } }) : route.fulfill({ json: { status: 'started' } });
  }
  if (action === 'widget_summary') {
    summaryReads++;
    if (failSummary) return route.fulfill({ status: 500, json: { error: 'Synthetic disconnect' } });
  }
  if (action === 'dashboard' || action === 'widget_summary') {
    const response = await route.fetch(), data = await response.json();
    data.desktop = state; data.timezone = 'America/New_York'; data.demo = false;
    data.provider_allowances = providerData;
    if (action === 'widget_summary') data.accounts = accounts;
    return route.fulfill({ json: data });
  }
  if (action === 'provider_allowances') return route.fulfill({ json: providerData });
  return route.continue();
});
const widget = await context.newPage();
widget.on('pageerror', error => errors.push(error.message));
await widget.clock.install({ time: new Date(now * 1000) });
await widget.addInitScript(() => {
  window.__layouts = [];
  window.pywebview = { api: { call: async (action, args) => {
    if (action === 'widget_layout') window.__layouts.push(args);
    const token = document.querySelector('meta[name="insights-token"]')?.content || '';
    const response = await fetch('/api/' + action, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Insights-Token': token }, body: JSON.stringify(args) });
    const data = await response.json();
    if (!response.ok) throw Error(data.error);
    return data;
  } } };
});
async function poll() { await widget.evaluate(() => document.dispatchEvent(new Event('visibilitychange'))); }
let dashboard;
try {
  await widget.setViewportSize({ width: 240, height: 650 });
  await widget.goto(url + '/widget/index.html');
  const cards = widget.locator('#widget-allowance .widget-account');
  await expect(cards).toHaveCount(4);
  await expect(cards.first().locator('h2')).toHaveText('Current Codex · Pro');
  await expect(cards.nth(1).locator('.widget-account-plan')).toHaveText('· Business Pro Lite');
  await expect(cards.nth(2).locator('.widget-account-plan')).toHaveCount(0);
  await expect(cards.nth(3).locator('.widget-account-plan')).toHaveCount(0);
  assert(await cards.first().locator('h2').evaluate(heading =>
    parseFloat(getComputedStyle(heading.querySelector('small')).fontSize) < parseFloat(getComputedStyle(heading).fontSize)),
  'subscription label uses a smaller font than the account name');
  await expect(widget.locator('#provider-allowances')).toBeHidden();
  await expect(widget.locator('.allowance-heading, .allowance-bucket-name, .allowance-bucket')).toHaveCount(0);
  await expect(widget.locator('.widget-details-toggle')).toHaveCount(1);
  await expect(cards.nth(2)).toContainText('0% · Exhausted');
  for (const card of await cards.all()) {
    await expect(card.locator('.allowance-update')).toHaveCount(1);
    await expect(card.locator('.allowance-update')).toHaveText('Updated 12:53 PM');
    const aligned = await card.locator('.widget-metadata').evaluate(row => {
      const [left, right] = [...row.children].map(el => el.getBoundingClientRect());
      return Math.abs(left.top - right.top) < 1 && left.right <= right.left && Math.abs(right.right - row.getBoundingClientRect().right) < 1;
    });
    assert(aligned, 'reset and timestamp share a non-overlapping, right-aligned line');
  }
  await widget.waitForFunction(() => window.__layouts.length);
  const naturalHeight = await widget.evaluate(() => window.__layouts.at(-1).height);
  await widget.setViewportSize({ width: 240, height: Math.ceil(naturalHeight) });
  await widget.screenshot({ path: resolve(output, 'four-accounts.png') });
  const steadyContentHeight = (await widget.locator('#widget-content').boundingBox()).height;
  accounts.accounts[0].allowance.refreshing = true;
  await poll();
  const accountRefresh = cards.first().locator('.allowance-refresh');
  await expect(accountRefresh).toHaveAttribute('aria-busy', 'true');
  await expect(accountRefresh).toBeDisabled();
  await expect(cards.first().locator('.widget-account-state')).toHaveCount(0);
  assert.equal(await accountRefresh.locator('svg').evaluate(el => getComputedStyle(el).animationName), 'widget-spin');
  assert.equal((await widget.locator('#widget-content').boundingBox()).height, steadyContentHeight, 'account updating keeps widget content height unchanged');
  accounts.accounts[0].allowance.refreshing = false;
  await poll();
  await expect(accountRefresh).not.toHaveAttribute('aria-busy');
  assert.equal((await widget.locator('#widget-content').boundingBox()).height, steadyContentHeight, 'finishing an account update keeps widget content height unchanged');
  await cards.first().locator('.allowance-update').focus();
  await expect(widget.locator('#widget-tooltip')).toContainText('America/New_York');
  await widget.keyboard.press('Escape');
  await expect(widget.locator('#widget-tooltip')).toBeHidden();

  state.preferences.widget_height_css_px = 180; state.revision++;
  await widget.setViewportSize({ width: 240, height: 180 }); await poll();
  await widget.waitForFunction(() => document.querySelector('#widget-scroll').scrollHeight > document.querySelector('#widget-scroll').clientHeight);
  await widget.locator('.widget-details-toggle').click();
  await expect(widget.locator('.widget-details-toggle')).toHaveAttribute('aria-expanded', 'true');
  assert.equal((await widget.locator('#widget').boundingBox()).height, 180);
  await widget.locator('.widget-details-toggle').click();
  await expect(widget.locator('.widget-details-toggle')).toHaveAttribute('aria-expanded', 'false');
  await widget.waitForFunction(() => document.querySelector('#widget-details').getBoundingClientRect().height === 0);
  await widget.evaluate(() => document.querySelector('#widget-scroll').scrollTop = 60);
  const scroll = await widget.locator('#widget-scroll').evaluate(el => el.scrollTop);
  accounts.accounts[0].allowance.buckets[0].windows[0].remaining_percent = 20;
  await poll();
  await expect(cards.first()).toContainText('20% · Low');
  assert.equal(await widget.locator('#widget-scroll').evaluate(el => el.scrollTop), scroll);
  await widget.screenshot({ path: resolve(output, 'short-scrolling-widget.png') });
  for (const edge of ['top', 'bottom']) {
    await widget.locator(`[data-resize="${edge}"]`).dispatchEvent('mousedown', { button: 0, bubbles: true });
    await expect.poll(() => commands.some(c => c.args.command === 'resize_' + edge)).toBe(true);
  }
  await widget.locator('#widget-menu').click();
  await expect.poll(() => commands.some(c => c.args.command === 'menu')).toBe(true);

  accounts.accounts[0].label = 'A very long account name with a long-address@example.test';
  accounts.accounts[0].plan = 'self_serve_business_prolite';
  accounts.accounts[0].allowance.buckets[0].windows.push({ id: 'other', remaining_percent: null, window_duration_mins: 300, resets_at: null });
  await poll();
  await expect(cards.first().locator('.widget-account-plan')).toHaveText('· Business Pro Lite');
  assert(await cards.first().locator('.widget-account-heading').evaluate(heading => {
    const title = heading.querySelector('h2').getBoundingClientRect();
    const actions = heading.querySelector('.widget-account-actions').getBoundingClientRect();
    return title.right <= actions.left && actions.right <= heading.getBoundingClientRect().right;
  }), 'long account names and subscription labels leave room for account actions');
  await expect(cards.first().locator('.allowance-window')).toHaveCount(2);
  await expect(cards.first().locator('.allowance-update')).toHaveCount(1);
  await expect(cards.first().locator('.allowance-window').last().locator('.allowance-update')).toBeVisible();
  await expect(cards.first().locator('[data-tone="unknown"]')).toContainText('Unavailable');
  assert(await widget.locator('#widget-scroll').evaluate(el => el.scrollWidth <= el.clientWidth), 'long names and multiple windows do not overflow horizontally');
  await cards.first().locator('.allowance-update').focus();
  const focusedScroll = await widget.locator('#widget-scroll').evaluate(el => el.scrollTop);
  accounts.accounts[0].allowance.buckets[0].windows[0].remaining_percent = 19;
  await poll();
  await expect(cards.first()).toContainText('19% · Low');
  await expect(cards.first().locator('.allowance-update')).toBeFocused();
  assert.equal(await widget.locator('#widget-scroll').evaluate(el => el.scrollTop), focusedScroll);

  accounts.accounts[3].enabled = false;
  failId = ids[2];
  await poll();
  await widget.locator('#widget-refresh-all').click();
  await expect(widget.locator('#widget-refresh-all')).toHaveAttribute('aria-busy', 'true');
  await expect(widget.locator('#widget-refresh-all')).toHaveText('Refresh all');
  await expect(widget.locator('#widget-refresh-all')).toHaveAttribute('aria-busy', 'false');
  assert.deepEqual(requests.sort(), ids.slice(0, 3).sort());
  await expect(cards.nth(2)).toContainText('Refresh failed');
  await expect(cards.first()).not.toContainText('Refresh failed');
  requests.length = 0;
  accounts.accounts.forEach(account => account.allowance.enabled = false);
  await poll();
  const readsBefore = summaryReads;
  await widget.locator('#widget-refresh-all').click();
  await expect.poll(() => summaryReads > readsBefore).toBe(true);
  assert.deepEqual(requests, []);

  const freshBucket = { id: 'seven_day', unit: 'percent', remaining_percent: 0, used: null, limit: null, resets_at: now + 3600 };
  providerData = [{ provider: 'claude_code', profile: 'local', received_at: now, buckets: [freshBucket, { ...freshBucket, id: 'old', stale: true }] }];
  await poll();
  await expect(widget.locator('.provider-allowance')).toHaveCount(1);
  // Stale readings stay visible and dimmed instead of disappearing.
  await expect(widget.locator('.provider-allowance .allowance-window')).toHaveCount(2);
  await expect(widget.locator('.provider-allowance .allowance-window[data-state="stale"]')).toHaveCount(1);
  await expect(widget.locator('.provider-allowance')).toContainText('0% · Exhausted');
  await expect(widget.locator('.provider-allowance')).toContainText('Weekly limit');
  await expect(widget.locator('.provider-allowance')).toContainText('Resets');
  failSummary = true;
  await widget.clock.fastForward(301000);
  await expect(widget.locator('.provider-allowance')).toBeVisible();
  await expect(widget.locator('.provider-allowance .allowance-window[data-state="stale"]')).toHaveCount(2);
  await expect(cards.first()).toContainText('Stale');
  await expect(cards.first()).toContainText('19% · Low');
  failSummary = false;
  providerData[0].received_at = await widget.evaluate(() => Date.now() / 1000);
  await poll();
  await expect(widget.locator('.provider-allowance .allowance-window[data-state="stale"]')).toHaveCount(1);
  await expect(cards.first()).not.toContainText('Stale');

  dashboard = await context.newPage();
  dashboard.on('pageerror', error => errors.push(error.message));
  await dashboard.addInitScript(() => {
    window.__focusEvents = [];
    document.addEventListener('focusin', event => window.__focusEvents.push({ tag: event.target.tagName, id: event.target.id, card: event.target.closest('.account-card')?.dataset.accountId }));
  });
  await dashboard.setViewportSize({ width: 1200, height: 900 });
  await dashboard.goto(url);
  await dashboard.locator('[data-page="accounts"]').waitFor();
  // Navigate through the actual widget command and desktop-state polling path.
  await cards.first().locator('.widget-account-open').click();
  await expect(dashboard.locator('#accounts-view')).toBeVisible();
  await expect(dashboard.locator('.account-card[data-account-id="current"] h2')).toBeFocused();
  await dashboard.locator('#account-new-label').focus();
  state.account_request = { sequence: state.account_request.sequence + 1, account_id: alias };
  await expect(dashboard.locator('.account-card[data-account-id="current"] h2')).toBeFocused();
  state.account_request = { sequence: state.account_request.sequence + 1, account_id: 'f'.repeat(32) };
  await expect(dashboard.locator('#toast')).toContainText('no longer available');
  await dashboard.locator('#settings-open').click();
  const heightMode = dashboard.locator('[data-desktop="widget_height_mode"]');
  await expect(heightMode).toHaveValue('custom');
  await heightMode.selectOption('auto');
  await expect.poll(() => state.preferences.widget_height_css_px).toBe(null);
  await heightMode.selectOption('custom');
  const heightInput = dashboard.locator('[data-desktop="widget_height_css_px"]');
  await heightInput.fill('240'); await heightInput.press('Tab');
  await expect.poll(() => state.preferences.widget_height_css_px).toBe(240);
  failSettings = true;
  await heightMode.selectOption('auto');
  await expect(dashboard.locator('.desktop-error')).toContainText('Synthetic save failure');
  await expect(heightMode).toHaveValue('custom');
  failSettings = false;
  assert.deepEqual(errors, []);
  console.log('Widget polish UI passed: compact rows, subscription labels and updates, aligned/timezoned metadata, keyboard tooltips, fixed viewport, scrolling, edge controls, deduplicated refresh/failures, offline provider expiry/recovery, account navigation and height settings.');
} catch (error) {
  await widget.screenshot({ path: resolve(output, 'failure.png') }).catch(() => {});
  if (dashboard) {
    await dashboard.screenshot({ path: resolve(output, 'dashboard-failure.png') }).catch(() => {});
    console.error(JSON.stringify({ desktopReads: desktopReads.slice(-10), dashboard: await dashboard.evaluate(() => ({ active: document.activeElement.tagName + '#' + document.activeElement.id, focusEvents: window.__focusEvents })) }));
  }
  throw error;
} finally { await browser.close(); }
