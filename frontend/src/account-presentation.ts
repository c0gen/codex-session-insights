/** Display relationships contain connection IDs, never private account identity. */
type Connection = { id: string; display_id?: string };
export interface AccountGroup<T> { account: T; connections: T[] }
export interface SelectedAccountGroup<T> extends AccountGroup<T> { selectedIds: string[] }

/** Format reported subscription identifiers without guessing a price or tier. */
export function accountPlanLabel(plan?: string | null): string {
  const value = plan?.trim();
  if (!value) return "";
  if (value === "self_serve_business_prolite") return "Business Pro Lite";
  return value.split(/[_\s-]+/).filter(Boolean)
    .map(word => word[0].toUpperCase() + word.slice(1)).join(" ");
}

export function accountGroups<T extends Connection>(accounts: T[]): AccountGroup<T>[] {
  const byId = new Map(accounts.map(account => [account.id, account]));
  const groups = new Map<string, AccountGroup<T>>();
  for (const account of accounts) {
    const id = account.display_id && byId.has(account.display_id) ? account.display_id : account.id;
    let group = groups.get(id);
    if (!group) {
      group = { account: byId.get(id)!, connections: [] };
      groups.set(id, group);
    }
    group.connections.push(account);
  }
  return [...groups.values()];
}

export function selectedAccountGroups<T extends Connection>(accounts: T[], ids: string[]): SelectedAccountGroup<T>[] {
  const byId = new Map(accountGroups(accounts).flatMap(group => group.connections.map(account => [account.id, group] as const)));
  const selected = new Map<string, SelectedAccountGroup<T>>();
  for (const id of new Set(ids)) {
    const group = byId.get(id);
    if (!group) continue;
    let entry = selected.get(group.account.id);
    if (!entry) {
      entry = { ...group, selectedIds: [] };
      selected.set(group.account.id, entry);
    }
    entry.selectedIds.push(id);
  }
  return [...selected.values()];
}
