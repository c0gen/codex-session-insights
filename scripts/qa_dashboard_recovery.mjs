import assert from 'node:assert/strict';
import { build } from '../frontend/node_modules/esbuild/lib/main.js';
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { metricFixture } from './metric-interface-fixture.mjs';
import { uiTestServer } from './ui-test-server.mjs';

// Only synthetic API responses and production assets; no account or log access.
const server = await uiTestServer();
const browser = await chromium.launch({headless:true,channel:process.env.PLAYWRIGHT_CHANNEL || 'msedge'});
const job = {running:false,message:'',error:null,progress:{},revision:1,completed:[]};
const fixture = filters => ({...metricFixture(),filters,job,revision:job.revision});
const errors = [];
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror', e => errors.push(e.message));
  await page.clock.install();
  let cached = true, hold = true, reject = false, holdRefresh = false, refreshRoute;
  const held = [], requests = [], assets = [];
  page.on('request', request => { if (request.url().includes('/assets/')) assets.push(request.url()); });
  await page.route('**/api/*', async route => {
    const action = route.request().url().split('/').pop(), args = route.request().postDataJSON();
    if (action === 'bootstrap') return route.fulfill({json:{ready:true,cached_overview:cached ? {...metricFixture(),cached_at:'2026-03-11T00:00:00Z',job} : null}});
    if (action === 'dashboard') {
      requests.push(args);
      if (hold) { held.push({route,args}); return; }
      return route.fulfill(reject ? {status:500,json:{error:'Synthetic query failure'}} : {json:fixture(args)});
    }
    if (action === 'refresh' && holdRefresh) { refreshRoute = route; return; }
    if (action === 'settings') return route.fulfill({status:500,json:{error:'Synthetic settings failure'}});
    if (action === 'live_status') return route.fulfill({json:{ready:true,job,desktop:{available:false},usage_limits:{enabled:false},provider_allowances:[]}});
    if (action === 'status') return route.fulfill({json:job});
    return route.fulfill({json:{}});
  });
  const release = async request => request.route.fulfill({json:fixture(request.args)});
  const idle = () => expect(page.locator('#dashboard-results')).toHaveAttribute('aria-busy','false');
  await page.goto(server.url);
  await expect(page.locator('#export-html')).toBeDisabled();
  await expect(page.locator('#export-html')).toHaveAttribute('title',/Wait for the dashboard/);
  await expect.poll(() => held.length).toBe(1);
  const style = await page.locator('.equivalents-explore').evaluate(e => ({color:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor}));
  assert.equal(style.color,'rgb(96, 223, 186)');
  assert.equal(style.bg,'rgba(0, 0, 0, 0)');
  assert(!assets.some(url => /gallery-/.test(url)));
  await page.clock.runFor(4100);
  await expect(page.locator('#update-label')).toContainText('Cached overview');
  await expect(page.locator('#dashboard-results')).toHaveAttribute('aria-busy','true');
  hold = false; await release(held[0]); await idle();
  await expect(page.locator('#export-html')).toBeEnabled();
  await expect(page.locator('#update-label')).toHaveText(/^Results · /);
  const datedStatus = await page.locator('#update-label').textContent();
  await page.clock.runFor(4100);
  assert.equal(await page.locator('#update-label').textContent(),datedStatus);

  await page.locator('#filter-range').selectOption('custom');
  await page.locator('#date-start').fill('2026-10-10');
  await page.locator('#date-end').fill('2026-10-01');
  await page.locator('.nav-item[data-page="sources"]').click();
  await expect(page.locator('h1')).toHaveText('Sources');
  assert.equal(requests.at(-1).range,'all');
  await page.locator('.nav-item[data-page="usage"]').click();
  await expect(page.locator('h1')).toHaveText('Usage & Cost');
  await expect(page.locator('#date-start')).toHaveValue('2026-10-10');
  await expect(page.locator('#date-end')).toHaveValue('2026-10-01');
  await page.locator('.nav-item[data-page="sources"]').click();
  await expect(page.locator('h1')).toHaveText('Sources');
  reject = true;
  await page.locator('#refresh').click();
  await expect(page.locator('#filter-feedback')).toContainText('Synthetic query failure');
  await page.evaluate(() => {
    window.errorRewrites = 0;
    window.errorObserver = new MutationObserver(records => {window.errorRewrites += records.length;});
    errorObserver.observe(document.querySelector('#filter-feedback span'),{childList:true,characterData:true,subtree:true});
  });
  await page.clock.runFor(9000);
  assert.equal(await page.evaluate(() => errorRewrites),0);
  await page.evaluate(() => errorObserver.disconnect());
  await expect(page.locator('#filter-feedback')).toBeVisible();
  reject = false;
  await page.locator('#filters-retry').click(); await idle();
  await expect(page.locator('#filter-feedback')).toBeHidden();
  reject = true; await page.locator('#refresh').click();
  await expect(page.locator('#filter-feedback')).toBeVisible();
  reject = false; await page.locator('#refresh').click(); await idle();
  await expect(page.locator('#filter-feedback')).toBeHidden();

  await page.locator('.nav-item[data-page="overview"]').click(); await idle();
  await page.locator('#filter-range').selectOption('7'); await idle();
  hold = true;
  const count = held.length;
  await page.locator('#filter-range').selectOption('30');
  await expect.poll(() => held.length).toBe(count+1);
  await page.clock.runFor(6100);
  await expect(page.locator('#update-label')).toHaveText('Updating metrics…');
  await expect(page.locator('#dashboard-results')).toHaveAttribute('aria-busy','true');
  await page.locator('#filter-range').selectOption('custom');
  await page.locator('#date-start').fill('2026-08-01');
  await page.locator('.nav-item[data-page="usage"]').click();
  await expect.poll(() => held.length).toBe(count+2);
  assert.equal(held.at(-1).args.range,'30');
  await release(held.at(-1)); await idle();
  await release(held[count]);
  await expect(page.locator('#date-start')).toHaveValue('2026-08-01');
  assert.equal(await page.evaluate(() => JSON.parse(localStorage.getItem('insights-filters')).range),'30');
  // Returning to the currently displayed page must supersede a pending other view.
  const returnCount = held.length;
  await page.locator('.nav-item[data-page="overview"]').click();
  await expect.poll(() => held.length).toBe(returnCount+1);
  await page.locator('.nav-item[data-page="usage"]').click();
  await expect.poll(() => held.length).toBe(returnCount+2);
  assert.equal(held.at(-1).args._view,'usage');
  await release(held.at(-1)); await idle(); await release(held[returnCount]);
  await expect(page.locator('h1')).toHaveText('Usage & Cost');
  hold = false;

  holdRefresh = true;
  await page.locator('#refresh').click();
  await expect.poll(() => !!refreshRoute).toBe(true);
  await page.locator('#filter-range').selectOption('7'); await idle();
  const afterApply = requests.length;
  await refreshRoute.fulfill({json:{}}); holdRefresh = false;
  await page.waitForTimeout(100);
  assert.equal(requests.length,afterApply);
  assert.equal(requests.at(-1).range,'7');
  refreshRoute = null; holdRefresh = true;
  await page.locator('#refresh').click(); await expect.poll(() => !!refreshRoute).toBe(true);
  await page.locator('.nav-item[data-page="sources"]').click();
  await expect(page.locator('h1')).toHaveText('Sources');
  const afterNavigation = requests.length;
  await refreshRoute.fulfill({json:{}}); holdRefresh = false;
  await page.waitForTimeout(100); assert.equal(requests.length,afterNavigation);

  await page.locator('#settings-open').click();
  await expect(page.locator('#device-label')).toBeFocused();
  await expect(page.locator('#app')).toHaveAttribute('aria-hidden','true');
  await page.locator('#settings-save').focus(); await page.keyboard.press('Tab');
  await expect(page.locator('#dialog-close')).toBeFocused();
  await page.keyboard.press('Shift+Tab'); await expect(page.locator('#settings-save')).toBeFocused();
  await page.evaluate(() => document.getElementById('refresh').focus());
  assert(await page.locator('[role="dialog"]').evaluate(e => e.contains(document.activeElement)));
  await page.locator('#settings-save').click();
  await expect(page.locator('#toast')).toContainText('Synthetic settings failure');
  assert.notEqual(await page.locator('#toast').getAttribute('aria-hidden'),'true');
  await page.clock.runFor(4100);
  await page.keyboard.press('Escape'); await expect(page.locator('#settings-open')).toBeFocused();
  await expect(page.locator('#app')).not.toHaveAttribute('aria-hidden');

  // No-cache initial failure must retain startup recovery, without an unhandled error.
  cached = false; reject = true;
  await page.reload(); await expect(page.locator('.startup-error')).toContainText('Synthetic query failure');
  reject = false;
  await page.locator('.startup-error button').click(); await idle();
  // Offline snapshot and Mac exporter use the same eager status/modal styles.
  const offline = await browser.newPage();
  await offline.addInitScript(data => {window.__INSIGHTS_REPORT__ = {...data,readonly:true};},metricFixture());
  await offline.goto(server.url); await expect(offline.locator('#update-label')).toHaveText(/^Saved snapshot · /);
  await expect(offline.locator('#export-html')).toHaveCount(0); await offline.close();
  cached = false;
  await page.route('**/api/dashboard', route => route.fulfill({json:{...fixture(route.request().postDataJSON()),exporter:true}}));
  await page.reload(); await expect(page.locator('h1')).toHaveText('Mac Exporter');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
  await page.locator('#settings-open').click(); await page.keyboard.press('Escape');
  await expect(page.locator('#settings-open')).toBeFocused();

  // Exercise replacement and all-disabled paths directly through the reusable manager.
  const compiled = await build({entryPoints:['frontend/src/modal-manager.ts'],bundle:true,format:'iife',globalName:'ModalTest',write:false});
  const modalPage = await browser.newPage();
  await modalPage.setContent('<div id="app"><article data-account-id="one"><button data-account-action="rename">Rename</button></article><button class="nav-item" aria-current="page">Overview</button></div><div id="dialog-root"></div><div id="toast" role="status"></div>');
  await modalPage.addScriptTag({content:compiled.outputFiles[0].text});
  await modalPage.evaluate(() => {window.manager = new ModalTest.ModalManager(() => {}); document.querySelector('[data-account-action]').focus(); manager.open('One','<input id="entry">','<button id="save">Save</button>',() => {});});
  await modalPage.evaluate(() => {document.getElementById('app').innerHTML='<article data-account-id="one"><button data-account-action="rename">Rename again</button></article><button class="nav-item" aria-current="page">Overview</button>'; manager.open('Replacement','<input id="entry">','',() => {});});
  await modalPage.keyboard.press('Escape'); await expect(modalPage.locator('[data-account-action]')).toBeFocused();
  await modalPage.evaluate(() => {manager.open('Disabled','<input disabled>','<button disabled>Disabled</button>',() => {document.getElementById('dialog-close').disabled=true;});});
  await expect(modalPage.locator('[role="dialog"]')).toBeFocused();
  await modalPage.keyboard.press('Tab'); await expect(modalPage.locator('[role="dialog"]')).toBeFocused();
  await modalPage.evaluate(() => {document.querySelector('.modal input').disabled=false; document.querySelector('.modal-footer button').disabled=false;});
  await modalPage.keyboard.press('Shift+Tab'); await expect(modalPage.locator('.modal-footer button')).toBeFocused();
  await modalPage.keyboard.press('Escape'); await expect(modalPage.locator('[data-account-action]')).toBeFocused();
  await modalPage.evaluate(() => {
    document.getElementById('app').innerHTML = '<button title="Merge Synthetic with another project">Merge</button><button class="nav-item" aria-current="page">Overview</button>';
    document.querySelector('[title]').focus();
    manager.open('Merge project groups','<input>','',() => {});
    document.getElementById('app').innerHTML = '<button title="Merge Synthetic with another project">Merge replacement</button><button class="nav-item" aria-current="page">Overview</button>';
  });
  await modalPage.keyboard.press('Escape'); await expect(modalPage.locator('[title]')).toBeFocused();
  await modalPage.evaluate(() => {
    manager.open('Missing opener','<input>','',() => {});
    document.querySelector('[title]').remove();
  });
  await modalPage.keyboard.press('Escape'); await expect(modalPage.locator('.nav-item')).toBeFocused();
  await modalPage.close();
  assert.deepEqual(errors,[]);
  console.log('Production recovery regressions passed: cached export, eager style/lazy 3D, invalid navigation, retry/refresh, stable query status, submitted snapshots, refresh race, modal focus/live errors/replacement/disabled controls, initial failure, offline report, exporter.');
} finally { await browser.close(); server.close(); }

