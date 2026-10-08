import {
  Chart,
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Filler,
  Tooltip,
  BarController,
  BarElement,
} from "chart.js";
import type { Dashboard, Day } from "./types";
Chart.register(
  LineController,
  LineElement,
  PointElement,
  LinearScale,
  CategoryScale,
  Filler,
  Tooltip,
  BarController,
  BarElement,
);
let charts: Chart[] = [];
export const clearCharts = () => {
  charts.forEach((c) => c.destroy());
  charts = [];
};
export function compact(n: number, digits = 2) {
  return Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: digits,
  }).format(n || 0);
}
export function currency(n: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(n || 0);
}
const grid = "rgba(152,172,186,.13)",
  muted = "#a8b6c7";
export function activity(
  data: Day[],
  mode: "tokens" | "cost" | "prompts" | "lines",
) {
  const canvas = document.querySelector<HTMLCanvasElement>("#activity-chart");
  if (!canvas) return;
  const ctx = canvas.getContext("2d")!;
  const gradient = ctx.createLinearGradient(0, 0, 0, 300);
  gradient.addColorStop(0, "rgba(87,224,184,.24)");
  gradient.addColorStop(1, "rgba(87,224,184,.01)");
  charts.push(
    new Chart(canvas, {
      type: "line",
      data: {
        labels: data.map((d) => d.day),
        datasets: [
          {
            data: data.map((d) => d[mode] || 0),
            borderColor: "#62e5bf",
            backgroundColor: gradient,
            fill: true,
            borderWidth: 1.7,
            pointRadius: 0,
            pointHitRadius: 12,
            tension: 0.12,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { intersect: false, mode: "index" },
        plugins: {
          legend: { display: false },
          tooltip: {
            displayColors: false,
            callbacks: {
              label: (c) =>
                mode === "cost"
                  ? currency(Number(c.raw))
                  : compact(Number(c.raw)) + " " + mode,
            },
          },
        },
        scales: {
          x: {
            grid: { color: grid },
            ticks: {
              color: muted,
              maxTicksLimit: 7,
              callback: (_, i) =>
                new Date(data[i]?.day + "T12:00:00").toLocaleDateString(
                  "en-US",
                  { month: "short", day: "numeric" },
                ),
            },
          },
          y: {
            beginAtZero: true,
            grid: { color: grid },
            ticks: {
              color: muted,
              maxTicksLimit: 5,
              callback: (v) =>
                mode === "cost" ? "$" + compact(Number(v)) : compact(Number(v)),
            },
          },
        },
      },
    }),
  );
}
export function modelChart(data: Dashboard, mode: "tokens" | "cost") {
  const canvas = document.querySelector<HTMLCanvasElement>("#model-chart");
  if (!canvas) return;
  charts.push(
    new Chart(canvas, {
      type: "bar",
      data: {
        labels: data.models.map((m) => m.name),
        datasets: [
          {
            data: data.models.map((m) => m[mode] || 0),
            backgroundColor: "#55caaa",
            borderRadius: 4,
            barThickness: 22,
          },
        ],
      },
      options: {
        indexAxis: "y",
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (c) =>
                mode === "cost"
                  ? currency(Number(c.raw))
                  : compact(Number(c.raw)) + " tokens",
            },
          },
        },
        scales: {
          x: {
            grid: { color: grid },
            ticks: {
              color: muted,
              callback: (v) =>
                mode === "cost" ? "$" + compact(Number(v)) : compact(Number(v)),
            },
          },
          y: { grid: { display: false }, ticks: { color: "#d3deeb" } },
        },
      },
    }),
  );
}
