import assert from 'node:assert/strict';
import {writeFile} from 'node:fs/promises';
import {chromium, expect} from '../frontend/node_modules/@playwright/test/index.mjs';
import {metricFixture} from './metric-interface-fixture.mjs';
import {uiTestServer} from './ui-test-server.mjs';
const [probe, output] = process.argv.slice(2);
const server = await uiTestServer();
const browser = await chromium.launch({headless:true, channel:process.env.PLAYWRIGHT_CHANNEL || 'msedge'});
const errors = [], observed = new Map();
let appendedDuringImport = 0, displayedDuringImport = 0;
try {
  const page = await browser.newPage({viewport:{width:1440,height:1000}});
  page.on('pageerror', error => errors.push(error.message));
  const snapshot = async () => (await fetch(probe + '/state')).json();
  const limits = state => ({enabled:true,allowed:true,status:'available',refreshing:false,stale:false,
    buckets:[],last_success_at:Date.now()/1000,error:null,...state.rates});
  await page.route('**/api/*', async route => {
    const action = route.request().url().split('/').pop(), state = await snapshot();
    const fixture = {...metricFixture(),demo:false,revision:state.job.revision || 0,job:state.job,
      generated_at:new Date().toISOString(),usage_limits:limits(state)};
    let value = {};
    if (action === 'bootstrap') value = {ready:true,cached_overview:null};
    if (action === 'dashboard') value = {...fixture,filters:route.request().postDataJSON()};
    if (action === 'live_status') value = {ready:true,job:state.job,desktop:{available:false},
      usage_limits:limits(state),provider_allowances:[]};
    if (action === 'status') value = state.job;
    await route.fulfill({json:value});
  });
  await page.goto(server.url);
  await expect(page.locator('#limits-burn-tokens strong')).toBeVisible();
  await fetch(probe + '/ready');
  const started = Date.now();
  while (Date.now()-started < 60000) {
    const state = await snapshot();
    const text = await page.locator('#limits-burn-tokens strong').textContent();
    const amount = Number(text.replace(/[^0-9.]/g,''));
    for (const item of state.written) {
      if (!observed.has(item.id) && amount >= item.expected) {
        observed.set(item.id,(Date.now()-item.at)/1000);
        appendedDuringImport += Number(item.phase === 'import');
        displayedDuringImport += Number(state.maintenance.phase === 'import' && state.job.running);
      }
    }
    if (observed.size === 20) break;
    await page.waitForTimeout(50);
  }
  assert.equal(observed.size,20);
  assert.deepEqual(errors,[]);
  const values = [...observed.values()].sort((a,b)=>a-b);
  await page.screenshot({path:output.replace(/\.json$/,'.png'),fullPage:true});
  await writeFile(output,JSON.stringify({events:values.length,p95_seconds:values[Math.ceil(values.length*.95)-1],
    maximum_seconds:values.at(-1),production_assets:true,poll_interval_seconds:2,appended_during_import:appendedDuringImport,
    displayed_during_import:displayedDuringImport,maintenance_completed: (await snapshot()).maintenance.phase === 'finished',errors},null,2));
} finally {await browser.close();server.close();}
