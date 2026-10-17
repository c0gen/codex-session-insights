import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { mkdir } from 'node:fs/promises';
import { resolve } from 'node:path';
import assert from 'node:assert/strict';

const [url, output = '.local-data/token-kpi-ui'] = process.argv.slice(2);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const errors = [];
let total = { total_tokens: 121500000000, accounts: 2, reported_accounts: 2, identity_complete: true, unresolved_connections: 0, stale: false, refreshing: false, last_success_at: Date.now() / 1000 };
const indexed_token_totals = { codex: { total_tokens: 400, state: 'complete', sessions: 1 }, claude_code: { total_tokens: 300, state: 'complete', sessions: 1 }, antigravity: { total_tokens: 200, state: 'complete', sessions: 1 } };
try {
  const page = await browser.newPage({ viewport: { width: 1500, height: 1000 } });
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/*', async route => {
    const action = route.request().url().split('/').pop();
    if (action === 'accounts') return route.fulfill({ json: { allowed: true, enabled: true, accounts: [], login: { status: 'idle' }, token_total: total } });
    if (action === 'dashboard') {
      const response = await route.fetch();
      const data = await response.json();
      return route.fulfill({ json: { ...data, demo: false, account_token_total: total, indexed_token_totals } });
    }
    return route.continue();
  });
  await page.goto(url);
  const card = page.locator('#total-tokens-kpi');
  const initial = await card.locator(':scope > strong').innerText();
  assert.equal(initial, '121.5B');
  await expect(card.locator('.kpi-label')).toContainText('Total tokens');
  const analyzed = await card.locator('.token-analyzed').innerText();
  await page.screenshot({ path: resolve(output, 'dashboard-combined-total.png') });
  await page.locator('#filter-range').selectOption('today');
  await expect(card.locator('.token-analyzed')).not.toHaveText(analyzed);
  await expect(card.locator(':scope > strong')).toHaveText(initial);
  await card.locator('.info').focus();
  total = { ...total, total_tokens: 2000, identity_complete: false, unresolved_connections: 1 };
  await expect(card.locator(':scope > strong')).toHaveText('2.5Kpartial');
  await expect(card.locator('.info')).toBeFocused();
  total = { ...total, total_tokens: null, reported_accounts: 0 };
  await expect(card.locator(':scope > strong')).toHaveText('900');
  await expect(card).toContainText('Indexed Codex fallback');
  total = { ...total, total_tokens: 0, reported_accounts: 2, identity_complete: true, unresolved_connections: 0 };
  await expect(card.locator(':scope > strong')).toHaveText('500');
  await expect(card).not.toContainText('Indexed Codex fallback');
  total = { ...total, total_tokens: 1000, stale: true };
  await expect(card.locator(':scope > strong')).toHaveText('1.5Kstale');
  await page.locator('#filter-provider').selectOption('claude_code');
  await expect(card.locator('.token-analyzed')).toContainText('Unavailable');
  await expect(card.locator(':scope > strong')).toHaveText('1.5Kstale');
  await page.setViewportSize({ width: 900, height: 760 });
  await page.screenshot({ path: resolve(output, 'dashboard-combined-total-narrow.png') });
  assert.equal(await card.evaluate(el => el.scrollWidth <= el.clientWidth && el.getBoundingClientRect().right <= innerWidth), true);
  assert.deepEqual(errors, []);
  console.log('Token KPI browser checks passed: combined all-time headline, filtered analyzed counts, live updates, focus, partial/stale/zero counters and indexed fallback.');
} finally { await browser.close(); }
