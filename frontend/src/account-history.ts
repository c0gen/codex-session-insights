import { Chart } from "chart.js";
import "./charts";
import type { AccountHistory } from "./account-types";
import { compact } from "./format";

export type HistoryRange = "30" | "90" | "all";

export function historyChart(canvas: HTMLCanvasElement, history: AccountHistory, range: HistoryRange, timezone: string): Chart | null {
  if (!history.daily?.length) return null;
  const dayMs = 86400000;
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: timezone, year: "numeric", month: "2-digit", day: "2-digit" }).format(new Date());
  // The service's day can already be tomorrow in the user's display timezone.
  const end = Math.max(Date.parse(today + "T00:00:00Z"), Date.parse(history.daily.at(-1)!.day + "T00:00:00Z"));
  const start = range === "all" ? Date.parse(history.daily[0].day + "T00:00:00Z") : end - (Number(range) - 1) * dayMs;
  const points: { x: number; y: number | null }[] = [];
  let previous: number | null = null;
  for (const bucket of history.daily) {
    const x = Date.parse(bucket.day + "T00:00:00Z");
    if (x < start || x > end) continue;
    // Gaps stay gaps; do not turn absent service data into zero usage.
    if (previous !== null && x - previous > dayMs) points.push({ x: previous + dayMs, y: null });
    points.push({ x, y: bucket.tokens });
    previous = x;
  }
  const dayLabel = (value: number) => new Date(value).toISOString().slice(0, 10);
  return new Chart(canvas, {
    type: "line",
    data: { datasets: [{ data: points, borderColor: "#62e5bf", backgroundColor: "rgba(98,229,191,.10)",
      borderWidth: 2, pointRadius: points.length === 1 ? 3 : 0, pointHitRadius: 10, fill: true, spanGaps: false }] },
    options: { responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: {
        title: items => items.length && items[0].parsed.x !== null ? dayLabel(items[0].parsed.x) : "",
        label: item => `${compact(item.parsed.y || 0)} tokens`,
      } } },
      scales: {
        x: { type: "linear", min: start, max: Math.max(start + dayMs, end), grid: { color: "rgba(152,172,186,.10)" },
          ticks: { color: "#a8b6c7", maxTicksLimit: 5, callback: value => dayLabel(Number(value)).slice(5) } },
        y: { beginAtZero: true, grid: { color: "rgba(152,172,186,.10)" },
          ticks: { color: "#a8b6c7", maxTicksLimit: 4, callback: value => compact(Number(value)) } },
      },
    },
  });
}
