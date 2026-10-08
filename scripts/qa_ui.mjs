import {chromium} from '../frontend/node_modules/@playwright/test/index.mjs';
import {mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';

const url=process.argv[2];
const report=process.argv[3];
const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHANNEL?{channel:process.env.PLAYWRIGHT_CHANNEL}:{})});
const page=await browser.newPage({viewport:{width:1586,height:992}});
const errors=[];
page.on('pageerror',e=>errors.push(e.message));
try {
 await page.goto(url);
 await page.locator('.kpi').first().waitFor();
 await page.locator('canvas').waitFor();
 await page.waitForTimeout(300);
 await mkdir('docs',{recursive:true});
 await page.screenshot({path:'docs/dashboard.png',fullPage:true});
 const original=await page.locator('.kpi>strong').first().textContent();
 await page.locator('[data-basis="output"]').click();
 await page.locator('[data-activity="cost"]').click();
 await page.locator('[data-page="usage"]').click();
 await page.locator('#model-chart').waitFor();
 assert.equal(await page.locator('.heat-row').count(),7);
 await page.locator('[data-model="cost"]').click();
 await page.locator('[data-page="projects"]').click();
 await page.locator('#project-search').fill('little-planets');
 assert.equal(await page.locator('tbody tr:visible').count(),1);
 await page.locator('tbody tr:visible').click();
 await page.waitForFunction(()=>document.querySelector('#filter-project')?.value);
 assert.notEqual(await page.locator('.kpi>strong').first().textContent(),original);
 await page.locator('#filter-project').selectOption('');
 await page.locator('#filter-range').selectOption('7');
 await page.waitForFunction(()=>document.querySelector('#filter-range')?.value==='7');
 await page.locator('[data-page="sources"]').click();
 assert.equal(await page.locator('.source-card').count(),2);
 await page.locator('#settings-open').click();
 assert.equal(await page.locator('[role="dialog"]').count(),1);
 await page.keyboard.press('Escape');
 assert.equal(await page.locator('[role="dialog"]').count(),0);
 await page.setViewportSize({width:850,height:650});
 await page.locator('[data-page="overview"]').click();
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
 if(report){
  await page.setViewportSize({width:1586,height:992});
  const external=[];
  page.on('request',r=>{if(/^https?:/.test(r.url()))external.push(r.url());});
  await page.goto(pathToFileURL(resolve(report)).href);
  await page.locator('.kpi').first().waitFor();
  assert.equal(await page.locator('#filter-range').isDisabled(),true);
  await page.locator('[data-page="sources"]').click();
  assert.equal(await page.locator('#import-snapshot').isDisabled(),true);
  assert.deepEqual(external,[]);
 }
 assert.deepEqual(errors,[]);
 console.log('UI smoke checks passed: navigation, filters, search, charts, responsive layout, offline report.');
} finally {await browser.close();}
