import type { AccountsSnapshot } from "./account-types";
import type { DesktopState } from "./types";
import { call } from "./api";
import { esc } from "./ui";
import { accountGroups, selectedAccountGroups } from "./account-presentation";

export function syncWidgetAccountSettings(root: HTMLElement, state: DesktopState, accounts?: AccountsSnapshot,
  saved?: (value: DesktopState) => void) {
  if (!accounts || !state.preferences) return;
  let field = root.querySelector<HTMLFieldSetElement>("#widget-accounts");
  if (!field) {
    field = document.createElement("fieldset");
    field.id = "widget-accounts";
    root.querySelector("#widget-bucket-label")?.after(field);
  }
  if (field.dataset.saving) return;
  const byId = new Map(accounts.accounts.map(account => [account.id, account]));
  const ids = (state.preferences.widget_account_ids || ["current"]).filter(id => byId.has(id));
  const selected = selectedAccountGroups(accounts.accounts, ids);
  const selectedIds = selected.map(group => group.account.id);
  const groups = accountGroups(accounts.accounts);
  const ordered = [...selected, ...groups.filter(group => !selectedIds.includes(group.account.id))];
  const key = JSON.stringify([ids, accounts.accounts.map(a => [a.id, a.label, a.display_id]), accounts.allowed]);
  if (field.dataset.key !== key) {
    field.dataset.key = key;
    field.innerHTML = `<legend>Accounts in widget · display order</legend>${ordered.map(({ account }) => {
      const id = account.id, index = selectedIds.indexOf(id);
      return `<div class="widget-account-setting"><label><input type="checkbox" data-widget-account="${esc(id)}" ${index >= 0 ? "checked" : ""}><span>${esc(account.label)}</span></label>
        <button type="button" data-move-account="${esc(id)}" data-direction="-1" aria-label="Move ${esc(account.label)} up" ${index <= 0 ? "disabled" : ""}>↑</button>
        <button type="button" data-move-account="${esc(id)}" data-direction="1" aria-label="Move ${esc(account.label)} down" ${index < 0 || index >= selected.length - 1 ? "disabled" : ""}>↓</button></div>`;
    }).join("")}<p class="fine-print">Select accounts to show together. Connect additional accounts on the Accounts page.</p>`;
  }
  const save = async (selected: string[]) => {
    field!.dataset.saving = "true";
    field!.querySelectorAll<HTMLInputElement | HTMLButtonElement>("input,button").forEach(el => el.disabled = true);
    try {
      const next = await call<DesktopState>("desktop_settings", { widget_account_ids: selected });
      saved?.(next);
      delete field!.dataset.saving;
      delete field!.dataset.key;
      syncWidgetAccountSettings(root, next, accounts, saved);
    } catch (error) {
      delete field!.dataset.saving;
      delete field!.dataset.key;
      syncWidgetAccountSettings(root, state, accounts, saved);
      root.querySelector(".desktop-error")!.textContent = String(error);
    }
  };
  field.onchange = event => {
    const target = event.target as HTMLInputElement, id = target.dataset.widgetAccount;
    const group = groups.find(group => group.account.id === id);
    if (id && group) {
      const members = new Set(group.connections.map(account => account.id));
      void save(target.checked ? [...ids, id] : ids.filter(item => !members.has(item)));
    }
  };
  field.onclick = event => {
    const button = (event.target as Element).closest<HTMLButtonElement>("[data-move-account]");
    if (!button || button.disabled) return;
    const from = selectedIds.indexOf(button.dataset.moveAccount!), to = from + Number(button.dataset.direction);
    if (from < 0 || to < 0 || to >= selected.length) return;
    const moved = [...selected];
    [moved[from], moved[to]] = [moved[to], moved[from]];
    void save(moved.flatMap(group => group.selectedIds));
  };
}
