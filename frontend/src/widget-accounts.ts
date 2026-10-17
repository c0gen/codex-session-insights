import type { AccountSnapshot, AccountsSnapshot } from "./account-types";
import type { DesktopState, UsageLimits } from "./types";
import { resetSummary, accountDate } from "./account-credits";
import { esc } from "./ui";
import { icon } from "./icons";
import { accountPlanLabel, selectedAccountGroups } from "./account-presentation";
import { widgetTimestamp, widgetWindowMarkup, tooltipAttributes } from "./widget-presentation";

export type WidgetAccount = Pick<AccountSnapshot, "id" | "display_id" | "label" | "allowance"> & Partial<Pick<AccountSnapshot, "enabled" | "removing" | "plan">>;
export interface WidgetAccountActions {
  pending: Set<string>;
  errors: Map<string, string>;
  snapshotStale?: boolean;
  select: (id: string, bucket: string) => void;
  refresh: (id: string) => void;
  open: (id: string) => void;
}

export function widgetAccountGroups(accounts: AccountsSnapshot | undefined, fallback: UsageLimits | undefined, desktop: DesktopState) {
  if (!desktop.preferences?.show_usage_remaining) return [];
  const list: WidgetAccount[] = accounts?.allowed ? accounts.accounts : fallback
    ? [{ id: "current", label: "Current Codex", allowance: fallback }] : [];
  return selectedAccountGroups(list, desktop.preferences.widget_account_ids || ["current"]);
}

export function canRefreshAccount(account: WidgetAccount) {
  return account.enabled !== false && !account.removing && account.allowance.enabled && account.allowance.allowed;
}

function compactAccount(account: WidgetAccount, selectionId: string, requestedBucket: string, timezone: string, actions: WidgetAccountActions) {
  const limits = account.allowance;
  const plan = accountPlanLabel(account.plan);
  const bucket = limits.buckets.find(b => b.id === requestedBucket) || limits.buckets.find(b => b.id === "codex") || limits.buckets[0];
  const busy = actions.pending.has(account.id) || limits.refreshing;
  const failed = actions.errors.get(account.id) || limits.error;
  const stale = limits.stale || (!!failed || actions.snapshotStale) && limits.last_success_at !== null;
  const disabled = !canRefreshAccount(account) ? account.removing ? "Removing…" : account.enabled === false ? "Paused" : "Fetching disabled" : "";
  const state = [disabled, stale ? "Stale" : "", failed ? "Refresh failed" : ""].filter(Boolean).join(" · ");
  const updated = widgetTimestamp(limits.last_success_at, timezone);
  const selector = limits.buckets.length > 1
    ? `<select class="allowance-bucket" data-focus="bucket" aria-label="Allowance bucket for ${esc(account.label)}">${limits.buckets.map(b => `<option value="${esc(b.id)}" ${b.id === bucket?.id ? "selected" : ""}>${esc(b.name)}</option>`).join("")}</select>`
    : bucket && bucket.id !== "codex" ? `<span class="allowance-bucket-name">${esc(bucket.name)}</span>` : "";
  const summary = resetSummary(limits.reset_credits, timezone);
  const compactSummary = summary.replace("Next known expiry · ", "next known ");
  const next = limits.reset_credits?.credits?.filter(c => c.status === "available" && c.expires_at !== null).sort((a, b) => a.expires_at! - b.expires_at!)[0];
  const summaryDetail = next ? `${summary}. Next known expiry: ${accountDate(next.expires_at!, timezone)} · ${timezone}` : summary;
  const unavailable = !canRefreshAccount(account) ? "Live allowance fetching is disabled. Enable it in Settings."
    : failed || (busy ? "Connecting to Codex…" : "Allowance unavailable. Sign in to Codex, then refresh.");
  return `<section class="widget-account" data-account-id="${esc(account.id)}" data-selection-id="${esc(selectionId)}" ${stale ? 'data-stale="true"' : ""}>
    <div class="widget-account-heading"><h2>${esc(account.label)}${plan ? ` <small class="widget-account-plan">· ${esc(plan)}</small>` : ""}</h2><div class="widget-account-actions">
      <button class="allowance-refresh" data-focus="refresh" ${busy || !canRefreshAccount(account) ? "disabled" : ""} aria-label="Refresh ${esc(account.label)}" title="Refresh ${esc(account.label)}" ${busy ? 'aria-busy="true"' : ""}>${icon("refresh", 13)}</button>
      <button class="widget-account-open" data-focus="open" aria-label="Open ${esc(account.label)} in Accounts" title="Open ${esc(account.label)} in Accounts">${icon("expand", 13)}</button>
    </div></div>${state ? `<div class="widget-account-state" role="status" ${failed ? tooltipAttributes(failed) : ""}>${esc(state)}</div>` : ""}${selector}
    ${bucket?.windows.length ? bucket.windows.map((window, i) => widgetWindowMarkup(window, i === bucket.windows.length - 1 ? updated : "", timezone)).join("")
      : `<p class="allowance-unavailable">${esc(unavailable)}</p><div class="widget-metadata">${updated}</div>`}
    <p class="widget-reset-summary" ${tooltipAttributes(summaryDetail)}>${esc(compactSummary)}</p></section>`;
}

/** Shared account caches only; the widget never launches additional providers. */
export function renderWidgetAccounts(root: HTMLElement, accounts: AccountsSnapshot | undefined,
  fallback: UsageLimits | undefined, desktop: DesktopState, timezone: string,
  actions: WidgetAccountActions) {
  const preferences = desktop.preferences;
  root.hidden = !preferences?.show_usage_remaining;
  if (root.hidden) return;
  const selected = widgetAccountGroups(accounts, fallback, desktop);
  const markup = selected.length ? selected.map(({ account, selectedIds }) => {
    const selectionId = selectedIds[0];
    const bucket = preferences?.widget_account_buckets?.[selectionId] ||
      (selectionId === "current" ? preferences?.usage_remaining_bucket : undefined) || "codex";
    return compactAccount(account, selectionId, bucket, timezone, actions);
  }).join("") : `<div class="empty"><button data-action="show_settings">Select accounts in Settings</button></div>`;
  if (root.dataset.markup === markup) return;
  const scroller = root.closest<HTMLElement>("#widget-scroll")!;
  const scroll = scroller.scrollTop;
  const active = document.activeElement as HTMLElement | null;
  const focused = active?.closest<HTMLElement>(".widget-account")?.dataset.selectionId;
  const focusKey = active?.dataset.focus;
  const focusIndex = active ? Array.from(active.closest(".widget-account")?.querySelectorAll<HTMLElement>("[tabindex]") || []).indexOf(active) : -1;
  root.dataset.markup = markup;
  root.innerHTML = markup;
  for (const card of Array.from(root.querySelectorAll<HTMLElement>(".widget-account"))) {
    const id = card.dataset.accountId!;
    const selectionId = card.dataset.selectionId!;
    card.querySelector<HTMLSelectElement>(".allowance-bucket")?.addEventListener("change", event => actions.select(selectionId, (event.target as HTMLSelectElement).value));
    card.querySelector(".allowance-refresh")?.addEventListener("click", () => actions.refresh(id));
    card.querySelector(".widget-account-open")?.addEventListener("click", () => actions.open(id));
    if (selectionId === focused) {
      const next = focusKey ? card.querySelector<HTMLElement>(`[data-focus="${focusKey}"]`) : card.querySelectorAll<HTMLElement>("[tabindex]")[focusIndex];
      if (next instanceof HTMLButtonElement && next.disabled) card.querySelector<HTMLElement>(".widget-account-open")?.focus({ preventScroll: true });
      else next?.focus({ preventScroll: true });
    }
  }
  scroller.scrollTop = scroll;
}
