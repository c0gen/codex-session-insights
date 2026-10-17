import { Chart } from "./charts";
import { calendarLabel } from "./calendar-dates";
import { count } from "./ui";
import type { DailySessions } from "./types";

export const sessionSeries = [
  { key: "chats", label: "Main chats", color: "#62e5bf" },
  { key: "subagents", label: "Spawned sub-agents", color: "#82b8ee" },
  { key: "system_agents", label: "System agents", color: "#c2a3ed" },
] as const;

export function dailySessionsChart(canvas: HTMLCanvasElement, days: DailySessions[], timezone: string) {
  return new Chart(canvas, {
    type: "bar",
    data: {
      labels: days.map(row => row.day),
      datasets: sessionSeries.map(series => ({ label: series.label, data: days.map(row => row[series.key]), backgroundColor: series.color, maxBarThickness: 28 })),
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: {
          title: items => items.length ? `${calendarLabel(days[items[0].dataIndex].day)} · ${timezone}` : "",
          label: item => `${item.dataset.label}: ${count(Number(item.raw))}`,
        } },
      },
      scales: {
        x: { stacked: true, grid: { display: false }, ticks: { color: "#a8b6c7", maxTicksLimit: 7, maxRotation: 0,
          callback: (_, index) => calendarLabel(days[index].day, { year: undefined }) } },
        y: { stacked: true, beginAtZero: true, suggestedMax: 1, title: { display: true, text: "Unique active sessions", color: "#a8b6c7" },
          grid: { color: "rgba(152,172,186,.13)" }, ticks: { color: "#a8b6c7", precision: 0, maxTicksLimit: 6 } },
      },
    },
  });
}
