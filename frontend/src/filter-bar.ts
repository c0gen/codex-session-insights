import type { Dashboard } from "./types";
import { defaultFilters, FilterState } from "./filter-state";
import { dateLabel, esc } from "./ui";
import "./filter-bar.css";

const fields = { range: "range", project: "project_id", model: "model", source: "source_id", provider: "provider" } as const;
const ranges: [string, string][] = [["all", "All time"], ["today", "Today"], ["7", "Last 7 days"],
  ["30", "Last 30 days"], ["90", "Last 90 days"], ["custom", "Custom dates"]];

/** Owns filter controls and request feedback independently of dashboard charts. */
export class FilterBar {
  constructor(private state: FilterState, private apply: () => void, private finishEditing: () => void) {}

  render(data: Dashboard) {
    const filters = this.state.draft;
    const select = (name: string, values: [string, string][], value: string) =>
      `<select id="filter-${name}" aria-label="${name}" ${data.readonly ? "disabled" : ""}>${values.map(([v, label]) =>
        `<option value="${esc(v)}" ${v === value ? "selected" : ""}>${esc(label)}</option>`).join("")}</select>`;
    const first = data.timeline[0]?.day, last = data.timeline[data.timeline.length - 1]?.day;
    const dates = first && last
      ? `Active ${dateLabel(first)}${first.slice(0, 4) !== last.slice(0, 4) ? `, ${first.slice(0, 4)}` : ""} – ${dateLabel(last)}, ${last.slice(0, 4)}`
      : "No activity in this range";
    const changed = !data.readonly && (filters.provider || filters.range !== "all" || filters.project_id || filters.model || filters.source_id);
    return `<div id="filter-bar"><div class="filters ${data.readonly ? "readonly" : ""}">
      ${select("provider", [["", "All tools"], ["codex", "Codex"], ["claude_code", "Claude Code"], ["antigravity", "Antigravity"]], filters.provider || "")}
      ${select("range", ranges, filters.range)}
      ${select("project", [["", "All projects"], ...data.options.projects.map(p => [p.id, p.name] as [string, string])], filters.project_id)}
      ${select("model", [["", "All models"], ...data.options.models.map(m => [m, m] as [string, string])], filters.model)}
      ${select("source", [["", "All sources"], ...data.sources.map(s => [s.id, s.label] as [string, string])], filters.source_id)}
      ${changed ? '<button id="filters-reset" class="text-button">Reset filters</button>' : ""}
      <span class="date-caption">${esc(dates)}</span>
      ${filters.range === "custom" ? `<div class="date-fields"><label>From <input id="date-start" type="date" value="${esc(filters.start)}"></label><label>To <input id="date-end" type="date" value="${esc(filters.end)}"></label><button id="date-apply" class="button small">Apply</button></div>` : ""}
      </div><div id="filter-feedback" class="filter-feedback" role="status" aria-live="polite" aria-atomic="true" hidden>
      <span></span><button id="filters-retry" class="button small" hidden>Retry</button></div></div>`;
  }

  mount(data: Dashboard) {
    const root = document.querySelector<HTMLElement>("#filter-bar");
    if (!root) return;
    if (!data.readonly) {
      root.querySelector<HTMLButtonElement>("#filters-reset")?.addEventListener("click", () => {
        Object.assign(this.state.draft, defaultFilters());
        this.apply();
      });
      for (const [name, key] of Object.entries(fields)) {
        const control = root.querySelector<HTMLSelectElement>(`#filter-${name}`)!;
        control.onchange = () => {
          this.state.draft[key] = control.value;
          if (key === "range" && control.value === "custom") {
            const filters = this.state.draft;
            filters.start ||= data.timeline[0]?.day || new Date().toISOString().slice(0, 10);
            filters.end ||= data.timeline[data.timeline.length - 1]?.day || filters.start;
            this.refresh(data);
            this.finishEditing();
          } else this.apply();
        };
      }
      root.querySelectorAll<HTMLInputElement>(".date-fields input").forEach(input => {
        input.oninput = () => { this.state.draft[input.id === "date-start" ? "start" : "end"] = input.value; };
      });
      const apply = root.querySelector<HTMLButtonElement>("#date-apply");
      if (apply) apply.onclick = () => this.apply();
      root.querySelector<HTMLButtonElement>("#filters-retry")!.onclick = () => this.apply();
    }
    this.feedback();
  }

  refresh(data: Dashboard) {
    const root = document.querySelector<HTMLElement>("#filter-bar");
    if (!root) return;
    const focus = root.contains(document.activeElement) ? document.activeElement?.id : "";
    root.outerHTML = this.render(data);
    this.mount(data);
    if (focus) document.getElementById(focus)?.focus({ preventScroll: true });
  }

  feedback() {
    const root = document.querySelector<HTMLElement>("#filter-bar");
    if (!root) return;
    const { loading, error } = this.state;
    const feedback = root.querySelector<HTMLElement>("#filter-feedback")!;
    // Routine refreshes use the header status without adding a row above metrics.
    feedback.hidden = !error;
    feedback.classList.toggle("error", !!error);
    feedback.querySelector("span")!.textContent = error ? `Couldn’t update metrics. Showing previous results. ${error}` : "";
    root.querySelector<HTMLButtonElement>("#filters-retry")!.hidden = !error;
    document.querySelector("#dashboard-results")?.setAttribute("aria-busy", String(loading));
    const label = document.querySelector("#update-label");
    if (label && (loading || error)) label.textContent = loading ? "Updating metrics…" : "Update failed";
    else if (label && !document.querySelector(".filters.readonly")) label.textContent = "Updated just now";
  }
}
