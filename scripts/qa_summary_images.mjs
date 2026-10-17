import { chromium } from '../frontend/node_modules/@playwright/test/index.mjs';
import { build } from '../frontend/node_modules/esbuild/lib/main.js';
import { mkdir, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';

const [url, output = '.local-data/summary-image-ui'] = process.argv.slice(2);
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}) });
const context = await browser.newContext({ viewport: { width: 1500, height: 960 }, acceptDownloads: true });
const page = await context.newPage(), errors = [];
page.on('pageerror', error => errors.push(error.message));
await page.addInitScript(() => {
  window.__cards = []; window.__writes = []; window.__copyMode = 'success';
  const original = CanvasRenderingContext2D.prototype.fillText;
  CanvasRenderingContext2D.prototype.fillText = function (text, ...args) {
    if (this.canvas.width === 1200 && this.canvas.height === 720) {
      if (!this.canvas.__card) { this.canvas.__card = []; window.__cards.push(this.canvas.__card); }
      this.canvas.__card.push(text);
    }
    return original.call(this, text, ...args);
  };
  Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { write: async items => {
    const blob = await items[0].getType('image/png');
    const data = await new Promise(resolve => { const reader = new FileReader(); reader.onload = () => resolve(reader.result); reader.readAsDataURL(blob); });
    window.__writes.push(data);
    if (window.__copyMode === 'delay') await new Promise(resolve => { window.__releaseCopy = resolve; });
    if (window.__copyMode === 'fail') throw new Error('Clipboard blocked for verification');
  } } });
});

let fixture = null, gate = null, held = false;
await page.route('**/api/dashboard', async route => {
  const args = route.request().postDataJSON();
  const response = await route.fetch();
  const data = await response.json();
  if (fixture) Object.assign(data, structuredClone(fixture));
  if (gate && args.range === '30') { held = true; await gate.promise; }
  await route.fulfill({ response, json: data });
});
const card = () => page.evaluate(() => window.__cards.at(-1));
const copy = async () => {
  await page.locator('#copy-summary-image').click();
  await page.waitForFunction(() => document.querySelector('#toast')?.textContent === 'Image copied' && !document.querySelector('#copy-summary-image').disabled);
  return card();
};
const saveFixture = async filename => {
  await page.evaluate(() => { window.__copyMode = 'fail'; });
  await page.locator('#copy-summary-image').click();
  await page.locator('#save-summary-image').waitFor();
  const download = page.waitForEvent('download');
  await page.locator('#save-summary-image').click();
  await (await download).saveAs(`${output}/${filename}.png`);
  await page.evaluate(() => { window.__copyMode = 'success'; });
};
const dashboard = () => page.evaluate(async () => (await fetch('/api/dashboard', {
  method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Insights-Token': document.querySelector('meta[name="insights-token"]').content }, body: '{}',
})).json());
const queuedOperation = (action, args) => page.evaluate(async ([action, args]) => {
  const request = async (name, body) => (await fetch(`/api/${name}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Insights-Token': document.querySelector('meta[name="insights-token"]').content }, body: JSON.stringify(body),
  })).json();
  const operation = await request(action, args);
  for (let attempt = 0; attempt < 150; attempt++) {
    const state = await request('status', {});
    const completion = state.completed.find(value => value.id === operation.job_id);
    if (completion) {
      if (completion.state !== 'completed') throw Error(completion.error || completion.state);
      return completion.result;
    }
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw Error('Verification operation did not finish');
}, [action, args]);

try {
  await page.goto(url);
  await page.locator('#copy-summary-image').waitFor();
  const base = await dashboard();
  let texts = await copy();
  assert(texts.includes('CODEX SESSION INSIGHTS') && texts.includes('Demo data'));
  assert(texts.includes('All tools · All projects · All models · All sources'));
  assert(texts.includes((base.summary.lines_added + base.summary.lines_removed).toLocaleString('en-US')));
  assert(texts.some(value => value.includes(`${base.summary.priced_percent}% priced`)));
  assert(!texts.some(value => value.includes(base.settings.device_label)));
  await saveFixture('standard');

  // Pure snapshot checks exercise missing days, bounded bins, immutability and privacy.
  const compiled = await build({ entryPoints: ['frontend/src/summary-image-data.ts'], bundle: true, format: 'esm', write: false });
  const model = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString('base64')}`);
  globalThis.window = {};
  globalThis.localStorage = { getItem: () => null };
  const selected = structuredClone(base);
  selected.filters = { ...selected.filters, range: 'custom', project_id: base.options.projects[0].id, model: 'test-model', source_id: base.sources[0].id };
  selected.date_bounds = { start: '2026-01-01', end: '2026-01-04' };
  selected.timeline = [{ day: '2026-01-01', tokens: 12 }, { day: '2026-01-04', tokens: 8 }];
  selected.usage_limits = { secret: 'PRIVATE_ALLOWANCE' };
  selected.accounts = { secret: 'PRIVATE_ACCOUNT' };
  const snapshot = model.summaryImageSnapshot(selected, false);
  assert.deepEqual(snapshot.activity, [12, 0, 0, 8]);
  assert(Object.isFrozen(snapshot) && Object.isFrozen(snapshot.activity));
  assert.equal(snapshot.context, 'All tools · Selected project · test-model · Selected source');
  for (const [provider, label] of [['codex', 'Codex'], ['claude_code', 'Claude Code'], ['antigravity', 'Antigravity']]) {
    const scoped = { ...selected, filters: { ...selected.filters, provider } };
    assert.equal(model.summaryImageSnapshot(scoped, false).context, `${label} · Selected project · test-model · Selected source`);
  }
  assert(!JSON.stringify(snapshot).includes('PRIVATE_'));
  const named = model.summaryImageSnapshot(selected, true);
  assert(named.context.includes(base.options.projects[0].name));
  selected.summary.total_tokens = 999;
  assert.notEqual(snapshot.tokens, 999);
  const long = model.tokenActivity(selected, '2000-01-01', '2030-01-01');
  assert.equal(long.length, 180); assert.equal(long.reduce((sum, value) => sum + value, 0), 20);

  const project = base.options.projects[0].id, source = base.sources[0].id, modelName = base.options.models[0];
  for (const projectId of ['', project]) for (const modelId of ['', modelName]) for (const sourceId of ['', source]) {
    await page.locator('#filter-project').selectOption(projectId);
    await page.locator('#filter-model').selectOption(modelId);
    await page.locator('#filter-source').selectOption(sourceId);
    await page.waitForFunction(() => !document.querySelector('#copy-summary-image').disabled);
    texts = await copy();
    assert(texts.includes(`All tools · ${projectId ? 'Selected project' : 'All projects'} · ${modelId || 'All models'} · ${sourceId ? 'Selected source' : 'All sources'}`));
    const lines = await page.locator('.change-values strong').allTextContents();
    const total = lines.reduce((sum, value) => sum + Number(value.replace(/[^\d]/g, '')), 0);
    assert(texts.includes(total.toLocaleString('en-US')));
  }

  await page.locator('#settings-open').click();
  assert.equal(await page.locator('#summary-image-project-names').isChecked(), false);
  await page.locator('#summary-image-project-names').check();
  await page.keyboard.press('Escape');
  await page.reload();
  await page.locator('#filter-project').selectOption(project);
  await page.waitForFunction(() => !document.querySelector('#copy-summary-image').disabled);
  assert((await copy()).some(value => value.startsWith(`All tools · ${base.options.projects[0].name} · `)));

  // An applied alias resolves to the destination's current retained group name.
  const destination = base.options.projects[1];
  const merged = await queuedOperation('merge_projects', { sources: [project], target: destination.id });
  try {
    await page.locator('#refresh').click();
    await page.waitForFunction(id => document.querySelector('#filter-project')?.value === id, destination.id);
    await page.waitForFunction(() => !document.querySelector('#copy-summary-image').disabled);
    assert.equal(await page.locator('#filter-project').inputValue(), destination.id);
    assert((await copy()).some(value => value.startsWith(`All tools · ${destination.name} · `)));
  } finally {
    await queuedOperation('undo_project_merge', { operation_id: merged.operation_id });
  }
  await page.reload();
  await page.locator('#filter-project').selectOption(project);
  await page.waitForFunction(() => !document.querySelector('#copy-summary-image').disabled);

  // A pending copy keeps the old card while newer filtered results redraw the UI.
  await page.evaluate(() => { window.__copyMode = 'delay'; });
  await page.locator('#copy-summary-image').click();
  await page.waitForFunction(() => !!window.__releaseCopy);
  const oldCard = await card(), beforeWrites = await page.evaluate(() => window.__writes.length);
  await page.evaluate(() => document.querySelector('#copy-summary-image').click());
  assert.equal(await page.evaluate(() => window.__writes.length), beforeWrites);
  await page.locator('#filter-range').selectOption('7');
  await page.waitForTimeout(150);
  assert.equal(await page.locator('#copy-summary-image').isDisabled(), true);
  assert.deepEqual(await card(), oldCard);
  await page.evaluate(() => { window.__releaseCopy(); window.__copyMode = 'success'; });
  await page.waitForFunction(() => !document.querySelector('#copy-summary-image').disabled);

  gate = {}; gate.promise = new Promise(resolve => { gate.release = resolve; });
  await page.locator('#filter-range').selectOption('30');
  for (let i = 0; !held && i < 100; i++) await page.waitForTimeout(20);
  assert(held); assert.equal(await page.locator('#copy-summary-image').isDisabled(), true);
  await page.locator('#filter-range').selectOption('90');
  await page.waitForFunction(() => !document.querySelector('#copy-summary-image').disabled);
  gate.release(); gate = null;
  await page.waitForTimeout(150);
  assert((await copy()).some(value => value.startsWith('Last 90 days')));

  // Unapplied date drafts must retain the displayed summary's applied dates.
  await page.locator('#filter-range').selectOption('custom');
  await page.locator('#date-start').fill('2026-01-01');
  await page.locator('#date-end').fill('2026-01-02');
  assert((await copy()).some(value => value.startsWith('Last 90 days')));
  await page.locator('#date-apply').click();
  await page.waitForFunction(() => !document.querySelector('#copy-summary-image').disabled);
  texts = await copy(); assert(texts.some(value => value.includes('Jan 1, 2026 – Jan 2, 2026')));

  const empty = { ...base.summary, total_tokens: 0, cost: 0, lines_added: 0, lines_removed: 0, chats: 0, change_coverage: 'no_observed_changes' };
  fixture = { summary: empty, timeline: [] };
  await page.reload();
  assert((await copy()).includes('No activity'));
  await saveFixture('empty');
  fixture = {
    summary: { ...base.summary, total_tokens: 123456789012345, cost: 9876543210987.65, lines_added: 123456789012, lines_removed: 765432109876, chats: 12345678, priced_percent: 42, change_coverage: 'partial' },
    timeline: [{ day: '2026-10-01', tokens: 60000000000000 }, { day: '2026-10-08', tokens: 63456789012345 }],
    options: { ...base.options, projects: [{ id: project, name: 'Merged project 项目 '.repeat(20) }] },
    filters: { ...base.filters, range: 'custom', start: '2026-10-01', end: '2026-10-08', project_id: project, model: modelName, source_id: source },
    date_bounds: { start: '2026-10-01', end: '2026-10-08' },
    settings: { ...base.settings, assumed_fast_percent: 35 },
  };
  await page.reload(); texts = await copy();
  assert(texts.some(value => value.includes('42% priced')));
  assert(texts.some(value => value.includes('Partial observation')));
  assert(texts.some(value => value.includes('Fast assumed')));
  assert(!texts.some(value => value.startsWith('$') && value.endsWith('…')));
  assert(texts.some(value => value.startsWith('All tools · Merged project') && value.endsWith('…')));
  await saveFixture('large-values');
  fixture = { summary: { ...base.summary, total_tokens: 1234567, cost: 5.12, lines_added: 12, lines_removed: 3, chats: 5 }, date_bounds: { start: base.date_bounds.end, end: base.date_bounds.end }, timeline: [{ day: base.date_bounds.end, tokens: 1234567 }], filters: { ...base.filters, range: 'today' } };
  await page.reload(); await saveFixture('today');
  fixture = null; await page.reload();

  for (const section of ['usage', 'projects']) {
    await page.locator(`[data-page="${section}"]`).click(); assert(await page.locator('#copy-summary-image').isVisible()); await copy();
  }
  for (const section of ['sources', 'accounts']) {
    await page.locator(`[data-page="${section}"]`).click(); assert.equal(await page.locator('#copy-summary-image').isVisible(), false);
  }
  await page.locator('[data-page="overview"]').click();
  for (const width of [850, 500]) {
    await page.setViewportSize({ width, height: 850 });
    await page.waitForFunction(() => document.documentElement.scrollWidth <= innerWidth);
  }
  await page.screenshot({ path: `${output}/narrow-dashboard.png`, fullPage: true });

  for (const mode of [{ exporter: true }, { readonly: true }]) {
    fixture = mode;
    await page.reload();
    await page.locator('.page-header').waitFor();
    assert.equal(await page.locator('#copy-summary-image').isVisible(), false);
  }
  fixture = null;
  await page.reload();

  // The native UI uses only its bridge, preserves the failed card, and remembers settings.
  const nativePage = await context.newPage(), nativeCalls = [];
  nativePage.on('pageerror', error => errors.push(error.message));
  let nativeNames = false, cancelSave = true;
  await nativePage.exposeFunction('__nativeImages', async (action, args) => {
    nativeCalls.push({ action, args });
    if (action === 'summary_image_preferences') {
      if ('include_project_names' in args) nativeNames = args.include_project_names;
      return { include_project_names: nativeNames };
    }
    if (action === 'copy_summary_image') throw new Error('Injected clipboard failure');
    return { status: cancelSave ? 'cancelled' : 'saved' };
  });
  await nativePage.addInitScript(() => {
    window.pywebview = { api: { call: async (action, args = {}) => {
      if (['copy_summary_image', 'save_summary_image', 'summary_image_preferences'].includes(action)) return window.__nativeImages(action, args);
      const response = await fetch(`/api/${action}`, { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Insights-Token': document.querySelector('meta[name="insights-token"]').content }, body: JSON.stringify(args) });
      if (!response.ok) throw new Error('API request failed');
      return response.json();
    } } };
  });
  await nativePage.goto(url);
  await nativePage.locator('#settings-open').click();
  await nativePage.locator('#summary-image-project-names').check();
  await nativePage.keyboard.press('Escape');
  await nativePage.reload();
  await nativePage.locator('#settings-open').click();
  assert(await nativePage.locator('#summary-image-project-names').isChecked());
  await nativePage.keyboard.press('Escape');
  await nativePage.locator('#copy-summary-image').click();
  await nativePage.locator('#save-summary-image').click();
  await nativePage.waitForFunction(() => !!document.querySelector('#save-summary-image') && !document.querySelector('#save-summary-image').disabled);
  assert(await nativePage.locator('#save-summary-image').isVisible());
  cancelSave = false;
  await nativePage.locator('#save-summary-image').click();
  await nativePage.waitForFunction(() => document.querySelector('#toast')?.textContent === 'Image saved');
  const copied = nativeCalls.find(value => value.action === 'copy_summary_image');
  const saved = nativeCalls.filter(value => value.action === 'save_summary_image');
  assert(saved.length === 2 && saved.every(value => value.args.png_base64 === copied.args.png_base64));
  await writeFile(`${output}/native-payload.png`, Buffer.from(copied.args.png_base64, 'base64'));
  await nativePage.close();
  assert.deepEqual(errors, []);
  console.log('Summary image checks passed: filters, dates, immutable snapshots, privacy, PNG fallback, native bridge, preferences, chart fixtures, and narrow layouts.');
} finally { await browser.close(); }
