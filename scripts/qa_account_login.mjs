import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';
import { accountFixture } from './account-ui-fixture.mjs';

const [url, output = '.local-data/account-login-ui'] = process.argv.slice(2);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const signInUrl = 'https://auth.openai.com/authorize?state=synthetic&redirect_uri=http%3A%2F%2Flocalhost%3A1455';
const accounts = { enabled: true, allowed: true, error: null, login: { status: 'idle' }, accounts: [accountFixture('current', 'Current Codex')] };
try {
  const context = await browser.newContext({ viewport: { width: 900, height: 700 }, permissions: ['clipboard-read', 'clipboard-write'] });
  await context.route('**/api/*', async route => {
    const action = route.request().url().split('/').pop();
    if (action === 'accounts') return route.fulfill({ json: accounts });
    if (action === 'account_login_start') {
      accounts.login = { status: 'waiting', label: 'Other browser', url: signInUrl };
      return route.fulfill({ json: accounts.login });
    }
    if (action === 'account_login_cancel') {
      accounts.login = { status: 'cancelled' };
      return route.fulfill({ json: accounts.login });
    }
    if (action === 'dashboard') {
      const response = await route.fetch(), data = await response.json();
      data.demo = false;
      return route.fulfill({ json: data });
    }
    return route.continue();
  });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto(url);
  await page.getByRole('button', { name: 'Accounts', exact: true }).click();
  await page.getByRole('button', { name: 'Add account', exact: true }).click();
  const copyLink = page.getByRole('button', { name: 'Copy sign-in link', exact: true });
  await expect(copyLink).toBeEnabled();
  assert.equal(await copyLink.evaluate(el => el.previousElementSibling.textContent), 'Open sign-in page');
  await copyLink.click();
  await expect(page.locator('#toast')).toHaveText('Sign-in link copied. Paste it into your preferred browser.');
  assert.equal(await page.evaluate(() => navigator.clipboard.readText()), signInUrl);
  const readClipboard = await page.evaluateHandle(() => navigator.clipboard.readText.bind(navigator.clipboard));
  const writeClipboard = await page.evaluateHandle(() => navigator.clipboard.writeText.bind(navigator.clipboard));
  for (const denied of [false, true]) {
    await writeClipboard.evaluate(write => write('before copy'));
    await page.evaluate(denied => {
      Object.defineProperty(navigator, 'clipboard', { configurable: true, value: denied
        ? { writeText: async () => { throw new Error('Permission denied'); } } : undefined });
    }, denied);
    await copyLink.click();
    await expect(page.locator('#toast')).toHaveText('Sign-in link copied. Paste it into your preferred browser.');
    assert.equal(await readClipboard.evaluate(read => read()), signInUrl);
    assert.equal(await page.locator('textarea').count(), 0);
  }
  await page.screenshot({ path: resolve(output, 'account-sign-in-copy-link.png') });
  await page.setViewportSize({ width: 500, height: 800 });
  await page.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.evaluate(() => { document.execCommand = () => false; });
  await copyLink.click();
  await expect(page.locator('#toast')).toHaveText('Could not copy the sign-in link. Please try again.');
  await expect(copyLink).toBeEnabled();
  await page.getByRole('button', { name: 'Cancel sign-in', exact: true }).click();
  await expect(copyLink).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Add account', exact: true })).toBeEnabled();
  assert.deepEqual(errors, []);
  console.log('Account login UI passed: adjacent copy button, exact clipboard URL, missing/denied Clipboard API fallback, failure feedback, narrow layout, and cancellation.');
} finally { await browser.close(); }
