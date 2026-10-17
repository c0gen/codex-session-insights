import { Chart, compact } from "./charts";
import { calendarLabel } from "./calendar-dates";
import { count } from "./ui";
import type { TokenActivityData, TokenActivityMode } from "./token-activity-data";

export function tokenActivityChart(canvas: HTMLCanvasElement, data: TokenActivityData, mode: Exclude<TokenActivityMode, "daily">) {
  const weekly = mode === "weekly";
  const labels = weekly ? data.weeks.map(week => week.start) : data.days.map(day => day.day);
  const values = weekly ? data.weeks.map(week => week.tokens) : data.days.map(day => day.cumulative);
  return new Chart(canvas, {
    type: weekly ? "bar" : "line",
    data: {
      labels,
      datasets: [{
        data: values, borderColor: "#82b8ff", backgroundColor: weekly ? "#4986ee" : "rgba(73,134,238,.15)",
        borderWidth: weekly ? 0 : 2, borderRadius: 3, maxBarThickness: 36,
        fill: !weekly, tension: 0, pointRadius: values.length === 1 ? 4 : 0, pointHitRadius: 12,
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
            title: items => {
              const index = items[0]?.dataIndex;
              if (index === undefined) return "";
              if (!weekly) return calendarLabel(labels[index]);
              const week = data.weeks[index];
              return week.start === week.end ? calendarLabel(week.start)
                : `${calendarLabel(week.start)} – ${calendarLabel(week.end)}`;
            },
            label: item => `${count(Number(item.raw))} ${weekly ? "tokens" : "cumulative tokens"}`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: {
            color: "#a8b6c7", maxTicksLimit: 8, maxRotation: 0,
            callback: (_, index) => calendarLabel(labels[index], { year: undefined }),
          },
        },
        y: {
          beginAtZero: true,
          grid: { color: "rgba(152,172,186,.13)" },
          ticks: { color: "#a8b6c7", maxTicksLimit: 5, callback: value => compact(Number(value)) },
        },
      },
    },
  });
}
