import type { Dashboard, Job } from "./types";
import type { FilterState } from "./filter-state";
import "./filter-bar.css";

/** One owner for query feedback, snapshot freshness, export readiness and busy state. */
export class DashboardFeedback {
  private job?: Job;
  constructor(private state: FilterState, private retry: () => void) {}

  render() {
    return `<div id="filter-feedback" class="filter-feedback" role="status" aria-live="polite" aria-atomic="true" hidden><span></span><button id="filters-retry" class="button small">Retry</button></div>`;
  }

  observe(job: Job, data: Dashboard) { this.job = job; this.update(data); }

  update(data: Dashboard) {
    const { loading, error, hasApplied } = this.state;
    const feedback = document.getElementById("filter-feedback");
    if (feedback) {
      feedback.hidden = !error;
      feedback.classList.toggle("error", !!error);
      const message = error
        ? `Couldn’t update metrics. ${hasApplied || data.cached_at ? "Showing previous results. " : ""}${error}` : "";
      const text = feedback.querySelector("span")!;
      if (text.textContent !== message) text.textContent = message;
      const retry = feedback.querySelector<HTMLButtonElement>("button")!;
      retry.disabled = loading;
      retry.onclick = this.retry;
    }
    document.getElementById("dashboard-results")?.setAttribute("aria-busy", String(loading || !error && !!data.analytics_refreshing));
    const label = document.getElementById("update-label");
    const timestamp = new Date(data.cached_at || data.generated_at).toLocaleString();
    if (label) label.textContent = error ? (loading ? "Retrying metrics…" : "Update failed")
      : data.cached_at ? `Cached overview · ${timestamp}${loading || data.analytics_refreshing ? " · Updating…" : ""}`
      : loading || data.analytics_refreshing ? "Updating metrics…"
      : this.job?.running && this.job.origin !== "automatic" ? this.job.message
      : `${data.readonly ? "Saved snapshot" : "Results"} · ${timestamp}`;
    const exportButton = document.querySelector<HTMLButtonElement>("#export-html");
    if (exportButton) {
      exportButton.disabled = !hasApplied;
      exportButton.title = hasApplied ? "Export the last successfully loaded filters" : "Wait for the dashboard to load before exporting";
    }
  }
}
