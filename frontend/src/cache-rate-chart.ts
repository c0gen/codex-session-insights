import { Chart } from "./charts";
import { calendarLabel } from "./calendar-dates";
import { cachePercent, cacheReasons } from "./cache-rate-data";
import type { CachePeriod } from "./cache-rate-data";
import { count } from "./ui";

export const cachePeriodLabel = (period: CachePeriod) => period.start === period.end
  ? calendarLabel(period.start) : `${calendarLabel(period.start)} – ${calendarLabel(period.end)}`;

export function cacheRateChart(canvas: HTMLCanvasElement, periods: CachePeriod[]) {
  const values = periods.map(period => period.percent);
  return new Chart(canvas, {
    type: "line",
    data: {
      labels: periods.map(period => period.start),
      datasets: [{
        data: values, borderColor: "#62e5bf", borderWidth: 2, fill: false, tension: 0, spanGaps: false,
        pointRadius: context => {
          const i = context.dataIndex;
          return values[i] != null && values[i - 1] == null && values[i + 1] == null ? 3 : 0;
        },
        pointHoverRadius: 4, pointHitRadius: 12,
      }, {
        // Invisible anchors let null periods explain their availability on hover.
        data: values.map(value => value == null ? 0 : null), showLine: false,
        borderWidth: 0, pointRadius: 0, pointHoverRadius: 0, pointHitRadius: 12,
        backgroundColor: "transparent", borderColor: "transparent",
      }],
    },
    options: {
      responsive: true, maintainAspectRatio: false, animation: false,
      interaction: { intersect: false, mode: "index" },
      plugins: {
        legend: { display: false },
        tooltip: {
          displayColors: false,
          callbacks: {
            title: items => items.length ? cachePeriodLabel(periods[items[0].dataIndex]) : "",
            label: item => {
              const period = periods[item.dataIndex];
              return [period.percent == null ? `Unavailable · ${cacheReasons[period.status]}` : `${cachePercent(period.percent)} cache reuse`,
                `${count(period.cached_tokens)} cached reads / ${count(period.input_tokens)} input tokens`,
                `Input recorded: ${count(period.input_available)}/${count(period.observations)} responses`,
                `Cached reads recorded: ${count(period.cached_available)}/${count(period.observations)} responses`];
            },
          },
        },
      },
      scales: {
        x: { grid: { display: false }, ticks: { color: "#a8b6c7", maxTicksLimit: 8, maxRotation: 0,
          callback: (_, i) => calendarLabel(periods[i].start, { year: undefined }) } },
        y: { min: 0, max: 100, grid: { color: "rgba(152,172,186,.13)" },
          ticks: { color: "#a8b6c7", stepSize: 25, callback: value => `${value}%` } },
      },
    },
  });
}
