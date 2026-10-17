import assert from 'node:assert/strict';
import { build } from '../frontend/node_modules/esbuild/lib/main.js';

const compiled = await build({ entryPoints: ['frontend/src/account-presentation.ts'], bundle: true, format: 'esm', write: false });
const { accountGroups, selectedAccountGroups } = await import(`data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString('base64')}`);
const accounts = [
  { id: 'saved', display_id: 'current', label: 'Personal' },
  { id: 'work', display_id: 'work', label: 'Work' },
  { id: 'current', display_id: 'current', label: 'Current Codex' },
  { id: 'saved-again', display_id: 'current', label: 'Personal alias' },
];
assert.deepEqual(accountGroups(accounts).map(group => group.account.id), ['current', 'work']);
assert.deepEqual(accountGroups(accounts)[0].connections.map(account => account.id), ['saved', 'current', 'saved-again']);
const ids = ['saved', 'work', 'current', 'saved-again', 'saved', 'removed'];
const selected = selectedAccountGroups(accounts, ids);
assert.deepEqual(selected.map(group => group.account.id), ['current', 'work']);
assert.deepEqual(selected[0].selectedIds, ['saved', 'current', 'saved-again']);
assert.deepEqual(ids, ['saved', 'work', 'current', 'saved-again', 'saved', 'removed']);
assert.deepEqual(selectedAccountGroups(accounts, ['saved']).map(group => group.account.id), ['current']);
const switched = accounts.map(account => ({ ...account, display_id: account.id }));
assert.deepEqual(selectedAccountGroups(switched, ['saved', 'current']).map(group => group.account.id), ['saved', 'current']);
assert.equal(accountGroups(accounts.map(({ display_id, ...account }) => account)).length, 4);
assert.equal(accountGroups([{ id: 'one', display_id: 'missing' }, { id: 'two' }]).length, 2);
assert.deepEqual(selectedAccountGroups(accounts, []).map(group => group.account.id), []);

// Backend display IDs distinguish members even when every plan and label match.
const members = Array.from({ length: 4 }, (_, i) => ({
  id: `member-${i + 1}`, display_id: `member-${i + 1}`, label: 'Shared organization',
  plan: 'self_serve_business_prolite', remaining_percent: 80 - i * 20,
}));
const organization = [...members, { ...members[0], id: 'member-one-duplicate' }];
assert.deepEqual(accountGroups(organization).map(group => group.account.remaining_percent), [80, 60, 40, 20]);
assert.deepEqual(selectedAccountGroups(organization, organization.map(account => account.id))
  .map(group => group.account.id), ['member-1', 'member-2', 'member-3', 'member-4']);
assert.deepEqual(accountGroups(organization)[0].connections.map(account => account.id), ['member-1', 'member-one-duplicate']);
console.log('Account presentation checks passed: grouping, stable order, aliases, shared-organization member quotas, account switches, legacy and missing snapshots.');
