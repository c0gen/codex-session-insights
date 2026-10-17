import type { AccountSnapshot } from "./account-types";
import type { AccountGroup } from "./account-presentation";
import { esc } from "./ui";

export const connectionGroupKey = (group: AccountGroup<AccountSnapshot>) => group.connections.map(account => account.id).sort().join(":");

export function connectionControls(account: AccountSnapshot, disabled: boolean) {
  const action = (name: string, text: string) => `<button id="account-${esc(account.id)}-${name}" class="button small" data-account-action="${name}" data-account-id="${esc(account.id)}" ${disabled ? "disabled" : ""}>${text}</button>`;
  return `<div class="account-controls">${action("rename", "Rename")}${action(account.enabled ? "disable" : "enable", account.enabled ? "Pause" : "Enable")}${account.managed ? action("reconnect", "Reconnect") + action("remove", "Remove") : ""}</div>`;
}

export function connectionDisclosure(group: AccountGroup<AccountSnapshot>, disabled: boolean, open: boolean) {
  const hidden = group.connections.filter(account => account.id !== group.account.id);
  if (!hidden.length) return "";
  return `<details class="account-connections" data-connection-group="${esc(connectionGroupKey(group))}" ${open ? "open" : ""}><summary id="connections-${esc(connectionGroupKey(group))}">Sign-in connections</summary>
    ${hidden.map(account => `<div class="account-connection" role="group" aria-label="${esc(account.label)} sign-in connection"><strong>${esc(account.label)}</strong>
      <p class="account-muted">${account.managed ? "Separate sign-in" : "Follows your Codex sign-in"} · ${esc(!account.enabled ? "Paused" : account.allowance.status === "available" ? "Connected" : account.allowance.status)}</p>
      ${connectionControls(account, disabled)}</div>`).join("")}</details>`;
}
