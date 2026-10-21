import type { Chart } from "chart.js";
import { call } from "../api";
import type { AccountsSnapshot, AccountSnapshot } from "../account-types";
import { allowanceMarkup, bindAllowance } from "../allowance";
import { localBurnRatesMarkup } from "../burn-rate";
import { accountDate, resetMarkup } from "../account-credits";
import { historyChart, type HistoryRange } from "../account-history";
import { compact } from "../format";
import { esc } from "../ui";
import { copyText } from "../clipboard";
import { accountGroups, type AccountGroup } from "../account-presentation";
import { connectionControls, connectionDisclosure, connectionGroupKey } from "../account-connections";
import "../accounts.css";

type Dialog = (title: string, body: string, footer: string, bind: () => void) => void;
const pendingLogin = (value?: AccountsSnapshot) => !!value && ["starting", "waiting", "cancelling"].includes(value.login.status);

export function accountsPage() {
  return `<section id="accounts-view"><div class="accounts-toolbar">
    <label>New account label<input id="account-new-label" maxlength="80" placeholder="Personal, Work, Research…"></label>
    <button id="account-add" class="button primary" disabled>Add account</button>
    <button id="accounts-refresh" class="button" disabled>Refresh all accounts</button>
    </div><p class="accounts-hint">Sign in once in your browser. Each added account stays connected independently.</p>
    <div id="accounts-token-burn"></div>
    <div id="account-login" role="status"></div><p id="accounts-error" role="status"></p>
    <div id="account-cards" class="account-grid"><p>Loading account connections…</p></div></section>`;
}

export class AccountsView {
  private value?: AccountsSnapshot;
  private root: HTMLElement | null = null;
  private timezone = "UTC";
  private blocked = true;
  private busy = false;
  private working = false;
  private rendered = "";
  private charts: Chart[] = [];
  private ranges = new Map<string, HistoryRange>();
  private buckets = new Map<string, string>();
  private connectionError = "";
  private openConnections = new Set<string>();
  private pendingConnectionFocus?: { id: string; action: string };
  private requestedFocus?: string;

  constructor(private toast: (message: string, error?: boolean) => void, private dialog: Dialog, private close: () => void) {}
  snapshot() { return this.value; }

  focusAccount(id: string) {
    this.requestedFocus = id;
    void this.poll();
  }

  private focusRequestedAccount() {
    if (!this.requestedFocus || !this.root?.isConnected || !this.value) return;
    const group = accountGroups(this.value.accounts).find(group => group.connections.some(account => account.id === this.requestedFocus));
    const card = Array.from(this.root.querySelectorAll<HTMLElement>(".account-card")).find(card => card.dataset.accountId === group?.account.id);
    if (card) {
      card.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
      card.scrollIntoView({ block: "center" });
    } else this.toast("That account is no longer available. Your current accounts are shown here.");
    this.requestedFocus = undefined;
  }

  mount(blocked: boolean, timezone: string) {
    this.blocked = blocked;
    this.timezone = timezone;
    this.charts.forEach(chart => chart.destroy());
    this.charts = [];
    this.root = document.querySelector("#accounts-view");
    if (!this.root) this.requestedFocus = undefined;
    this.rendered = "";
    if (this.root) {
      this.root.querySelector("#account-add")?.addEventListener("click", () => {
        const input = this.root!.querySelector<HTMLInputElement>("#account-new-label")!;
        void this.perform("account_login_start", { label: input.value.trim() || "Additional account" });
      });
      this.root.querySelector("#accounts-refresh")?.addEventListener("click", () => { void this.perform("account_refresh", { refresh_local: true }); });
      this.root.addEventListener("click", event => {
        const target = (event.target as Element).closest<HTMLButtonElement>("[data-account-action]");
        if (target) this.handle(target.dataset.accountAction!, target.dataset.accountId);
      });
      this.root.addEventListener("toggle", event => {
        const details = event.target as HTMLDetailsElement;
        const key = details.dataset.connectionGroup;
        if (key && details.isConnected) {
          if (details.open) this.openConnections.add(key);
          else this.openConnections.delete(key);
        }
      }, true);
    }
    this.render();
    if (!blocked && this.root && !this.value) void this.poll();
  }

  private card(group: AccountGroup<AccountSnapshot>): string {
    const account = group.account;
    const disabled = this.working || !this.value?.allowed;
    const history = account.history, summary = history.summary;
    const value = (number: number | null) => number === null ? "Unavailable" : compact(number);
    const range = this.ranges.get(account.id) || "30";
    // Three large "Unavailable" values say less than one line explaining that nothing was reported.
    const empty = summary.lifetime_tokens === null && summary.peak_daily_tokens === null
      && summary.current_streak_days === null && !history.daily?.length;
    return `<article class="panel account-card" data-account-id="${esc(account.id)}">
      <div class="account-card-heading"><div><h2 id="account-heading-${esc(account.id)}" tabindex="-1">${esc(account.label)}</h2><p>${esc(account.plan || "Plan unavailable")} · ${account.managed ? "Separate sign-in" : "Follows your Codex sign-in"}</p></div>
      <span class="account-state">${!account.enabled ? "Paused" : account.allowance.status === "available" ? "Connected" : account.allowance.status}</span></div>
      ${connectionControls(account, disabled)}
      ${connectionDisclosure(group, disabled, this.openConnections.has(connectionGroupKey(group)))}
      <section class="account-allowance" aria-label="Account allowance">${allowanceMarkup(account.allowance, this.buckets.get(account.id) || "codex", false, undefined, account.id)}</section>
      <section class="account-history"><div class="account-section-heading"><h3>Account-reported token history</h3>
        <select class="account-range" aria-label="Token history range for ${esc(account.label)}" ${empty ? "hidden" : ""}>${[["30", "Last 30 days"], ["90", "Last 90 days"], ["all", "All available history"]].map(([key, text]) => `<option value="${key}" ${range === key ? "selected" : ""}>${text}</option>`).join("")}</select></div>
      ${empty ? `<p class="account-muted account-history-empty">No token history reported for this account yet: lifetime tokens, peak day and streak are unavailable.</p>` : `<dl class="account-metrics"><div><dt>Lifetime tokens</dt><dd>${value(summary.lifetime_tokens)}</dd></div><div><dt>Peak daily tokens</dt><dd>${value(summary.peak_daily_tokens)}</dd></div><div><dt>Current streak</dt><dd>${summary.current_streak_days === null ? "Unavailable" : summary.current_streak_days + " days"}</dd></div></dl>
      ${history.daily?.length ? '<div class="account-chart"><canvas role="img" aria-label="Daily account-reported tokens"></canvas></div>'
        : `<p class="account-muted">${history.daily === null ? "Daily token history is unavailable." : "No daily token buckets returned."}</p>`}
      <p class="account-muted">Reported bucket dates are preserved. Coverage can differ from locally indexed usage.</p>`}
      <p class="account-history-status">${history.stale ? "Stale · " : ""}${history.refreshing ? "Updating history… · " : ""}${history.last_success_at === null ? "No successful history update" : "History updated " + esc(accountDate(history.last_success_at, this.timezone))}</p>
      ${history.error ? `<p class="account-error">${esc(history.error)}</p>` : ""}</section>
      <section class="account-resets">${resetMarkup(account.allowance.reset_credits, this.timezone)}</section>
      </article>`;
  }

  private render() {
    if (!this.root?.isConnected || !this.value) return;
    const value = this.value;
    const localRate = this.root.querySelector<HTMLElement>("#accounts-token-burn")!;
    const rateMarkup = localBurnRatesMarkup(value, ["accounts"]);
    if (localRate.dataset.markup !== rateMarkup) {
      const focusedId = localRate.contains(document.activeElement) ? (document.activeElement as HTMLElement).id : "";
      const focusedRate = Array.from(localRate.querySelectorAll(".burn-rate")).indexOf(document.activeElement!);
      localRate.innerHTML = rateMarkup;
      localRate.dataset.markup = rateMarkup;
      if (focusedRate >= 0) localRate.querySelectorAll<HTMLElement>(".burn-rate")[focusedRate]?.focus({ preventScroll: true });
      if (focusedId) localRate.querySelector<HTMLElement>(`#${CSS.escape(focusedId)}`)?.focus({ preventScroll: true });
    }
    const add = this.root.querySelector<HTMLButtonElement>("#account-add")!;
    add.disabled = this.working || !value.allowed || !value.enabled || pendingLogin(value);
    this.root.querySelector<HTMLButtonElement>("#accounts-refresh")!.disabled = this.working || !value.allowed || !value.enabled;
    const notice = this.root.querySelector<HTMLElement>("#accounts-error")!;
    notice.textContent = this.connectionError || value.error ||
      (!value.allowed ? "Account connections are disabled in demo and exporter modes." : !value.enabled ? "Live account data is disabled. Enable it in Settings." : "");
    // A mode or setting that turns connections off is information, not an error.
    notice.classList.toggle("info", !this.connectionError && !value.error);
    this.root.querySelector<HTMLElement>(".accounts-toolbar")!.hidden = !value.allowed;
    this.root.querySelector<HTMLElement>(".accounts-hint")!.hidden = !value.allowed;
    const login = value.login;
    this.root.querySelector("#account-login")!.innerHTML = pendingLogin(value)
      ? `<div class="account-login-status"><strong>${esc(login.label)} · ${login.status === "cancelling" ? "Cancelling sign-in…" : login.status === "starting" ? "Opening sign-in…" : "Complete sign-in in your browser"}</strong>
        ${login.status === "waiting" ? `<button class="button small" data-account-action="open">Open sign-in page</button>
        <button class="button small" data-account-action="copy-link" title="Copy the sign-in link to open in another browser" ${login.url ? "" : "disabled"}>Copy sign-in link</button>` : ""}
        <button class="button small" data-account-action="cancel" ${login.status === "cancelling" ? "disabled" : ""}>Cancel sign-in</button>${login.error ? `<p>${esc(login.error)}</p>` : ""}</div>`
      : login.error ? `<p class="account-error">${esc(login.error)}</p>` : login.status === "completed" ? '<p class="account-muted">Account connected.</p>' : "";
    const key = JSON.stringify([value.accounts, this.working, this.timezone, [...this.ranges], [...this.buckets], Math.floor(Date.now() / 60000)]);
    if (key === this.rendered) return;
    const active = document.activeElement as HTMLElement | null;
    const focusedId = active?.closest<HTMLElement>(".account-card")?.dataset.accountId;
    const remembered = active?.tagName === "H2" && focusedId ? this.pendingConnectionFocus : undefined;
    const focusedAction = active?.dataset.accountAction || remembered?.action;
    const focusedConnection = active?.dataset.accountAction ? active.dataset.accountId : remembered?.id;
    this.pendingConnectionFocus = focusedConnection && focusedAction ? { id: focusedConnection, action: focusedAction } : undefined;
    const focusedDisclosure = active?.tagName === "SUMMARY" ? active.parentElement?.dataset.connectionGroup : undefined;
    const focusClass = active?.className;
    const focusedRate = Array.from(active?.closest(".account-card")?.querySelectorAll(".burn-rate") || []).indexOf(active!);
    this.rendered = key;
    this.charts.forEach(chart => chart.destroy());
    this.charts = [];
    const cards = this.root.querySelector("#account-cards")!;
    const groups = accountGroups(value.accounts);
    cards.innerHTML = groups.map(group => this.card(group)).join("");
    for (const group of groups) {
      const account = group.account;
      const card = Array.from(cards.children).find(node => (node as HTMLElement).dataset.accountId === account.id)!;
      bindAllowance(card.querySelector<HTMLElement>(".account-allowance")!, bucket => {
        this.buckets.set(account.id, bucket); this.render();
      }, () => { void this.perform("account_refresh", { id: account.id, refresh_local: true }); });
      const picker = card.querySelector<HTMLSelectElement>(".account-range")!;
      picker.addEventListener("change", () => { this.ranges.set(account.id, picker.value as HistoryRange); this.render(); });
      const canvas = card.querySelector<HTMLCanvasElement>("canvas");
      if (canvas) {
        const chart = historyChart(canvas, account.history, this.ranges.get(account.id) || "30", this.timezone);
        if (chart) this.charts.push(chart);
      }
      if (account.id === focusedId && (focusClass === "account-range" || focusClass === "allowance-bucket"))
        card.querySelector<HTMLElement>("." + focusClass)?.focus({ preventScroll: true });
      if (account.id === focusedId && focusedRate >= 0)
        card.querySelectorAll<HTMLElement>(".burn-rate")[focusedRate]?.focus({ preventScroll: true });
      if (account.id === focusedId && active?.tagName === "H2")
        card.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
      if (focusedDisclosure === connectionGroupKey(group))
        card.querySelector<HTMLElement>(".account-connections summary")?.focus({ preventScroll: true });
      if (focusedConnection && group.connections.some(entry => entry.id === focusedConnection)) {
        const buttons = Array.from(card.querySelectorAll<HTMLButtonElement>("[data-account-action]"));
        const nextAction = focusedAction === "disable" ? "enable" : focusedAction === "enable" ? "disable" : focusedAction;
        const button = buttons.find(entry => entry.dataset.accountId === focusedConnection && entry.dataset.accountAction === focusedAction)
          || buttons.find(entry => entry.dataset.accountId === focusedConnection && entry.dataset.accountAction === nextAction)
          || buttons.find(entry => entry.dataset.accountId === focusedConnection);
        if (button && !button.disabled) {
          const disclosure = button.closest<HTMLDetailsElement>("details");
          if (disclosure) { disclosure.open = true; this.openConnections.add(connectionGroupKey(group)); }
          button.focus({ preventScroll: true });
          this.pendingConnectionFocus = undefined;
        } else {
          card.querySelector<HTMLElement>("h2")?.focus({ preventScroll: true });
          if (!button) this.pendingConnectionFocus = undefined;
        }
      }
    }
  }

  private handle(action: string, id?: string) {
    if (action === "copy-link") {
      const login = this.value?.login;
      if (login?.status === "waiting" && login.url) {
        void copyText(login.url).then(() => this.toast("Sign-in link copied. Paste it into your preferred browser."))
          .catch(() => this.toast("Could not copy the sign-in link. Please try again.", true));
      }
      return;
    }
    if (action === "cancel" || action === "open") {
      void this.perform(action === "cancel" ? "account_login_cancel" : "account_login_open"); return;
    }
    const account = this.value?.accounts.find(entry => entry.id === id);
    if (!account) return;
    if (action === "enable" || action === "disable") {
      void this.perform("account_settings", { id, enabled: action === "enable" }); return;
    }
    if (action === "reconnect") { void this.perform("account_login_start", { id }); return; }
    if (action === "rename") {
      this.dialog("Rename account", `<label>Account label<input id="account-label-edit" maxlength="80" value="${esc(account.label)}"></label>`,
        '<button id="account-label-save" class="button primary">Save label</button>', () => {
          document.querySelector("#account-label-save")!.addEventListener("click", async () => {
            const label = document.querySelector<HTMLInputElement>("#account-label-edit")!.value;
            if (await this.perform("account_settings", { id, label })) this.close();
          });
        }); return;
    }
    if (action === "remove") {
      this.dialog("Remove account", `<p>Disconnect ${esc(account.label)} from Insights and remove its saved sign-in?</p>`,
        '<button id="account-remove-confirm" class="button primary">Remove account</button>', () => {
          document.querySelector("#account-remove-confirm")!.addEventListener("click", async () => {
            if (await this.perform("account_remove", { id })) this.close();
          });
        });
    }
  }

  private async perform(action: string, args: unknown = {}) {
    if (this.working) return false;
    this.working = true; this.render();
    try {
      await call(action, args);
      await this.poll();
      return true;
    } catch (error) { this.toast(error instanceof Error ? error.message : String(error), true); return false; }
    finally { this.working = false; this.render(); }
  }

  async poll() {
    if (this.blocked || this.busy) return;
    this.busy = true;
    try { this.value = await call<AccountsSnapshot>("accounts"); this.connectionError = ""; }
    catch { this.connectionError = "Could not update account connections. Retrying…"; }
    finally {
      this.busy = false;
      this.render();
      if (!this.connectionError) this.focusRequestedAccount();
    }
  }
  accept(value: AccountsSnapshot) {
    this.value = value;
    this.connectionError = '';
    this.render();
    this.focusRequestedAccount();
  }
}
