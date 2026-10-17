import { chromium } from '../frontend/node_modules/@playwright/test/index.mjs';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const [url, output = '.local-data/accounts-ui'] = process.argv.slice(2);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const errors = [], actions = [], now = Math.floor(Date.now() / 1000);
const ids = ['current', 'a'.repeat(32), 'b'.repeat(32)];
let revisionOffset = 0;
const rate = (value, status = 'available', observed_seconds = 300) => ({ value, status, observed_seconds, updated_at: now });
const allowance = (used = 30) => ({
  enabled: true, allowed: true, status: 'available', refreshing: false, stale: false,
  last_success_at: now, next_refresh_at: now + 60, error: null, error_code: null,
  buckets: [{ id: 'codex', name: 'Codex', windows: [
    { id: 'primary', remaining_percent: 100 - used, window_duration_mins: 300, resets_at: now + 3600, burn_rate: rate(2.4) },
    { id: 'secondary', remaining_percent: 45, window_duration_mins: 10080, resets_at: now + 86400 * 3, burn_rate: rate(0.6) },
  ] }],
  reset_credits: { available_count: 5, details_complete: false, credits: [
    { id: 'expires', status: 'available', title: 'Banked reset', granted_at: now - 1000, expires_at: now + 3600, expiration: 'dated' },
    { id: 'forever', status: 'available', title: 'Banked reset', granted_at: now - 1000, expires_at: null, expiration: 'none' },
    { id: 'unknown', status: 'available', title: 'Banked reset', granted_at: now - 1000, expires_at: null, expiration: 'unknown' },
  ] },
});
const history = {
  enabled: true, allowed: true, status: 'available', refreshing: false, stale: false, last_success_at: now, error: null, error_code: null,
  summary: { lifetime_tokens: 42000000, peak_daily_tokens: 5000000, current_streak_days: 4, longest_streak_days: 12, longest_running_turn_sec: 100 },
  daily: Array.from({ length: 18 }, (_, i) => ({
    day: new Date((now - (17 - i) * 86400) * 1000).toISOString().slice(0, 10), tokens: i === 0 ? 0 : (i % 5 + 1) * 600000,
  })).filter((_, i) => i !== 8),
};
let accounts = { enabled: true, allowed: true, error: null, token_burn_rate: rate(12400), login: { status: 'idle' }, accounts: ids.map((id, i) => ({
  id, label: ['Current Codex', 'Research account with a deliberately long display label', 'Work'][i],
  plan: i === 2 ? 'business' : 'pro', managed: i > 0, enabled: true, removing: false,
  allowance: allowance(30 + i * 20), history: structuredClone(history),
})) };
accounts.accounts[1].history.summary.lifetime_tokens = 0;
accounts.accounts[2].history = { ...structuredClone(history), daily: null, summary: Object.fromEntries(Object.keys(history.summary).map(key => [key, null])), status: 'unavailable', error: 'This Codex version does not support token history.' };
accounts.accounts[2].allowance = { ...allowance(70), status: 'stale', stale: true, error: 'Read timed out.' };
accounts.accounts[2].allowance.buckets[0].windows.forEach(window => { window.burn_rate.status = 'stale'; });
let desktop = { available: true, preferences: {
  tray_enabled: true, widget_enabled: true, always_on_top: true, metrics: ['tokens', 'cost', 'lines'],
  show_usage_remaining: true, usage_remaining_bucket: 'codex', widget_account_ids: ids.slice(0, 2), widget_account_buckets: {},
}, revision: 1, tray_active: true, error: null, settings_request: 0 };

async function routes(context) {
  await context.route('**/api/*', async route => {
    const action = route.request().url().split('/').pop();
    const args = route.request().postDataJSON();
    if (action === 'status') {
      const response = await route.fetch(), data = await response.json();
      data.revision += revisionOffset;
      return route.fulfill({ json: data });
    }
    if (action === 'accounts') return route.fulfill({ json: accounts });
    if (action === 'usage_limits') return route.fulfill({ json: { ...accounts.accounts[0].allowance, token_burn_rate: accounts.token_burn_rate } });
    if (action === 'desktop_state') return route.fulfill({ json: desktop });
    if (action === 'desktop_settings') {
      desktop = { ...desktop, revision: desktop.revision + 1, preferences: { ...desktop.preferences, ...args } };
      return route.fulfill({ json: desktop });
    }
    if (action.startsWith('account_')) {
      actions.push({ action, args });
      if (action === 'account_login_start') accounts.login = { status: 'waiting', account_id: args.id || 'c'.repeat(32), label: args.label || 'Research', error: null };
      if (action === 'account_login_cancel') accounts.login = { status: 'cancelled' };
      if (action === 'account_settings') Object.assign(accounts.accounts.find(account => account.id === args.id), args);
      if (action === 'account_remove') accounts.accounts = accounts.accounts.filter(account => account.id !== args.id);
      return route.fulfill({ json: { status: 'started' } });
    }
    if (action === 'widget_layout' || action === 'widget_command') {
      actions.push({ action, args });
      return route.fulfill({ json: { status: 'accepted' } });
    }
    if (action === 'dashboard' || action === 'widget_summary') {
      const response = await route.fetch();
      const data = await response.json();
      data.revision += revisionOffset;
      data.desktop = desktop;
      data.usage_limits = { ...accounts.accounts[0].allowance, token_burn_rate: accounts.token_burn_rate };
      data.demo = false;
      data.settings && (data.settings.live_usage_enabled = accounts.enabled);
      if (action === 'widget_summary') {
        data.accounts = accounts;
        // Account geometry is exercised independently of local provider cards.
        data.provider_allowances = [];
      }
      return route.fulfill({ json: data });
    }
    return route.continue();
  });
}
async function redrawPreservesRateFocus(page, row) {
  await row.focus();
  const main = await page.locator('main.main').elementHandle();
  revisionOffset++;
  await page.waitForFunction(previous => !previous.isConnected, main);
  assert.equal(await row.evaluate(el => el === document.activeElement), true,
    'a full analytics redraw must preserve keyboard focus on burn-rate help');
  await main.dispose();
}
try {
  const context = await browser.newContext({ viewport: { width: 1500, height: 1100 } });
  await routes(context);
  const page = await context.newPage();
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  // Overview shows a compact limits row; the full rate rows live on Accounts.
  const overviewRate = page.locator('#limits-row .burn-rate-tokens');
  await overviewRate.waitFor();
  assert.match(await overviewRate.innerText(), /12\.4K tokens\/min/);
  await redrawPreservesRateFocus(page, overviewRate);
  assert.match(await overviewRate.getAttribute('aria-label'), /Local token burn.*Five-minute trailing estimate/);
  const overviewValue = await overviewRate.innerText();
  await page.locator('#limits-row').screenshot({ path: resolve(output, 'allowance-burn-rates.png') });
  await page.screenshot({ path: resolve(output, 'dashboard-burn-rates.png'), fullPage: true });
  await page.getByRole('button', { name: 'Accounts', exact: true }).click();
  await page.locator('.account-card').nth(2).waitFor();
  assert.equal(await page.locator('.filters').count(), 0);
  assert.equal(await page.locator('#export-html').isVisible(), false);
  assert.equal(await page.locator('#limits-row').count(), 0);
  const current = page.locator('.account-card').first();
  const localRate = page.locator('#accounts-token-burn .burn-rate-tokens');
  assert.ok((await localRate.textContent()).includes(overviewValue), 'Overview and Accounts show the same local token burn');
  assert.equal(await page.locator('#accounts-view .burn-rate-tokens').count(), 1);
  assert.equal(await page.locator('.account-card .burn-rate-tokens').count(), 0);
  assert.equal(await current.locator('.burn-rate-allowance').count(), 2);
  assert.match(await current.locator('.burn-rate-allowance').first().innerText(), /2\.4%\/hr/);
  assert.match(await current.locator('.burn-rate-allowance').first().getAttribute('aria-label'), /Percentage points.*Observed interval: 5m/);
  await localRate.focus();
  assert.equal(await localRate.evaluate(el => el === document.activeElement), true);
  await redrawPreservesRateFocus(page, localRate);
  assert.match(await localRate.getAttribute('aria-label'), /Local token burn.*local Codex session folders.*across projects and accounts.*recorded event timestamps/);
  assert.doesNotMatch(await localRate.getAttribute('aria-label'), /refresh roughly every five minutes/);
  accounts.token_burn_rate = rate(0);
  await page.waitForFunction(() => document.querySelector('#accounts-token-burn').textContent.includes('0 tokens/min'));
  accounts.token_burn_rate = rate(null, 'unavailable', 0);
  await localRate.locator('strong').filter({ hasText: 'Unavailable' }).waitFor();
  assert.equal(await page.locator('.account-card').nth(2).locator('.burn-rate-allowance[data-status=stale]').count(), 2);
  accounts.token_burn_rate = rate(null, 'collecting', 0);
  await page.locator('#accounts-token-burn [data-status=collecting]').waitFor();
  assert.equal(await localRate.evaluate(el => el === document.activeElement), true);
  assert.match(await localRate.innerText(), /Waiting for indexing….*5m estimate/s);
  accounts.token_burn_rate = { ...rate(12400), partial: true, detail: 'Some local files could not be indexed; this rate may be incomplete.' };
  await localRate.getByText('Partial', { exact: true }).waitFor();
  assert.match(await localRate.innerText(), /12\.4K tokens\/min Partial/);
  assert.match(await localRate.getAttribute('aria-label'), /Partial estimate.*may be incomplete/);
  accounts.token_burn_rate = rate(12400, 'stale');
  await page.locator('#accounts-token-burn [data-status=stale]').waitFor();
  assert.match(await localRate.innerText(), /12\.4K tokens\/min Stale/);
  assert.equal(await current.locator('.burn-rate-allowance[data-status=available]').count(), 2);
  accounts.token_burn_rate = rate(12400);
  await page.locator('#accounts-token-burn [data-status=available]').waitFor();
  assert.equal(await page.locator('.account-card canvas').count(), 2);
  assert.equal(await page.locator('.account-card').nth(1).locator('dd').first().innerText(), '0');
  assert.equal(await page.getByText('No expiration', { exact: true }).count(), 3);
  assert.equal(await page.getByText('Expiration unavailable', { exact: true }).count(), 3);
  await page.locator('.account-range').first().selectOption('all');
  await page.screenshot({ path: resolve(output, 'accounts.png'), fullPage: true });
  await page.setViewportSize({ width: 900, height: 700 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.screenshot({ path: resolve(output, 'accounts-narrow.png'), fullPage: true });
  await page.setViewportSize({ width: 500, height: 800 });
  // Charts resize on the next frame; wait before measuring the page or taking a full-page screenshot.
  await page.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth);
  await page.screenshot({ path: resolve(output, 'accounts-burn-rates-mobile.png'), fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true,
    JSON.stringify(await page.evaluate(() => [...document.querySelectorAll('#accounts-view *')]
      .filter(el => el.getBoundingClientRect().right > innerWidth)
      .map(el => ({ tag: el.tagName, class: el.className, width: el.getBoundingClientRect().width })).slice(0, 12))));
  await page.setViewportSize({ width: 900, height: 700 });
  await page.locator('#account-new-label').fill('Additional test');
  await page.getByRole('button', { name: 'Add account', exact: true }).click();
  await page.getByText(/Complete sign-in in your browser/).waitFor();
  assert.equal(await page.locator('#account-add').isDisabled(), true);
  await page.getByRole('button', { name: 'Cancel sign-in', exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('#account-add').disabled);
  await page.locator('.account-card').nth(1).getByRole('button', { name: 'Rename', exact: true }).click();
  await page.locator('#account-label-edit').fill('Research <local>');
  await page.getByRole('button', { name: 'Save label', exact: true }).click();
  await page.getByRole('heading', { name: 'Research <local>', exact: true }).waitFor();
  assert.equal(await page.locator('local').count(), 0);
  await page.locator('.account-card').nth(1).getByRole('button', { name: 'Pause', exact: true }).click();
  await page.locator('.account-card').nth(1).getByRole('button', { name: 'Enable', exact: true }).waitFor();
  await page.locator('.account-card').nth(1).getByRole('button', { name: 'Enable', exact: true }).click();
  await page.getByRole('button', { name: 'Refresh all accounts', exact: true }).click();
  assert(actions.some(entry => entry.action === 'account_refresh' && !entry.args.id && entry.args.refresh_local));
  await page.locator('.account-card').first().getByRole('button', { name: 'Pause', exact: true }).click();
  await page.locator('.account-card').first().getByRole('button', { name: 'Enable', exact: true }).waitFor();
  await page.locator('#settings-open').click();
  assert.equal(await page.locator('#live-usage-enabled').isChecked(), true);
  const picker = page.locator('#widget-accounts');
  await picker.locator('input').nth(2).check();
  await page.waitForFunction(() => document.querySelectorAll('#widget-accounts input:checked').length === 3 && !document.querySelector('#widget-accounts').dataset.saving);
  await picker.getByRole('button', { name: 'Move Work up', exact: true }).click();
  await page.waitForFunction(() => !document.querySelector('#widget-accounts').dataset.saving);
  assert.deepEqual(desktop.preferences.widget_account_ids, ['current', ids[2], ids[1]]);
  await page.screenshot({ path: resolve(output, 'account-settings.png') });
  await page.keyboard.press('Escape');
  // Paused accounts now correctly disable widget refresh. Resume the account
  // before exercising manual refresh at each rendering scale.
  await page.locator('.account-card').first().getByRole('button', { name: 'Enable', exact: true }).click();
  await page.locator('.account-card').first().getByRole('button', { name: 'Pause', exact: true }).waitFor();

  for (const scale of [1, 1.25, 2]) {
    const widgets = await browser.newContext({ viewport: { width: 240, height: 340 }, deviceScaleFactor: scale });
    await routes(widgets);
    const widget = await widgets.newPage();
    widget.on('pageerror', error => errors.push(error.message));
    await widget.addInitScript(() => {
      window.__layouts = [];
      window.pywebview = { api: { call: async (action, args) => {
        if (action === 'widget_layout') window.__layouts.push(args);
        const token = document.querySelector('meta[name="insights-token"]')?.content || '';
        const response = await fetch('/api/' + action, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Insights-Token': token }, body: JSON.stringify(args) });
        return response.json();
      } } };
    });
    await widget.goto(url + '/widget/index.html');
    await widget.locator('.widget-account').nth(2).waitFor();
    assert.equal(await widget.locator('.burn-rate').count(), 0, 'compact widget omits all burn-rate rows');
    assert.deepEqual(await widget.locator('.widget-account h2').allTextContents(), ['Current Codex · Pro', 'Work · Business', 'Research <local> · Pro']);
    await widget.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight);
    assert.equal(await widget.evaluate(() => document.documentElement.scrollWidth <= innerWidth && document.documentElement.scrollHeight <= innerHeight), true);
    assert.equal(await widget.locator('#widget-scroll').evaluate(el => el.scrollHeight > el.clientHeight), true);
    await widget.waitForFunction(() => window.__layouts.length > 0);
    const layout = await widget.evaluate(() => window.__layouts.at(-1));
    assert.equal(layout.width, 240);
    assert.equal(layout.scale, scale);
    assert(layout.height > 340);
    const before = await widget.evaluate(() => window.__layouts.length);
    await widget.waitForTimeout(2200);
    assert.equal(await widget.evaluate(() => window.__layouts.length), before, 'clamped native viewport must not cause resize loops');
    await widget.locator('.allowance-refresh').first().click();
    assert(actions.some(entry => entry.action === 'account_refresh' && entry.args.id === 'current' && !entry.args.refresh_local));
    await widget.screenshot({ path: resolve(output, 'widget-accounts-' + scale + '.png') });
    await widgets.close();
  }
  await page.locator('.account-card').nth(2).getByRole('button', { name: 'Remove', exact: true }).click();
  await page.getByRole('button', { name: 'Remove account', exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll('.account-card').length === 2);
  assert.deepEqual(errors, []);
  console.log('Account UI passed: shared local token rate, separate allowance rates, independent freshness, indexing/zero/unavailable states, accessible help, narrow layouts, login/cancel, rename/enable/remove, history/reset details, and unchanged widgets at 100/125/200% scales.');
} finally { await browser.close(); }
