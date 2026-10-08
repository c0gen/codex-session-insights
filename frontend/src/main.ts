import "./style.css";
import { call, getDashboard } from "./api";
import { icon } from "./icons";
import { activity, modelChart, clearCharts, compact, currency } from "./charts";
import type { Dashboard, Filters, Job } from "./types";
import { esc, count, dateLabel, button } from "./ui";
import { overview } from "./views/overview";
import { usage } from "./views/usage";
import { projects } from "./views/projects";
import { sources } from "./views/sources";

const root = document.querySelector<HTMLDivElement>("#app")!;
let saved: Filters | null = null;
try {
  saved = JSON.parse(localStorage.getItem("insights-filters") || "null");
} catch {
  /* Ignore obsolete or damaged local preferences. */
}
let filters: Filters = window.__INSIGHTS_REPORT__?.filters ||
  saved || {
    range: "all",
    project_id: "",
    model: "",
    source_id: "",
    start: "",
    end: "",
  };
let data: Dashboard,
  page = "overview",
  mode: "tokens" | "cost" | "prompts" | "lines" = "tokens",
  basis: "total" | "output" = "total",
  modelMode: "tokens" | "cost" = "tokens";
let request = 0,
  lastJobRunning = false;

function sidebar() {
  const items = [
    ["overview", "Overview", "home"],
    ["usage", "Usage & Cost", "chart"],
    ["projects", "Projects", "folder"],
    ["sources", "Sources", "database"],
  ];
  return `<aside class="sidebar"><div class="brand"><span class="brand-icon">${icon("terminal", 28)}</span><div><strong>Codex</strong><span>Session Insights</span></div></div><nav aria-label="Main navigation">${items
    .filter((x) => !data.exporter || x[0] === "sources")
    .map(
      ([id, label, symbol]) =>
        `<button data-page="${id}" class="nav-item ${page === id ? "active" : ""}">${icon(symbol, 23)}<span>${label}</span>${id === "sources" ? `<b class="badge">${data.sources.length}</b>` : ""}</button>`,
    )
    .join(
      "",
    )}</nav><div class="sidebar-bottom"><div class="source-mini">${data.sources
    .filter((s) => s.enabled)
    .slice(0, 3)
    .map(
      (s) =>
        `<div>${icon("laptop", 17)}<span>${esc(s.label)}</span><small><i class="dot ${s.status === "Offline" ? "offline" : (s.kind === "import" || s.status === "Imported") ? "imported" : ""}"></i>${(s.kind === "import" || s.status === "Imported") ? "Imported" : s.status === "Offline" ? "Offline" : "Live"}</small></div>`,
    )
    .join(
      "",
    )}</div><button id="settings-open" class="local-note">${icon("shield", 20)} Local processing ${icon("settings", 17)}</button></div></aside>`;
}

function filterBar() {
  const ranges: [string, string][] = [
    ["all", "All time"],
    ["today", "Today"],
    ["7", "Last 7 days"],
    ["30", "Last 30 days"],
    ["90", "Last 90 days"],
    ["custom", "Custom dates"],
  ];
  const select = (id: string, values: [string, string][], value: string) =>
    `<select id="${id}" aria-label="${id.replace("filter-", "")}">${values.map(([v, l]) => `<option value="${esc(v)}" ${v === value ? "selected" : ""}>${esc(l)}</option>`).join("")}</select>`;
  const dates = data.timeline.length
    ? `${dateLabel(data.timeline[0].day)} – ${dateLabel(data.timeline[data.timeline.length - 1].day)}, ${data.timeline[data.timeline.length - 1].day.slice(0, 4)}`
    : "No activity in this range";
  return `<div class="filters ${data.readonly ? "readonly" : ""}">${select("filter-range", ranges, filters.range)}${select("filter-project", [["", "All projects"], ...data.options.projects.map((p) => [p.id, p.name] as [string, string])], filters.project_id)}${select("filter-model", [["", "All models"], ...data.options.models.map((m) => [m, m] as [string, string])], filters.model)}${select("filter-source", [["", "All sources"], ...data.sources.map((s) => [s.id, s.label] as [string, string])], filters.source_id)}<span class="date-caption">${esc(dates)}</span>${filters.range === "custom" ? `<div class="date-fields"><label>From <input id="date-start" type="date" value="${esc(filters.start)}"></label><label>To <input id="date-end" type="date" value="${esc(filters.end)}"></label><button id="date-apply" class="button small">Apply</button></div>` : ""}</div>`;
}

function render() {
  clearCharts();
  if (data.exporter) page = "sources";
  const title = {
    overview: "Overview",
    usage: "Usage & Cost",
    projects: "Projects",
    sources: data.exporter ? "Mac Exporter" : "Sources",
  }[page];
  const content = {
    overview: () => overview(data, mode, basis),
    usage: () => usage(data, modelMode),
    projects: () => projects(data),
    sources: () => sources(data),
  }[page as "overview"]();
  root.innerHTML = `${sidebar()}<main class="main"><header class="page-header"><div><div class="title-row"><h1>${title}</h1>${data.demo ? '<span class="demo-pill">Demo data</span>' : data.readonly ? '<span class="demo-pill">Saved report</span>' : ""}</div><p>${page === "sources" ? "Manage where your usage comes from" : "Usage across all projects and sources"}</p></div><div class="header-actions"><span id="update-label">${data.readonly ? "Saved snapshot" : "Updated just now"}</span>${!data.readonly ? `<button id="refresh" class="button icon-only" aria-label="Refresh insights">${icon("refresh", 21)}</button>${button("export-html", "Export HTML report", "file")}` : ""}</div></header>${page !== "sources" ? filterBar() : ""}<div id="job-banner" class="job-banner" hidden></div>${data.coverage.conflicts || data.coverage.parse_errors ? `<div class="coverage-note">${data.coverage.conflicts} unresolved copy conflicts · ${data.coverage.parse_errors} unparsed records. Accepted history is retained.</div>` : ""}${!data.summary.total_tokens && page === "overview" ? `<div class="empty-state panel"><h2>No usage in this view yet</h2><p>Choose another date range or add a folder in Sources. Your regular Codex folders are included automatically.</p><button data-page="sources" class="button primary">${icon("database")}Open Sources</button></div>` : ""}${content}<footer class="app-footer"><span>${icon("shield", 14)}Processed on this computer</span><span>Codex Session Insights · v0.1.0</span></footer></main><div id="dialog-root"></div><div id="toast" role="status" hidden></div>`;
  bind();
  if (page === "overview") activity(data.timeline, mode);
  if (page === "usage") modelChart(data, modelMode);
  if (data.readonly) {
    document
      .querySelectorAll<
        HTMLButtonElement | HTMLSelectElement | HTMLInputElement
      >(
        ".filters select,.date-fields input,.date-fields button,.source-actions button,.source-footer input,.source-footer button,.merge-project,#settings-open,#settings-inline",
      )
      .forEach((s) => (s.disabled = true));
  }
  showJob(data.job);
}

function toast(message: string, error = false) {
  const el = document.querySelector<HTMLElement>("#toast")!;
  el.textContent = message;
  el.className = error ? "error" : "";
  el.hidden = false;
  setTimeout(() => (el.hidden = true), 6500);
}
async function load() {
  const id = ++request;
  try {
    const next = await getDashboard(filters);
    if (id !== request) return;
    data = next;
    render();
  } catch (e) {
    if (data) toast(String(e), true);
    else
      root.innerHTML = `<div class="startup-error"><h1>Couldn’t open insights</h1><p>${esc(e)}</p><button onclick="location.reload()">Try again</button></div>`;
  }
}
async function action(name: string, args: unknown = {}) {
  try {
    const result = await call<{ status?: string }>(name, args);
    if (result?.status === "busy")
      toast("An update is already running. Please wait or cancel it.");
    else if (result?.status !== "cancelled") await load();
  } catch (e) {
    toast(e instanceof Error ? e.message : String(e), true);
  }
}
function on(id: string, callback: () => void) {
  document.getElementById(id)?.addEventListener("click", callback);
}
function showJob(job: Job) {
  const banner = document.querySelector<HTMLElement>("#job-banner");
  if (!banner) return;
  banner.hidden = !job.running;
  banner.innerHTML = `<span class="spinner"></span><span>${esc(job.progress?.phase || job.message)}${job.progress?.sessions ? ` · ${count(job.progress.sessions)} session facts` : job.progress?.files ? ` · ${count(job.progress.files)} files · ${compact((job.progress.bytes_read || 0) / 1024 / 1024)} MB read` : ""}</span><button id="cancel-job" class="text-button">Cancel</button>`;
  on("cancel-job", () => action("cancel"));
  const label = document.querySelector("#update-label");
  if (label && job.running) label.textContent = job.message;
}
function bind() {
  document.querySelectorAll<HTMLButtonElement>("[data-page]").forEach(
    (b) =>
      (b.onclick = () => {
        page = b.dataset.page!;
        render();
      }),
  );
  ["range", "project", "model", "source"].forEach((name) =>
    document
      .querySelector<HTMLSelectElement>("#filter-" + name)
      ?.addEventListener("change", (event) => {
        const value = (event.target as HTMLSelectElement).value;
        const key = {
          range: "range",
          project: "project_id",
          model: "model",
          source: "source_id",
        }[name] as keyof Filters;
        filters[key] = value;
        localStorage.setItem("insights-filters", JSON.stringify(filters));
        if (name === "range" && value === "custom") {
          filters.start ||=
            data.timeline[0]?.day || new Date().toISOString().slice(0, 10);
          filters.end ||= data.timeline[data.timeline.length - 1]?.day || filters.start;
          render();
        } else load();
      }),
  );
  on("date-apply", () => {
    filters.start = (
      document.querySelector("#date-start") as HTMLInputElement
    ).value;
    filters.end = (
      document.querySelector("#date-end") as HTMLInputElement
    ).value;
    localStorage.setItem("insights-filters", JSON.stringify(filters));
    load();
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
  on("refresh", () => action("refresh"));
  on("rebuild-index", () => action("refresh", { rebuild: true }));
  on("add-source", () => action("add_source"));
  on("import-snapshot", () => action("import"));
  on("export-snapshot", () => action("export"));
  on("settings-open", settings);
  on("settings-inline", settings);
  on("export-html", () =>
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
          action("export_html", { filters, anonymous });
        }),
    ),
  );
  document
    .querySelectorAll<HTMLInputElement>("[data-enabled]")
    .forEach(
      (el) =>
        (el.onchange = () =>
          action("source_enabled", {
            id: el.dataset.enabled,
            enabled: el.checked,
          })),
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
  document
    .querySelector<HTMLInputElement>("#project-search")
    ?.addEventListener("input", (event) => {
      const text = (event.target as HTMLInputElement).value.toLowerCase();
      document
        .querySelectorAll<HTMLTableRowElement>("tbody tr")
        .forEach(
          (row) =>
            (row.hidden = !row.textContent!.toLowerCase().includes(text)),
        );
    });
  document.querySelectorAll<HTMLTableRowElement>("tr[data-project]").forEach(
    (row) =>
      (row.onclick = (event) => {
        if (data.readonly || (event.target as Element).closest("button"))
          return;
        filters.project_id = row.dataset.project!;
        page = "overview";
        load();
      }),
  );
  document.querySelectorAll<HTMLButtonElement>(".merge-project").forEach(
    (b) =>
      (b.onclick = () =>
        dialog(
          "Merge project group",
          `<p>Group this workspace with an existing project. Usage is recalculated; original chats stay in place.</p><label>Target project<select id="merge-target">${data.options.projects
            .filter((p) => p.id !== b.dataset.id)
            .map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`)
            .join("")}</select></label>`,
          `<button id="merge-save" class="button primary">Merge groups</button>`,
          () =>
            on("merge-save", () => {
              const target = (
                document.querySelector("#merge-target") as HTMLSelectElement
              ).value;
              closeDialog();
              action("alias", { source: b.dataset.id, target });
            }),
        )),
  );
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
}
function settings() {
  dialog(
    "Settings",
    `<label>Computer label<input id="device-label" value="${esc(data.settings.device_label)}"></label><label>Display timezone<input id="timezone" value="${esc(data.timezone)}" placeholder="America/New_York"></label><label>Assumed Fast share for unlogged tiers (%)<input id="fast-share" type="number" min="0" max="100" value="${data.settings.assumed_fast_percent}"></label><p class="fine-print">Observed tiers always take precedence. Changing timezone or pricing recalculates stored usage.</p><button id="pricing-import" class="button">${icon("upload")}Import pricing catalog</button>`,
    `<button id="settings-save" class="button primary">Save settings</button>`,
    () => {
      on("pricing-import", () => {
        closeDialog();
        action("import_pricing");
      });
      on("settings-save", () => {
        const args = {
          device_label: (
            document.querySelector("#device-label") as HTMLInputElement
          ).value,
          timezone: (document.querySelector("#timezone") as HTMLInputElement)
            .value,
          assumed_fast_percent: Number(
            (document.querySelector("#fast-share") as HTMLInputElement).value,
          ),
        };
        closeDialog();
        action("settings", args);
      });
    },
  );
}
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDialog();
});
root.innerHTML =
  '<div class="loading"><span class="spinner"></span>Opening your insights…</div>';
load();
if (!window.__INSIGHTS_REPORT__)
  setInterval(async () => {
    try {
      const job = await call<Job>("status");
      showJob(job);
      if (
        data &&
        (job.revision !== data.revision || (lastJobRunning && !job.running))
      ) {
        await load();
        if (job.error) toast(job.error, true);
      }
      lastJobRunning = job.running;
    } catch {
      /* A closing desktop window shuts down the server. */
    }
  }, 2000);
