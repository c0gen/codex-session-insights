import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve, extname } from 'node:path';
import { pathToFileURL } from 'node:url';
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { build } from '../frontend/node_modules/esbuild/lib/main.js';

const directory = resolve(process.argv[2]);
const fixtures = JSON.parse(await readFile(resolve(directory, 'dashboard-fixtures.json')));
const widget = JSON.parse(await readFile(resolve(directory, 'widget-fixture.json')));
const compiled = await build({ entryPoints: ['frontend/src/summary-image-data.ts'], bundle: true, format: 'esm', write: false });
const { summaryImageSnapshot } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString('base64')}`);
assert.match(summaryImageSnapshot(fixtures.claude_code, false).context, /^Claude Code/);
assert.equal(summaryImageSnapshot(fixtures.claude_code, false).tokens, 120);
assert.equal(summaryImageSnapshot(fixtures[''], false).partial, true);
assert.equal(summaryImageSnapshot(fixtures.antigravity, false).tokens, null);

const front = resolve('frontend/dist');
const server = createServer(async (req, res) => {
  try {
    const path = resolve(front, '.' + (req.url === '/' ? '/index.html' : req.url));
    if (!path.startsWith(front)) throw new Error('Invalid path');
    res.setHeader('Content-Type', ({ '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css' })[extname(path)] || 'application/octet-stream');
    res.end(await readFile(path));
  } catch { res.writeHead(404); res.end(); }
});
await new Promise(done => server.listen(0, '127.0.0.1', done));
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const errors = [];
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/*', async route => {
    const action = new URL(route.request().url()).pathname.split('/').pop();
    const args = route.request().postDataJSON();
    let value = {};
    if (action === 'dashboard') value = { ...fixtures[args.provider || ''], filters: args };
    if (action === 'provider_allowances') value = fixtures[''].provider_allowances;
    if (action === 'provider_setup_preview') value = { target: args.target, configuration: { statusLine: { type: 'command', command: 'synthetic-bridge' } } };
    if (action === 'status') value = { ...fixtures[''].job, revision: fixtures[''].revision };
    if (action === 'accounts') value = { enabled: false, allowed: false, accounts: [], login: { status: 'idle' } };
    if (action === 'widget_summary') value = widget;
    await route.fulfill({ json: value });
  });
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  const headline = page.locator('#total-tokens-kpi > strong');
  await expect(headline).toContainText('180');
  await expect(headline).toContainText('partial');
  await page.locator('#filter-provider').selectOption('claude_code');
  await expect(headline).toHaveText('120');
  // The Overview limits row follows the tool filter; full cards are on Accounts.
  await expect(page.locator('#limits-row')).toContainText('100% left');
  await expect(page.locator('#limits-row')).toContainText('5-hour');
  await expect(page.locator('#limits-row')).not.toContainText('gemini-weekly');
  await expect(page.locator('#limit-chip-antigravity')).toHaveCount(0);
  await page.locator('[data-page="usage"]').click();
  await expect(headline).toHaveText('120');
  await page.locator('[data-page="projects"]').click();
  await expect(page.locator('tbody')).toContainText('120');
  await page.locator('#filter-provider').selectOption('antigravity');
  await page.locator('[data-page="overview"]').click();
  await expect(headline).toHaveText('—');
  await expect(page.locator('#total-tokens-kpi')).toContainText('Token counters unavailable');
  await expect(page.locator('#limits-row')).toContainText('50% left');
  await page.locator('[data-page="sources"]').click();
  await expect(page.locator('.source-card')).toHaveCount(3);
  await page.locator('[data-provider-target="claude_code"][data-provider-operation="preview"]').click();
  await expect(page.locator('[role="dialog"]')).toContainText('synthetic-bridge');
  await page.keyboard.press('Escape');
  await page.locator('[data-page="overview"]').click();
  await page.locator('#filter-provider').selectOption('');
  await expect(headline).toContainText('180');
  await page.screenshot({ path: resolve(directory, 'providers-dashboard.png'), fullPage: true });
  await page.setViewportSize({ width: 850, height: 700 });
  await page.screenshot({ path: resolve(directory, 'providers-narrow.png'), fullPage: true });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true,
    JSON.stringify(await page.evaluate(() => [...document.querySelectorAll('main *')].filter(el => el.getBoundingClientRect().right > innerWidth + 1).slice(0, 12).map(el => [el.tagName, el.className, Math.round(el.getBoundingClientRect().width)]))));

  const report = await browser.newPage();
  report.on('pageerror', error => errors.push(error.message));
  await report.goto(pathToFileURL(resolve(directory, 'providers-report.html')).href);
  await expect(report.locator('#total-tokens-kpi > strong')).toContainText('180');
  await expect(report.locator('#total-tokens-kpi > strong')).toContainText('partial');
  await expect(report.locator('.provider-allowance')).toHaveCount(0);
  const html = await readFile(resolve(directory, 'providers-report.html'), 'utf8');
  assert(!html.includes('gemini-weekly'));
  assert(!html.includes('C:/synthetic'));

  await page.goto(`http://127.0.0.1:${server.address().port}/widget/index.html`);
  await expect(page.locator('.metric-tokens')).toContainText('180');
  await expect(page.locator('#provider-allowances')).toContainText('Claude');
  await expect(page.locator('#provider-allowances')).toContainText('5-hour limit');
  await expect(page.locator('#provider-allowances')).toContainText('Antigravity');
  await expect(page.locator('#provider-allowances')).toContainText('100% remaining');
  await expect(page.locator('#provider-allowances')).toContainText('50% remaining');
  await page.screenshot({ path: resolve(directory, 'providers-widget.png') });
  assert.deepEqual(errors, []);
  console.log('Provider UI passed: tool filters, nullable counters, coverage, separate allowances, setup preview, copied-image snapshots and offline report privacy.');
} finally { await browser.close(); server.close(); }
