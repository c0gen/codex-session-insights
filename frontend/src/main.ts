import { metricCoverage } from "./metric-coverage";
import "./style.css";
import "./allowance.css";
import "./summary-image.css";
import "./export-feedback.css";
import { ExportFeedback } from "./export-feedback";
import { version as appVersion } from "../package.json";
import { call, getDashboard } from "./api";
import { icon } from "./icons";
import { activity, modelChart, clearCharts } from "./charts";
import type { ActionResponse, Dashboard, Job, JobCompletion } from "./types";
import { esc, dateLabel, button } from "./ui";
import { overview } from "./views/overview";
import { usage } from "./views/usage";
import { projects } from "./views/projects";
import { sources } from "./views/sources";
import { syncDesktopSettings, pollDesktopSettings, setDesktopAccounts } from "./desktop-settings";
import { showJob as updateJob, JobFeedback } from "./job-ui";
import { captureView, restoreView, DeferredReload } from "./live-updates";
import { ProjectMerges } from "./project-merges";
import { DashboardAllowance } from "./allowance";
import { updateTokenKpi } from "./token-kpi";
import { updateTextEquivalents } from "./text-equivalents";
import { AccountsView, accountsPage } from "./views/accounts";
import { SummaryImageCopy, summaryImageSettings, bindSummaryImageSettings } from "./summary-image";
import { TokenActivityPanel } from "./token-activity";
import { DailySessionsPanel } from "./daily-sessions";
import { renderProviderAllowances, bindProviderAllowances, bindProviderSetup } from "./provider-ui";
import { FilterState, restoreFilters } from "./filter-state";
import { FilterBar } from "./filter-bar";

const root = document.querySelector<HTMLDivElement>("#app")!;
let storedFilters: string | null = null;
try { storedFilters = localStorage.getItem("insights-filters"); } catch { /* Storage may be unavailable. */ }
const restored = restoreFilters(window.__INSIGHTS_REPORT__?.filters
  ? JSON.stringify(window.__INSIGHTS_REPORT__.filters) : storedFilters);
const filterState = new FilterState(restored.filters);
const filters = filterState.draft;
let recoveryNotice = restored.recovered;
let data: Dashboard,
  page = "overview",
  mode: "tokens" | "cost" | "prompts" | "lines" = "tokens",
  basis: "total" | "output" = "total",
  modelMode: "tokens" | "cost" = "tokens";
let lastCompleted = 0, polling = false;
const updates = new DeferredReload(() => load(true));
const filterBar = new FilterBar(filterState, () => { void load(); }, () => updates.finishEditing());
const feedback = new JobFeedback((message) => toast(message, true));
const exportFeedback = new ExportFeedback();
const allowance = new DashboardAllowance(() => {
  updates.finishEditing();
  page = "accounts";
  render();
});
const summaryCopy = new SummaryImageCopy(toast);
const tokenActivity = new TokenActivityPanel();
const dailySessions = new DailySessionsPanel();
const accounts = new AccountsView(toast, dialog, closeDialog);
const merges = new ProjectMerges(async (name, args, state) => {
  let result: JobCompletion | null = null;
  await action(name, args, state, completion => { result = completion; });
  return result;
}, dialog, closeDialog);

/** The same status words as the source cards, shortened to fit the sidebar. */
function sourceStatus(s: Dashboard["sources"][number]) {
  if (s.kind === "import" || s.status === "Imported") return "Imported";
  return ({ "No supported history": "No history", "Collection disabled": "Disabled" } as Record<string, string>)[s.status] || s.status;
}

function sidebar() {
  const enabledSources = data.sources.filter((s) => s.enabled);
  const items = [
    ["overview", "Overview", "home"],
    ["usage", "Usage & Cost", "chart"],
    ["projects", "Projects", "folder"],
    ["accounts", "Accounts", "user"],
    ["sources", "Sources", "database"],
  ];
  return `<aside class="sidebar"><div class="brand"><span class="brand-icon">${icon("terminal", 28)}</span><div><strong>Codex</strong><span>Session Insights</span></div></div><nav aria-label="Main navigation">${items
    .filter((x) => !data.exporter || x[0] === "sources")
    .filter((x) => !data.readonly || x[0] !== "accounts")
    .map(
      ([id, label, symbol]) =>
        `<button data-page="${id}" aria-label="${label}" ${page === id ? 'aria-current="page"' : ""} class="nav-item ${page === id ? "active" : ""}">${icon(symbol, 23)}<span>${label}</span>${id === "sources" ? `<b class="badge">${data.sources.length}</b>` : ""}</button>`,
    )
    .join(
      "",
    )}</nav><div class="sidebar-bottom"><div class="source-mini">${enabledSources
    .slice(0, 3)
    .map(
      (s) =>
        `<div title="${esc(`${s.label} · ${sourceStatus(s)}`)}">${icon(s.kind === "import" ? "upload" : "laptop", 17)}<span>${esc(s.label)}</span><small><i class="dot ${["Offline", "No supported history", "Locked", "Unsupported", "Collection disabled"].includes(s.status) ? "offline" : (s.kind === "import" || s.status === "Imported") ? "imported" : ""}"></i>${esc(sourceStatus(s))}</small></div>`,
    )
    .join(
      "",
    )}${enabledSources.length > 3 ? `<button id="sidebar-more-sources" class="source-more">+${enabledSources.length - 3} more</button>` : ""}</div><button id="settings-open" aria-label="Settings" class="local-note">${icon("shield", 20)} Local processing ${icon("settings", 17)}</button></div></aside>`;
}

/** Says which slice of usage the page shows, using the applied (not draft) filters. */
function scopeLabel() {
  const applied = data.filters ?? filters;
  const parts = [
    applied.project_id ? data.options.projects.find((p) => p.id === applied.project_id)?.name : "",
    applied.provider ? ({ codex: "Codex", claude_code: "Claude Code", antigravity: "Antigravity" } as Record<string, string>)[applied.provider] : "",
    applied.model || "",
    applied.source_id ? data.sources.find((s) => s.id === applied.source_id)?.label : "",
    applied.range === "custom" && applied.start ? `${dateLabel(applied.start)} – ${dateLabel(applied.end)}`
      : ({ today: "Today", "7": "Last 7 days", "30": "Last 30 days", "90": "Last 90 days" } as Record<string, string>)[applied.range] || "",
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "Usage across all projects and sources";
}

function render() {
  const view = captureView(root);
  clearCharts();
  tokenActivity.unmount();
  dailySessions.unmount();
  if (data.exporter) page = "sources";
  const title = {
    overview: "Overview",
    usage: "Usage & Cost",
    projects: "Projects",
    accounts: "Accounts",
    sources: data.exporter ? "Mac Exporter" : "Sources",
  }[page];
  const content = {
    overview: () => overview(data, mode, basis, tokenActivity.render(data)),
    usage: () => usage(data, modelMode, dailySessions.render(data)),
    projects: () => projects(data),
    accounts: () => accountsPage(),
    sources: () => exportFeedback.render() + sources(data),
  }[page as "overview"]();
  root.innerHTML = `${sidebar()}<main class="main"><header class="page-header"><div><div class="title-row"><h1>${title}</h1>${data.demo ? '<span class="demo-pill">Demo data</span>' : data.readonly ? '<span class="demo-pill">Saved report</span>' : ""}</div><p>${page === "sources" ? "Manage where your usage comes from" : page === "accounts" ? "Allowance, token history, and banked resets across your accounts" : esc(scopeLabel())}</p></div><div class="header-actions"><span id="update-label">${data.readonly ? "Saved snapshot" : "Updated just now"}</span>${!data.readonly ? `<button id="refresh" class="button icon-only" aria-label="Refresh insights">${icon("refresh", 21)}</button><button id="copy-summary-image" class="button icon-only" aria-label="Copy summary as an image" title="Copy summary as an image">${icon("copy", 20)}</button>${button("export-html", "Export HTML report", "file")}` : ""}</div></header><div id="summary-image-feedback" class="summary-image-feedback" role="status" hidden></div>${page === "overview" ? '<section id="limits-row" class="limits-row" aria-label="Plan limits and allowance, independent of filters" hidden></section>' : ""}${page !== "sources" && page !== "accounts" ? filterBar.render(data) : ""}<div id="job-banner" class="job-banner" hidden></div><div id="dashboard-results" aria-busy="false">${data.coverage.conflicts || data.coverage.parse_errors ? `<div class="coverage-note">${data.coverage.conflicts} unresolved copy conflicts · ${data.coverage.parse_errors} unparsed records. Accepted history is retained.</div>` : ""}${!data.summary.chats && !data.timeline.length && page === "overview" ? `<div class="empty-state panel"><h2>No usage in this view yet</h2><p>Choose another date range or add a folder in Sources. Your regular Codex folders are included automatically.</p><button data-page="sources" class="button primary">${icon("database")}Open Sources</button></div>` : ""}${page === "accounts" ? `<div id="provider-allowance-cards">${renderProviderAllowances(data.provider_allowances, undefined, data.timezone)}</div>` : ""}${page !== "accounts" && page !== "sources" ? metricCoverage(data) : ""}${content}</div><footer class="app-footer"><span>${icon("shield", 14)}Processed on this computer</span><span>Codex Session Insights · v${appVersion}</span></footer></main>`;
  bind();
  filterBar.mount(data);
  summaryCopy.mount(data, page);
  document.querySelector("#export-html")?.toggleAttribute("hidden", page === "accounts");
  allowance.mount(data.usage_limits, !!(data.demo || data.exporter || data.readonly || page === "accounts"),
    data.provider_allowances, data.timezone, data.filters?.provider);
  accounts.mount(!!(data.exporter || data.readonly), data.timezone);
  if (page === "overview") activity(data.timeline, mode, data.coverage.tokens?.state);
  if (page === "overview") tokenActivity.mount(render);
  if (page === "usage") modelChart(data, modelMode);
  if (page === "usage") dailySessions.mount();
  if (data.readonly) {
    document
      .querySelectorAll<
        HTMLButtonElement | HTMLSelectElement | HTMLInputElement
      >(
        ".filters select,.date-fields input,.date-fields button,.source-actions button,.source-footer input,.source-footer button,.merge-project,#settings-open,#settings-inline",
      )
      .forEach((s) => (s.disabled = true));
  }
  if (!data.readonly) showJob(data.job);
  restoreView(root, view);
}

let toastTimer: ReturnType<typeof setTimeout> | undefined;
function toast(message: string, error = false, duration = 6500) {
  clearTimeout(toastTimer);
  const el = document.querySelector<HTMLElement>("#toast")!;
  el.textContent = message;
  el.className = error ? "error" : "";
  el.hidden = false;
  toastTimer = setTimeout(() => (el.hidden = true), duration);
}
async function load(automatic = false) {
  let pending;
  try { pending = filterState.begin(automatic); }
  catch (e) { toast(e instanceof Error ? e.message : String(e), true); return; }
  if (!pending) return;
  // Establish the user request before releasing any queued background reload.
  if (!automatic) updates.finishEditing();
  summaryCopy.setLoading(true);
  if (data) {
    if (automatic) filterBar.feedback();
    else filterBar.refresh(data);
  }
  try {
    const next = await getDashboard({ ...pending.filters });
    if (!filterState.current(pending)) return;
    // An editor may have opened while the dashboard query was in flight.
    if (automatic && updates.editing()) {
      filterState.finish(pending);
      summaryCopy.setLoading(false);
      filterBar.feedback();
      updates.request();
      return;
    }
    const applied = filterState.accept(pending, next.filters ?? pending.filters)!;
    data = { ...next, filters: applied };
    if (!data.readonly) {
      try { localStorage.setItem("insights-filters", JSON.stringify(applied)); } catch { /* The view still works without preferences. */ }
    }
    summaryCopy.setLoading(false);
    render();
    const cleared = (["project_id", "source_id", "model"] as const)
      .filter(key => pending.filters[key] && !applied[key]);
    if (cleared.length) toast("Some selected filters were no longer available and were cleared. Other filters were kept.");
    if (recoveryNotice) {
      recoveryNotice = false;
      toast("Saved filters were invalid and have been reset to All time. You can choose a new range above.");
    }
  } catch (e) {
    if (!filterState.current(pending)) return;
    filterState.fail(pending, e instanceof Error ? e.message : String(e));
    summaryCopy.setLoading(false);
    filterBar.feedback();
    if (data) toast(String(e), true);
    else
      root.innerHTML = `<div class="startup-error"><h1>Couldn’t open insights</h1><p>${esc(e)}</p><button onclick="location.reload()">Try again</button></div>`;
  }
}
async function action(name: string, args: unknown = {}, state?: (value: "queued" | "running") => void, completed?: (value: JobCompletion) => void) {
  try {
    const result = await call<ActionResponse>(name, args);
    if (result?.status === "cancelled") return false;
    if (result?.status === "stopping") throw new Error("The app is closing.");
    if (result?.job_id !== undefined) {
      const completion = feedback.wait(result, state);
      state?.(result.status === "queued" ? "queued" : "running");
      if (result.status === "queued") toast(`Queued · ${result.message}`);
      try {
        const job = await call<Job>("status");
        showJob(job);
        feedback.observe(job);
      } catch { /* Polling can still observe an accepted job. */ }
      const finished = await completion;
      exportFeedback.observe(finished);
      completed?.(finished);
      updates.request();
      return finished.state === "completed";
    }
    if (result?.status !== "cancelling") updates.request();
    return true;
  } catch (e) {
    toast(e instanceof Error ? e.message : String(e), true);
    return false;
  }
}
function on(id: string, callback: () => void) {
  document.getElementById(id)?.addEventListener("click", callback);
}
function showJob(job: Job) {
  updateJob(job, () => { void action("cancel"); });
}
function openWidgetAccount(id: string) {
  updates.finishEditing();
  closeDialog();
  page = "accounts";
  render();
  accounts.focusAccount(id);
}

function bind() {
  document.querySelectorAll<HTMLButtonElement>("[data-page]").forEach(
    (b) =>
      (b.onclick = () => {
        updates.finishEditing();
        page = b.dataset.page!;
        render();
      }),
  );
  on("sidebar-more-sources", () => {
    updates.finishEditing();
    page = "sources";
    render();
  });
  document.querySelectorAll<HTMLButtonElement>("[data-activity]").forEach(
    (b) =>
      (b.onclick = () => {
        mode = b.dataset.activity as typeof mode;
        render();
      }),
  );
  document.querySelectorAll<HTMLButtonElement>("[data-basis]").forEach(
    (b) =>
      (b.onclick = () => {
        basis = b.dataset.basis as typeof basis;
        render();
      }),
  );
  document.querySelectorAll<HTMLButtonElement>("[data-model]").forEach(
    (b) =>
      (b.onclick = () => {
        modelMode = b.dataset.model as typeof modelMode;
        render();
      }),
  );
  on("equivalents-more", () => {
    const el = document.querySelector<HTMLElement>("#extra-equivalents")!;
    el.hidden = !el.hidden;
  });
  on("refresh", () => page === "accounts" ? void call("account_refresh", { refresh_local: true }).then(() => accounts.poll()).catch(e => toast(String(e), true)) : action("refresh"));
  on("rebuild-index", () => action("refresh", { rebuild: true }));
  bindProviderSetup(root, async (target, operation) => {
    if (operation === "preview") {
      const preview = await call("provider_setup_preview", { target });
      dialog("Configuration preview", `<pre>${esc(JSON.stringify(preview, null, 2))}</pre>`, "", () => {});
    } else {
      await action("provider_setup", { target, operation });
      await load();
    }
  });
  on("add-source", () => dialog("Add session folder", `<label>Tool <select id="source-provider"><option value="codex">Codex</option><option value="claude_code">Claude Code</option><option value="antigravity">Antigravity (public transcripts)</option></select></label><p>For Antigravity, choose its brain folder. Public transcripts and official hooks supply recorded usage.</p>`, `<button id="source-choose" class="button primary">Choose folder</button>`, () => on("source-choose", () => {
    const provider = document.querySelector<HTMLSelectElement>("#source-provider")!.value;
    closeDialog();
    void action("add_source", { provider });
  })));
  on("import-snapshot", () => action("import"));
  on("export-snapshot", () => action("export"));
  on("settings-open", settings);
  on("settings-inline", settings);
  on("export-html", () => {
    const exportFilters = filterState.exportSnapshot();
    dialog(
      "Export HTML report",
      `<p>Save this filtered view as a standalone, offline report.</p><label class="toggle-label"><input id="anonymous" type="checkbox" checked> Replace project and source names with generic labels</label>`,
      `<button id="report-save" class="button primary">Save report</button>`,
      () =>
        on("report-save", () => {
          const anonymous = (
            document.querySelector("#anonymous") as HTMLInputElement
          ).checked;
          closeDialog();
          action("export_html", { filters: exportFilters, anonymous });
        }),
    );
  });
  document
    .querySelectorAll<HTMLInputElement>("[data-enabled]")
    .forEach(
      (el) =>
        (el.onchange = async () => {
          const checked = el.checked;
          el.disabled = true;
          el.setAttribute("data-pending-edit", "true");
          const saved = await action("source_enabled", {
            id: el.dataset.enabled,
            enabled: checked,
          });
          if (el.isConnected) {
            el.removeAttribute("data-pending-edit");
            el.disabled = false;
            if (!saved) el.checked = !checked;
          }
          void updates.flush();
        }),
    );
  document.querySelectorAll<HTMLButtonElement>("[data-forget]").forEach(
    (el) =>
      (el.onclick = () => {
        if (
          confirm(
            "Forget this source’s indexed history? Original chats will remain untouched.",
          )
        )
          action("forget_source", { id: el.dataset.forget });
      }),
  );
  document.querySelectorAll<HTMLTableRowElement>("tr[data-project]").forEach(
    (row) =>
      (row.onclick = (event) => {
        if (data.readonly || (event.target as Element).closest("button,input,.project-check"))
          return;
        filters.project_id = row.dataset.project!;
        page = "overview";
        load();
      }),
  );
  merges.bind(data);
}
function dialog(
  title: string,
  body: string,
  footer: string,
  bindDialog: () => void,
) {
  document.querySelector("#dialog-root")!.innerHTML =
    `<div class="modal-backdrop"><section class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}"><div class="panel-heading"><h2>${title}</h2><button id="dialog-close" class="icon-button" aria-label="Close dialog">${icon("close")}</button></div><div class="modal-body">${body}</div><div class="modal-footer">${footer}</div></section></div>`;
  on("dialog-close", closeDialog);
  bindDialog();
  document
    .querySelector<HTMLElement>(".modal input,.modal select,.modal button")
    ?.focus();
}
function closeDialog() {
  document.querySelector("#dialog-root")!.innerHTML = "";
  void updates.flush();
}
function validTimezone(zone: string) {
  if (!zone) return false;
  try { new Intl.DateTimeFormat("en-US", { timeZone: zone }); return true; } catch { return false; }
}
/** Suggestions where the browser can list zones (not Safari 15); typing any IANA name still works. */
function timezoneOptions() {
  const supported = (Intl as unknown as { supportedValuesOf?: (key: string) => string[] }).supportedValuesOf;
  if (!supported) return "";
  try { return `<datalist id="timezone-options">${supported("timeZone").map(zone => `<option value="${esc(zone)}"></option>`).join("")}</datalist>`; }
  catch { return ""; }
}
function settings() {
  dialog(
    "Settings",
    `<h3 class="settings-section">General</h3><label>Computer label<input id="device-label" value="${esc(data.settings.device_label)}"></label><label>Display timezone<input id="timezone" value="${esc(data.timezone)}" placeholder="America/New_York" list="timezone-options" autocomplete="off" spellcheck="false"></label>${timezoneOptions()}<p id="timezone-error" class="settings-error" role="alert" hidden></p>${!data.exporter ? summaryImageSettings() : ""}<h3 class="settings-section">Pricing</h3><label>Assumed Fast share for unlogged tiers (%)<input id="fast-share" type="number" min="0" max="100" value="${data.settings.assumed_fast_percent}"></label><p class="fine-print">Observed tiers always take precedence. Changing timezone or pricing recalculates stored usage.</p><button id="pricing-import" class="button">${icon("upload")}Import pricing catalog</button>${!data.demo && !data.exporter ? `<h3 class="settings-section">Live account data</h3><label class="toggle-label"><input id="live-usage-enabled" type="checkbox" ${data.settings.live_usage_enabled !== false ? "checked" : ""}> Fetch live account data</label><p class="fine-print">Uses installed Codex and your existing ChatGPT sign-in. Refreshes allowance every 60 seconds and account history every five minutes. Account data stays in memory and is excluded from exports.</p><label class="toggle-label"><input id="claude-usage-enabled" type="checkbox" ${data.settings.claude_usage_enabled ? "checked" : ""}> Check Claude plan limits</label><p class="fine-print">Runs your installed Claude Code's <code>/usage</code> command every five minutes for the 5-hour and weekly limits. Claude Code signs in on its own: this app never reads Claude credentials and makes no model requests. Readings stay in memory and are excluded from exports.</p><label class="toggle-label"><input id="antigravity-usage-enabled" type="checkbox" ${data.settings.antigravity_usage_enabled ? "checked" : ""}> Check Antigravity allowance</label><p class="fine-print">Runs the official Antigravity CLI’s read-only <code>/usage</code> command every five minutes. Install agy and sign in there. No model turn is started. Readings stay in memory and are excluded from exports.</p>` : ""}`,
    `<button id="settings-cancel" class="button">Cancel</button><button id="settings-save" class="button primary">Save settings</button>`,
    () => {
      on("settings-cancel", closeDialog);
      bindSummaryImageSettings(toast);
      document.querySelector<HTMLInputElement>("#live-usage-enabled")?.addEventListener("change", async event => {
        const input = event.target as HTMLInputElement;
        input.disabled = true;
        const enabled = input.checked;
        const saved = await action("usage_limits_settings", { enabled });
        if (saved) {
          data.settings.live_usage_enabled = enabled;
          if (data.usage_limits) data.usage_limits.enabled = enabled;
          await allowance.poll();
        } else input.checked = !enabled;
        input.disabled = false;
      });
      for (const provider of ["claude", "antigravity"] as const) {
        document.querySelector<HTMLInputElement>(`#${provider}-usage-enabled`)?.addEventListener("change", async event => {
          const input = event.target as HTMLInputElement;
          input.disabled = true;
          const enabled = input.checked;
          const saved = await action(`${provider}_usage_settings`, { enabled });
          if (saved) {
            data.settings[`${provider}_usage_enabled`] = enabled;
            await pollProviderAllowances();
          } else input.checked = !enabled;
          input.disabled = false;
        });
      }
      if (data.desktop?.available) {
        const section = document.createElement("section");
        section.id = "desktop-preferences";
        document.querySelector(".modal-body")!.append(section);
        syncDesktopSettings(data.desktop, allowance.snapshot());
        pollDesktopSettings(settings).catch(() => {});
      }
      on("pricing-import", () => {
        closeDialog();
        action("import_pricing");
      });
      on("settings-save", async () => {
        const modal = document.querySelector<HTMLElement>('[role="dialog"]')!;
        const save = modal.querySelector<HTMLButtonElement>("#settings-save")!;
        const zone = modal.querySelector<HTMLInputElement>("#timezone")!;
        const zoneError = modal.querySelector<HTMLElement>("#timezone-error")!;
        if (!validTimezone(zone.value.trim())) {
          zoneError.textContent = `“${zone.value}” isn’t a recognized IANA timezone, such as America/New_York or Europe/London.`;
          zoneError.hidden = false;
          zone.setAttribute("aria-invalid", "true");
          zone.focus();
          return;
        }
        zoneError.hidden = true;
        zone.removeAttribute("aria-invalid");
        const args = {
          device_label: (
            document.querySelector("#device-label") as HTMLInputElement
          ).value,
          timezone: zone.value.trim(),
          assumed_fast_percent: Number(
            (document.querySelector("#fast-share") as HTMLInputElement).value,
          ),
        };
        const inputs = Array.from(modal.querySelectorAll<HTMLInputElement>("#device-label,#timezone,#fast-share"));
        inputs.forEach((input) => input.disabled = true);
        save.disabled = true;
        const saved = await action("settings", args, (state) => {
          save.textContent = state === "queued" ? "Queued" : "Saving…";
        });
        if (saved) {
          if (modal.isConnected) closeDialog();
          toast("Settings saved.");
        } else {
          inputs.forEach((input) => input.disabled = false);
          save.disabled = false;
          save.textContent = "Save settings";
        }
      });
    },
  );
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDialog();
});
document.body.insertAdjacentHTML("beforeend", '<div id="dialog-root"></div><div id="toast" role="status" hidden></div>');
root.innerHTML =
  '<div class="loading"><span class="spinner"></span>Opening your insights…</div>';
load();
window.addEventListener("pywebviewready", () => { if (data) summaryCopy.mount(data, page); });
if (!window.__INSIGHTS_REPORT__)
  setInterval(() => { void allowance.poll().catch(() => {}); }, 2000);
if (!window.__INSIGHTS_REPORT__)
  setInterval(async () => {
    await accounts.poll();
    const snapshot = accounts.snapshot();
    setDesktopAccounts(snapshot);
    if (data && snapshot?.token_total) {
      data.account_token_total = snapshot.token_total;
      updateTokenKpi(data);
      updateTextEquivalents(data, basis);
    }
  }, 2000);
if (!window.__INSIGHTS_REPORT__)
  setInterval(async () => {
    if (polling) return;
    polling = true;
    try {
      const job = await call<Job>("status");
      showJob(job);
      feedback.observe(job);
      const finished = (job.completed || []).filter((item) => item.id > lastCompleted);
      for (const item of finished) lastCompleted = Math.max(lastCompleted, item.id);
      if (data && (job.revision !== data.revision || finished.length)) {
        updates.request();
      }
      if (data?.desktop?.available) await pollDesktopSettings(settings, openWidgetAccount);
    } catch {
      /* A closing desktop window shuts down the server. */
    } finally { polling = false; }
  }, 2000);

let providerPolling = false;
async function pollProviderAllowances() {
  if (!data || providerPolling) return;
  providerPolling = true;
  try {
    data.provider_allowances = await call("provider_allowances");
    allowance.setProviders(data.provider_allowances);
    const cards = root.querySelector<HTMLElement>("#provider-allowance-cards");
    const markup = renderProviderAllowances(data.provider_allowances, undefined, data.timezone);
    if (cards && cards.dataset.markup !== markup) {
      const refocus = cards.contains(document.activeElement) && document.activeElement?.matches("[data-provider-usage-refresh]");
      cards.innerHTML = markup;
      cards.dataset.markup = markup;
      if (refocus) cards.querySelector<HTMLElement>("[data-provider-usage-refresh]")?.focus({ preventScroll: true });
    }
  } catch { /* Closing clients leave the last reading visible with expiry. */ }
  finally { providerPolling = false; }
}
if (!window.__INSIGHTS_REPORT__) {
  bindProviderAllowances(root, async provider => {
    await call(provider === "antigravity" ? "refresh_antigravity_usage" : "refresh_claude_usage");
    await pollProviderAllowances();
  });
  setInterval(() => { void pollProviderAllowances(); }, 2000);
}
