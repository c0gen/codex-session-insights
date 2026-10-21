import assert from 'node:assert/strict';
import { mkdir } from 'node:fs/promises';
import { chromium, expect } from '../frontend/node_modules/@playwright/test/index.mjs';
import { metricFixture } from './metric-interface-fixture.mjs';
import { uiTestServer } from './ui-test-server.mjs';

const output = process.argv[2] || '.local-data/history-review-ui';
await mkdir(output, {recursive: true});
const server = await uiTestServer();
const browser = await chromium.launch({headless: true, channel: process.env.PLAYWRIGHT_CHANNEL || 'msedge'});
try {
  const page = await browser.newPage({viewport: {width: 1050, height: 850}});
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  const fixture = metricFixture();
  Object.assign(fixture, {exporter: true, demo: false, provider_setup: [], provider_allowances: []});
  Object.assign(fixture.coverage, {conflicts: 1, parse_errors: 0});
  fixture.claude_recovery = {state: 'awaiting_verification', identity_issues: 1,
    newly_included_responses: 2, newly_included_tokens: 3_000_000_001, reopened_choices: 1,
    sources: [{source_id: 'synthetic', state: 'pending', accepted_tokens_before: 110,
      accepted_tokens_after: 3_000_000_111, accepted_token_change: 3_000_000_001,
      legacy_snapshot_without_alternatives: true}]};
  const base = {source: 'Mac history', records: 10, locations: ['/synthetic/session.jsonl'], format: 'Transcript history',
    first_activity: '2026-10-01T12:00:00Z', last_activity: '2026-10-01T13:00:00Z'};
  const group = {id: 'copy:test', revision: 'r1', session_id: 'synthetic-session', kind: 'copy', state: 'needs_review',
    reason: 'Histories disagree. Choosing one excludes alternative activity from totals.', has_selection: false,
    versions: [{...base, id: 'accepted', accepted: true, recorded_tokens: 110}, {...base, id: 'other', accepted: false, recorded_tokens: 990}]};
  let revision = 1, sequence = 0;
  const job = {running: false, message: 'Ready', error: null, progress: {}, queued: [], completed: []};
  await page.route('**/api/*', async route => {
    const name = route.request().url().split('/').pop();
    let result = {};
    if (name === 'dashboard') result = {...fixture, job, revision, filters: route.request().postDataJSON()};
    if (name === 'status') result = {...job, revision};
    if (name === 'history_conflicts') result = [group];
    if (name === 'resolve_history_conflict') {
      const args = route.request().postDataJSON();
      assert.equal(args.revision, group.revision);
      if (args.undo) {group.state = 'needs_review'; group.has_selection = false; fixture.coverage.conflicts = 1;}
      else {
        group.state = 'manually_resolved'; group.has_selection = true; fixture.coverage.conflicts = 0;
        group.versions.forEach(v => v.accepted = v.id === args.selected);
      }
      group.revision = `r${++revision}`;
      const id = ++sequence;
      job.completed.push({id, origin: 'user', message: 'Updating accepted history', state: 'completed', error: null, result: {status: 'resolved'}});
      result = {status: 'started', job_id: id, message: 'Updating accepted history'};
    }
    if (name === 'live_status') result = {ready: true, job: {...job, revision}, desktop: {available: false}, provider_allowances: [],
      usage_limits: {allowed: false, enabled: false, buckets: [], status: 'disabled', stale: false, refreshing: false, last_success_at: null}};
    await route.fulfill({json: result});
  });
  await page.goto(server.url);
  await expect(page.locator('h1')).toHaveText('Mac Exporter');
  await expect(page.getByRole('region', {name: 'Claude history recovery'})).toContainText('3,000,000,001 newly included tokens');
  await expect(page.getByRole('region', {name: 'Claude history recovery'})).toContainText('older snapshot omitted alternative histories');
  await page.locator('#review-history-banner').click();
  await expect(page.getByRole('dialog')).toContainText('110 recorded tokens');
  await page.getByRole('button', {name: 'Use this version', exact: true}).click();
  await expect(page.getByRole('dialog')).toContainText('Selection saved');
  await expect(page.locator('.history-version').filter({hasText: '990 recorded tokens'})).toContainText('Accepted');
  await page.screenshot({path: `${output}/saved-selection.png`, fullPage: true});
  await page.getByRole('button', {name: 'Undo selection'}).click();
  await expect(page.getByRole('dialog')).toContainText('Needs review');
  await page.getByRole('button', {name: 'Keep accepted'}).click();
  await expect(page.getByRole('dialog')).toContainText('Selection saved');
  await page.getByRole('button', {name: 'Close dialog'}).click();
  await expect(page.locator('.coverage-note')).toHaveCount(0);
  await page.setViewportSize({width: 850, height: 700});
  await page.locator('#review-history').click();
  await expect(page.getByRole('dialog')).toContainText('Selection saved');
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await page.getByRole('button', {name: 'Close dialog'}).click();
  Object.assign(group, {state: 'awaiting_verification', reason_code: 'claude_identity_unverified',
    reason: 'Reconnect the original logs to verify agent identity.', alternative_only_tokens: 3_000_000_001,
    alternative_only_responses: 2, disputed_responses: 1});
  await page.locator('#review-history').click();
  await expect(page.getByRole('dialog')).toContainText('3,000,000,001 potentially excluded tokens');
  await expect(page.getByRole('button', {name: 'Keep accepted'})).toBeDisabled();
  await expect(page.getByRole('button', {name: 'Use this version'})).toBeDisabled();
  await page.screenshot({path: `${output}/identity-verification.png`, fullPage: true});
  assert.deepEqual(errors, []);
  console.log('Mac review UI: banner, selection, undo, persistent review and responsive layout passed');
} finally { await browser.close(); server.close(); }
