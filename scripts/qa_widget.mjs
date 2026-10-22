import { chromium } from '../frontend/node_modules/@playwright/test/index.mjs';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import assert from 'node:assert/strict';

const [url, output = '.local-data/widget-ui', report] = process.argv.slice(2);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const context = await browser.newContext();
const errors = [];
let state = { available: true, preferences: { tray_enabled: true, widget_enabled: false, always_on_top: true, widget_details_expanded: true, show_usage_remaining: false, metrics: ['tokens', 'cost', 'lines'] }, revision: 0, tray_active: true, error: null, settings_request: 0 };
let failSettings = false;
const limits = { enabled: true, allowed: true, status: 'available', refreshing: false, stale: false,
  last_success_at: Date.now() / 1000, error: null, buckets: [{ id: 'codex', name: 'Codex', windows: [
    { id: 'weekly', remaining_percent: 45, window_duration_mins: 10080, resets_at: Date.now() / 1000 + 86400 * 4 }
  ] }] };
let command;
let widgetCommand;
await context.route('**/api/*', async route => {
  const action = route.request().url().split('/').pop();
  if (action === 'widget_command') {
    widgetCommand = route.request().postDataJSON();
    return route.fulfill({ json: { status: 'accepted' } });
  }
  if (action === 'widget_layout') return route.fulfill({ json: { status: 'accepted' } });
  if (action === 'desktop_state') return route.fulfill({ json: state });
  if (action === 'desktop_settings') {
    if (failSettings) return route.fulfill({ status: 400, json: { error: 'Test save failure' } });
    state.preferences = { ...state.preferences, ...route.request().postDataJSON() };
    state.revision++;
    return route.fulfill({ json: state });
  }
  if (action === 'desktop_command') {
    command = route.request().postDataJSON().command;
    return route.fulfill({ json: { status: 'accepted' } });
  }
  if (action === 'dashboard' || action === 'widget_summary') {
    const response = await route.fetch();
    const data = await response.json();
    data.desktop = state;
    if (action === 'widget_summary') {
      data.usage_limits = limits;
      data.accounts = { allowed: true, enabled: true, accounts: [{ id: 'current', label: 'Current Codex', allowance: limits }] };
    }
    return route.fulfill({ json: data });
  }
  return route.continue();
});
const page = await context.newPage();
page.on('pageerror', error => errors.push(error.message));
try {
  await page.setViewportSize({ width: 1000, height: 760 });
  await page.goto(url);
  await page.locator('#settings-open').click();
  const preferences = page.locator('#desktop-preferences');
  await preferences.locator('[data-desktop=tray_enabled]').waitFor();
  assert.equal(await preferences.locator('[data-desktop=tray_enabled]').isChecked(), true);
  assert.equal(await preferences.locator('[data-desktop=widget_enabled]').isChecked(), false);
  await preferences.locator('[data-desktop=widget_enabled]').check();
  await preferences.locator('[data-desktop=chats]').check();
  await page.waitForFunction(() => !document.querySelector('[data-desktop=chats]').disabled);
  assert.deepEqual(state.preferences.metrics, ['tokens', 'cost', 'lines', 'chats']);
  await page.screenshot({ path: resolve(output, 'settings.png') });
  await page.keyboard.press('Escape');

  const widget = await context.newPage();
  widget.on('pageerror', error => errors.push(error.message));
  await widget.addInitScript(() => {
    window.__layouts = [];
    window.pywebview = { api: { call: async (action, args) => {
      if (action === 'widget_layout') window.__layouts.push(args);
      const token = document.querySelector('meta[name="insights-token"]')?.content;
      const response = await fetch('/api/' + action, { method: 'POST', headers: {
        'Content-Type': 'application/json', 'X-Insights-Token': token || ''
      }, body: JSON.stringify(args) });
      if (!response.ok) throw Error('Test request failed');
      return response.json();
    } } };
  });
  async function fitViewport() {
    await widget.waitForFunction(() => window.__layouts.length > 0);
    await widget.waitForTimeout(60);
    const size = await widget.evaluate(() => window.__layouts.at(-1));
    await widget.setViewportSize({ width: Math.ceil(size.width), height: Math.ceil(state.preferences.widget_height_css_px ?? size.height) });
    await widget.waitForFunction(() => Math.abs(document.querySelector('#widget').getBoundingClientRect().height - innerHeight) < 1);
    const layout = await widget.evaluate(() => ({
      width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth,
      scrollHeight: document.documentElement.scrollHeight, root: document.querySelector('#widget').getBoundingClientRect().toJSON(),
      main: document.querySelector('main').getBoundingClientRect().toJSON(), totals: document.querySelector('#totals').getBoundingClientRect().toJSON(),
    }));
    assert.equal(layout.scrollWidth <= layout.width && layout.scrollHeight <= layout.height, true, JSON.stringify(layout));
    const overlap = await widget.locator('td, tbody th').evaluateAll(cells => cells.filter(cell => {
      const range = document.createRange(); range.selectNodeContents(cell);
      const text = range.getBoundingClientRect(), box = cell.getBoundingClientRect();
      return text.left < box.left - .5 || text.right > box.right + .5 || text.top < box.top - .5 || text.bottom > box.bottom + .5;
    }).map(cell => cell.textContent));
    assert.deepEqual(overlap, []);
  }
  await widget.setViewportSize({ width: 240, height: 160 });
  await widget.goto(url + '/widget/index.html');
  await widget.locator('tbody tr').nth(3).waitFor();
  assert.deepEqual(await widget.locator('thead th').allTextContents(), ['Usage', 'Today', 'All time']);
  assert.equal(await widget.locator('header, footer, nav, .pywebview-drag-region').count(), 0);
  await fitViewport();
  await widget.screenshot({ path: resolve(output, 'widget-all-metrics.png') });
  await widget.locator('#widget').click({ button: 'right' });
  await widget.waitForTimeout(100);
  assert.deepEqual(widgetCommand, { command: 'menu', keyboard: false });
  await widget.locator('#widget').focus();
  await widget.keyboard.press('Shift+F10');
  await widget.waitForTimeout(100);
  assert.deepEqual(widgetCommand, { command: 'menu', keyboard: true });
  await widget.keyboard.press('Escape');
  await widget.waitForTimeout(100);
  assert.deepEqual(widgetCommand, { command: 'dismiss_menu', keyboard: false });
  await widget.locator('.metric-tokens td').first().hover();
  await widget.mouse.down();
  await widget.mouse.move(50, 40);
  await widget.mouse.up();
  await widget.waitForTimeout(100);
  assert.deepEqual(widgetCommand, { command: 'drag', keyboard: false });
  state.preferences.metrics = [];
  state.revision++;
  await widget.getByRole('button', { name: 'Select metrics in Settings' }).waitFor();
  await fitViewport();
  widgetCommand = undefined;
  await widget.getByRole('button', { name: 'Select metrics in Settings' }).click();
  await widget.waitForTimeout(100);
  assert.equal(command, 'show_settings');
  assert.deepEqual(widgetCommand, { command: 'dismiss_menu', keyboard: false }, 'settings button dismisses the menu without starting a drag');
  state.preferences.metrics = ['tokens', 'cost', 'lines'];
  state.revision++;
  await widget.locator('tbody tr').nth(2).waitFor();
  await fitViewport();
  await widget.screenshot({ path: resolve(output, 'widget.png') });
  const measured = await widget.evaluate(() => window.__layouts.at(-1));
  assert.equal(measured.width, 240);
  assert.equal(measured.scale, 1);
  const requestsBefore = await widget.evaluate(() => window.__layouts.length);
  await widget.waitForTimeout(2200);
  assert.equal(await widget.evaluate(() => window.__layouts.length), requestsBefore, 'stable polling must not resize the window');

  state.preferences.show_usage_remaining = true;
  state.preferences.metrics = ['tokens', 'cost', 'lines', 'chats'];
  state.revision++;
  const toggle = widget.locator('.widget-details-toggle');
  await toggle.waitFor();
  await widget.waitForFunction(() => document.querySelectorAll('tbody tr').length === 4);
  await widget.setViewportSize({ width: 240, height: 600 });
  await fitViewport();
  const expandedHeight = (await widget.locator('#widget').boundingBox()).height;
  assert.deepEqual(await widget.locator('tbody th').allTextContents(), ['Tokens', 'Cost', 'Lines', 'Main chats']);
  await widget.screenshot({ path: resolve(output, 'widget-expanded.png') });
  widgetCommand = undefined;
  await toggle.click();
  await widget.waitForFunction(() => document.querySelector('#widget-details').getBoundingClientRect().height < 1);
  assert.equal(state.preferences.widget_details_expanded, false);
  assert.deepEqual(widgetCommand, { command: 'dismiss_menu', keyboard: false }, 'disclosure button dismisses the menu without starting a drag');
  assert.equal(await toggle.getAttribute('aria-expanded'), 'false');
  assert.equal(await widget.locator('#widget-details').evaluate(el => el.inert), true);
  await fitViewport();
  assert((await widget.locator('#widget').boundingBox()).height < expandedHeight - 90);
  assert.equal((await widget.evaluate(() => window.__layouts.at(-1))).anchor, 'bottom');
  await widget.screenshot({ path: resolve(output, 'widget-collapsed.png') });
  await widget.reload();
  await toggle.waitFor();
  assert.equal(await toggle.getAttribute('aria-expanded'), 'false', 'collapse survives reload');
  await toggle.focus();
  await widget.keyboard.press('Enter');
  await widget.waitForFunction(() => document.querySelector('#widget-details').getBoundingClientRect().height > 100);
  await widget.waitForTimeout(300);
  await widget.setViewportSize({ width: 240, height: 600 });
  await fitViewport();
  assert.equal(await toggle.getAttribute('aria-expanded'), 'true');
  assert.equal(state.preferences.widget_details_expanded, true);

  failSettings = true;
  await toggle.click();
  await widget.waitForFunction(() => document.querySelector('.widget-details-toggle').getAttribute('aria-expanded') === 'true' && !document.querySelector('.widget-details-toggle').disabled);
  assert.equal(state.preferences.widget_details_expanded, true, 'failed saves restore the prior state');
  failSettings = false;
  await widget.emulateMedia({ reducedMotion: 'reduce' });
  await toggle.click();
  await widget.waitForFunction(() => document.querySelector('#widget-details').getBoundingClientRect().height === 0);
  assert.equal(await widget.locator('#widget-details').evaluate(el => getComputedStyle(el).transitionDuration), '0s');
  state.preferences.show_usage_remaining = false;
  state.revision++;
  await widget.waitForFunction(() => !document.querySelector('#widget').hasAttribute('data-collapsed'));
  assert.equal(await widget.locator('#widget-details').evaluate(el => el.inert), false, 'hiding usage leaves a usable metrics widget');

  if (report) {
    const saved = await browser.newPage();
    const requests = [];
    saved.on('pageerror', error => errors.push(error.message));
    saved.on('request', request => { if (/^https?:/.test(request.url())) requests.push(request.url()); });
    await saved.goto(pathToFileURL(resolve(report)).href);
    await saved.locator('.kpi').first().waitFor();
    await saved.locator('canvas').waitFor();
    assert.equal(await saved.locator('#filter-range').isDisabled(), true);
    assert.equal(await saved.locator('#desktop-preferences').count(), 0);
    assert.deepEqual(requests, []);
  }
  assert.deepEqual(errors, []);
  console.log('Widget UI checks passed: settings, metrics, drag/menu, 240px layout, disclosure, keyboard, persistence, failed save, reduced motion and standalone report.');
} catch (error) {
  console.error("Widget page errors:", errors);
  console.error(await context.pages().at(-1)?.locator("body").innerText());
  throw error;
} finally { await browser.close(); }
