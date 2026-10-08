import type { Dashboard } from "./types";
export async function call<T = unknown>(
  action: string,
  args: unknown = {},
): Promise<T> {
  if (window.__INSIGHTS_REPORT__) {
    if (action === "dashboard") return window.__INSIGHTS_REPORT__ as T;
    throw new Error(
      "This is a saved report. Open the desktop app to update sources.",
    );
  }
  if (window.pywebview?.api)
    return (await window.pywebview.api.call(action, args)) as T;
  const token = document.querySelector<HTMLMetaElement>(
    'meta[name="insights-token"]',
  )?.content;
  const response = await fetch(`/api/${action}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Insights-Token": token || "",
    },
    body: JSON.stringify(args),
  });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "Request failed");
  return value as T;
}
export const getDashboard = (filters: unknown) =>
  call<Dashboard>("dashboard", filters);
