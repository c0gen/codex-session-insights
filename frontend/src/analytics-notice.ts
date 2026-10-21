import type { Dashboard } from "./types";

type Notice = { text: string; active: boolean; until: number; timer?: ReturnType<typeof setTimeout> };
const notices = new Map<string, Notice>();

function update(id: string, text: string | undefined, completed: string) {
  let notice = notices.get(id);
  if (notice?.timer) clearTimeout(notice.timer);
  if (text) notice = { text, active: true, until: Infinity };
  else if (notice?.active) notice = { text: completed, active: false, until: performance.now() + 5000 };
  if (notice && performance.now() >= notice.until) notice = undefined;
  const element = document.getElementById(id);
  if (!notice) {
    notices.delete(id);
    if (element) element.hidden = true;
    return;
  }
  notices.set(id, notice);
  if (element) { element.textContent = notice.text; element.hidden = false; }
  if (!notice.active) notice.timer = setTimeout(() => update(id, undefined, completed), notice.until - performance.now());
}

export function showAnalyticsNotices(data: Dashboard) {
  update("analytics-refresh-notice", data.analytics_refreshing
    ? `Updating metrics. Showing previous results from ${new Date(data.generated_at).toLocaleString()}.` : undefined,
    `Metrics updated. Results from ${new Date(data.generated_at).toLocaleString()}.`);
  update("cached-overview-notice", data.cached_at
    ? `Cached overview from ${new Date(data.cached_at).toLocaleString()}. Updating saved usage...` : undefined,
    "Saved usage refreshed.");
}
