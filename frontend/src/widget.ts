import { historyCoverage } from "./history-coverage";
import "./widget.css";
import { renderWidgetProviders } from "./widget-providers";
import { WidgetRefreshControls } from "./widget-controls";
import { bindWidgetTooltips } from "./widget-tooltips";
import { call } from "./api";
import { compact, currency } from "./format";
import { esc } from "./ui";
import { bindWidgetWindow } from "./widget-window";
import { renderWidgetAccounts, widgetAccountGroups } from "./widget-accounts";
import { bindWidgetDetails, detailsToggle } from "./widget-details";
import type { AccountsSnapshot } from "./account-types";
import type { WidgetTotals, WidgetMetric, WidgetSummary, UsageLimits, DesktopState, ProviderAllowance } from "./types";

const root = document.querySelector<HTMLElement>("#widget")!;
root.tabIndex = 0;
root.setAttribute(
  "aria-label",
  "Usage widget. Drag a heading to move; drag the top or bottom edge to resize. Right-click or press Shift+F10 for controls.",
);
root.innerHTML = `<div class="widget-resize-handle" data-resize="top" title="Drag to resize height; use Settings for keyboard controls" aria-hidden="true"></div>
  <div id="widget-toolbar" role="toolbar" aria-label="Widget controls">${detailsToggle}<button id="widget-refresh-all" title="Refresh displayed accounts and reread local provider snapshots">Refresh all</button><button id="widget-menu" aria-label="Widget menu" title="Widget menu">⋯</button><span id="widget-indicator" hidden tabindex="0" role="img" aria-label="Widget status"></span></div>
  <main id="widget-scroll" aria-label="Usage and accounts" tabindex="0"><div id="widget-content"><div id="widget-details"><div class="widget-details-clip"><div id="totals"><div class="empty">Loading usage…</div></div></div></div><section id="widget-allowance" aria-label="Account usage" hidden></section><section id="provider-allowances" aria-label="Local provider allowances" hidden></section></div></main>
  <div class="widget-resize-handle" data-resize="bottom" title="Drag to resize height; use Settings for keyboard controls" aria-hidden="true"></div><span class="sr-only" role="status" id="widget-status"></span>`;
const totals = root.querySelector<HTMLElement>("#totals")!;
const status = root.querySelector<HTMLElement>("#widget-status")!;
const indicator = root.querySelector<HTMLElement>("#widget-indicator")!;
let rendered = "";
let loading = false;
let snapshotStale = false;
let desktop: DesktopState;
let limits: UsageLimits | undefined;
let accounts: AccountsSnapshot | undefined;
let timezone = "UTC";
let providers: ProviderAllowance[] | undefined;
const allowanceRoot = root.querySelector<HTMLElement>("#widget-allowance")!;
const providerRoot = root.querySelector<HTMLElement>("#provider-allowances")!;

function renderProviders() {
  const markup = desktop?.preferences?.show_usage_remaining ? renderWidgetProviders(providers, timezone) : "";
  if (providerRoot.dataset.markup !== markup) {
    const scroller = root.querySelector<HTMLElement>("#widget-scroll")!;
    const scroll = scroller.scrollTop;
    const focused = document.activeElement as HTMLElement | null;
    const provider = focused?.closest<HTMLElement>("[data-provider]")?.dataset.provider;
    const index = Array.from(focused?.closest("[data-provider]")?.querySelectorAll("[tabindex]") || []).indexOf(focused!);
    providerRoot.innerHTML = markup;
    providerRoot.dataset.markup = markup;
    const card = Array.from(providerRoot.querySelectorAll<HTMLElement>("[data-provider]")).find(card => card.dataset.provider === provider);
    if (provider) (card?.querySelectorAll<HTMLElement>("[tabindex]")[index] || root.querySelector<HTMLElement>("#widget-refresh-all"))?.focus({ preventScroll: true });
    scroller.scrollTop = scroll;
  }
  providerRoot.hidden = !markup;
}

function renderAllowance() {
  if (!desktop) return;
  controls.reconcile();
  renderWidgetAccounts(allowanceRoot, accounts, limits, desktop, timezone, {
    pending: controls.pending, errors: controls.errors, snapshotStale,
    refresh: id => { void controls.refresh(id); },
    open: async account_id => {
      try { await call("desktop_command", { command: "show_account", account_id }); }
      catch { setStatus("Could not open account details · try again", true); }
    },
    select: async (accountId, bucket) => {
      try {
        const buckets = { ...desktop.preferences?.widget_account_buckets, [accountId]: bucket };
        desktop = await call<DesktopState>("desktop_settings", {
          widget_account_buckets: buckets, ...(accountId === "current" ? { usage_remaining_bucket: bucket } : {}),
        });
        delete allowanceRoot.dataset.markup;
        renderAllowance();
      } catch { setStatus("Could not save allowance bucket · retry in Settings", true); }
    },
  });
  renderProviders();
  root.toggleAttribute("data-accounts", !allowanceRoot.hidden);
  const refreshAll = root.querySelector<HTMLButtonElement>("#widget-refresh-all")!;
  refreshAll.hidden = allowanceRoot.hidden;
  refreshAll.disabled = controls.busy();
  refreshAll.setAttribute("aria-busy", String(controls.busy()));
  syncDetails();
  measure();
}

function setStatus(message: string, failed = false) {
  indicator.hidden = !failed;
  indicator.title = message;
  // The shared widget tooltip shows the failure on hover and keyboard focus.
  indicator.dataset.tooltip = message;
  indicator.setAttribute("aria-label", message);
  const accessible = failed
    ? message
    : indicator.dataset.failed
      ? "Usage updated"
      : "";
  if (status.textContent !== accessible) status.textContent = accessible;
  if (failed) indicator.dataset.failed = "true";
  else delete indicator.dataset.failed;
}
const measure = bindWidgetWindow(root, (message) => setStatus(message, true));
const syncDetails = bindWidgetDetails(root, () => desktop, state => { desktop = state; }, measure,
  message => setStatus(message, true));
const controls = new WidgetRefreshControls(() => widgetAccountGroups(accounts, limits, desktop).map(group => group.account),
  renderAllowance, refresh, setStatus);
bindWidgetTooltips(root);

function annotated(text: string, description: string, className = "") {
  return `<span class="${className}" title="${esc(description)}" aria-label="${esc(description)}">${text}</span>`;
}

function shortNumber(number: number) {
  const formatted = compact(number);
  return formatted.length <= 9 ? formatted : number.toExponential(1);
}

  let sourceStates: Record<string, number> | undefined;
  function value(metric: WidgetMetric, summary: WidgetTotals) {
    const history = historyCoverage(sourceStates);
    const historyHint = history ? ` · ${history}. Previously accepted history is retained.` : '';
  if ((metric === "tokens" || metric === "cost") && summary.token_coverage === "unavailable") {
      // No recorded responses at all is a true zero, like the lines and chats beside it.
      if (summary.metric_coverage?.total?.observations === 0)
        return annotated(metric === "tokens" ? "0" : currency(0), "No recorded activity in this period yet" + historyHint);
      return annotated("—", "Token counters unavailable in this scope" + historyHint);
  }
  if (metric === "tokens" || metric === "chats") {
    const number = metric === "tokens" ? summary.total_tokens : summary.chats;
    return annotated(
        shortNumber(number) + (metric === "tokens" && (summary.token_coverage === "partial" || history) ? "*" : ""),
        `${number.toLocaleString("en-US")} ${metric === "tokens" ? "tokens" : "main chats"}${historyHint}`,
    );
  }
  if (metric === "cost") {
    const partial = summary.total_tokens > 0 && summary.priced_percent < 100;
    const amount =
      Math.abs(summary.cost) >= 1000
        ? `$${shortNumber(summary.cost)}`
        : currency(summary.cost);
    const text =
      partial && summary.priced_percent === 0
        ? "Unpriced"
        : amount + (partial ? "*" : "");
    return annotated(
      text,
        (partial && summary.priced_percent === 0 ? 'Price unavailable for recorded usage.' : `${currency(summary.cost)} estimated API-equivalent cost in USD, not a subscription bill. ${summary.priced_percent}% priced.`) + historyHint,
    );
  }
  const partial = summary.change_coverage === "partial";
  return annotated(
    `<span class="added">+${shortNumber(summary.lines_added)}</span><span class="removed">−${shortNumber(summary.lines_removed)}${partial ? "*" : ""}</span>`,
    `${summary.lines_added.toLocaleString("en-US")} lines added; ${summary.lines_removed.toLocaleString("en-US")} removed. Observed edits; repeated edits count.${partial ? " Partial observation." : ""}`,
    "lines",
  );
}

function render(data: WidgetSummary) {
  if (!desktop || (data.desktop.revision ?? 0) >= (desktop.revision ?? 0)) desktop = data.desktop;
  limits = data.usage_limits;
  accounts = data.accounts;
  providers = data.provider_allowances;
  timezone = data.timezone;
  sourceStates = data.source_states;
  const metrics =
    desktop.preferences?.metrics ||
    (["tokens", "cost", "lines"] as WidgetMetric[]);
  const key = JSON.stringify([
    data.revision,
    data.date,
    data.timezone,
    metrics,
    data.today,
    data.all_time,
    data.source_states,
  ]);
  const labels = {
    tokens: "Tokens",
    cost: "Cost",
    lines: "Lines",
    chats: "Main chats",
  };
  if (key !== rendered) {
    rendered = key;
    totals.innerHTML = metrics.length
      ? `<table><thead><tr><th scope="col"><span class="sr-only">Usage</span></th><th scope="col">Today</th><th scope="col">All time</th></tr></thead><tbody>${metrics.map((metric) => `<tr class="metric-${metric}"><th scope="row">${labels[metric]}</th><td>${value(metric, data.today)}</td><td>${value(metric, data.all_time)}</td></tr>`).join("")}</tbody></table>`
      : `<div class="empty"><button data-action="show_settings">Select metrics in Settings</button></div>`;
  }
  const message = data.job.error
    ? "Update failed · open dashboard"
    : data.job.running
      ? "Updating usage…"
      : `Updated ${new Date(data.generated_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit", timeZone: data.timezone })} · ${data.timezone}`;
  setStatus(message, !!data.job.error);
  renderAllowance();
  measure();
}

async function refresh() {
  renderProviders();
  // The native widget is hidden until its first measured layout arrives.
  if (loading || (document.hidden && rendered)) return;
  loading = true;
  try {
    const data = await call<WidgetSummary>("widget_summary");
    snapshotStale = false;
    render(data);
  } catch {
    snapshotStale = true;
    if (!rendered) totals.innerHTML = `<div class="empty">Connecting…</div>`;
    setStatus("Disconnected · retrying…", true);
    renderAllowance();
    measure();
  } finally {
    loading = false;
  }
}
root.addEventListener("click", async (event) => {
  if ((event.target as Element).closest("#widget-refresh-all")) {
    void controls.refreshAll();
    for (const profile of providers || []) {
      if (profile.check?.enabled) void call(profile.provider === "antigravity" ? "refresh_antigravity_usage" : "refresh_claude_usage").catch(() => undefined);
    }
    return;
  }
  if (!(event.target as Element).closest('[data-action="show_settings"]'))
    return;
  try {
    await call("desktop_command", { command: "show_settings" });
  } catch {
    setStatus("Could not open Settings · retrying…", true);
  }
});
document.addEventListener("visibilitychange", refresh);
window.addEventListener("pywebviewready", refresh);
void refresh();
setInterval(refresh, 2000);
