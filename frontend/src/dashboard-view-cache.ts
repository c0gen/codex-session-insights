import type { Dashboard, Filters } from "./types";
import { captureView } from "./live-updates";

/** Page content and interaction state live independently of in-flight requests. */
export class DashboardViewCache {
  private values = new Map<string, Dashboard>();
  private positions = new Map<string, ReturnType<typeof captureView>>();
  private key(view: string, filters: Filters | undefined) { return JSON.stringify([view, filters]); }
  save(view: string, data: Dashboard) {
    this.values.set(this.key(view, data.filters), data);
    while (this.values.size > 12) this.values.delete(this.values.keys().next().value!);
  }
  read(view: string, current: Dashboard) {
    const value = this.values.get(this.key(view, current.filters));
    if (!value || value.analytics_context !== current.analytics_context || value.timezone !== current.timezone ||
      value.settings.assumed_fast_percent !== current.settings.assumed_fast_percent ||
      new Date(value.generated_at).toDateString() !== new Date(current.generated_at).toDateString()) return null;
    return { ...value, sources: current.sources, job: current.job,
      usage_limits: current.usage_limits, provider_allowances: current.provider_allowances,
      analytics_refreshing: value.revision !== current.revision };
  }
  capture(page: string, root: HTMLElement) { this.positions.set(page, captureView(root)); }
  position(page: string) { return this.positions.get(page); }
}

export const dashboardSkeleton = () => `<section class="panel dashboard-skeleton" role="status" aria-label="Loading this view"><span class="spinner"></span> Loading usage...</section>`;
