import { calendarLabel, dayNumber, dayString } from "./calendar-dates";
import { dailySessionsChart, sessionSeries } from "./daily-sessions-chart";
import { sessionDays, sessionPageSize, sessionRange } from "./daily-sessions-data";
import { count, esc, tip } from "./ui";
import type { Dashboard } from "./types";
import "./usage-metrics.css";

export class DailySessionsPanel {
  private chart?: ReturnType<typeof dailySessionsChart>;
  private events?: AbortController;
  private offset = 0;
  private rangeKey = "";
  private tableOpen = false;
  private data?: Dashboard;

  render(data: Dashboard): string {
    this.data = data;
    const range = sessionRange(data);
    const key = JSON.stringify([data.date_bounds, data.filters, data.timezone]);
    if (key !== this.rangeKey) {
      this.rangeKey = key;
      this.offset = Math.max(0, (Math.ceil(range.length / sessionPageSize) - 1) * sessionPageSize);
    }
    const days = sessionDays(data, this.offset);
    const first = days[0]?.day, last = days.at(-1)?.day;
    const period = first && last ? `${calendarLabel(first)} – ${calendarLabel(last)} · ` : "";
    const empty = data.daily_sessions === undefined ? "Daily session counts are unavailable in this snapshot."
      : !days.length ? "No observed date range for daily sessions." : "";
    return `<section class="panel daily-sessions" id="daily-sessions"><div class="panel-heading"><div><h2>Chats and agents per day ${tip("Each session counts once on every day it is active. These are not new-chat counts; daily counts do not sum to the all-range distinct total.")}</h2><p>Unique active sessions per day · ${esc(data.timezone)}</p></div></div>${empty ? `<p class="daily-sessions-empty">${empty}</p>` : `
      <div class="daily-session-toolbar"><div class="daily-session-legend">${sessionSeries.map(series => `<span><i style="background:${series.color}"></i>${series.label}</span>`).join("")}</div>
      <div class="daily-session-range"><p id="daily-sessions-period" role="status">${esc(period)}${count(days.length)} of ${count(range.length)} days</p>
      ${range.length > sessionPageSize ? `<div class="daily-session-controls" aria-label="Daily session dates"><button id="session-previous" class="button small" ${this.offset === 0 ? "disabled" : ""}>Previous days</button><label>Go to date <input type="date" id="session-date" min="${dayString(range.start)}" max="${dayString(range.end)}" value="${first}"></label><button id="session-next" class="button small" ${this.offset + days.length >= range.length ? "disabled" : ""}>Next days</button></div>` : ""}</div></div>
      <div class="daily-session-chart"><canvas id="daily-sessions-chart" role="img" aria-label="Daily active main chats, spawned sub-agents and system agents. Exact counts are in the table below." aria-describedby="daily-sessions-period"></canvas></div>
      ${days.every(day => day.chats + day.subagents + day.system_agents === 0) ? '<p class="daily-sessions-empty">No active sessions in these dates.</p>' : ""}
      <details id="daily-sessions-values" ${this.tableOpen ? "open" : ""}><summary>Exact daily counts</summary><div class="daily-session-table" tabindex="0" role="region" aria-label="Scrollable daily session counts"><table><caption>${esc(period)}${esc(data.timezone)} · selected filters</caption><thead><tr><th scope="col">Date</th>${sessionSeries.map(series => `<th scope="col">${series.label}</th>`).join("")}</tr></thead><tbody>${days.map(day => `<tr><th scope="row">${day.day}</th>${sessionSeries.map(series => `<td>${count(day[series.key])}</td>`).join("")}</tr>`).join("")}</tbody></table></div></details>`}</section>`;
  }

  mount() {
    const panel = document.querySelector<HTMLElement>("#daily-sessions");
    if (!panel || !this.data) return;
    this.events = new AbortController();
    const options = { signal: this.events.signal };
    const canvas = panel.querySelector<HTMLCanvasElement>("canvas");
    if (canvas) this.chart = dailySessionsChart(canvas, sessionDays(this.data, this.offset), this.data.timezone);
    const update = (offset: number, focus: string) => {
      this.offset = offset;
      this.unmount();
      panel.outerHTML = this.render(this.data!);
      this.mount();
      const target = document.getElementById(focus) as HTMLButtonElement | HTMLInputElement | null;
      // At a range boundary keep keyboard focus in the paging controls.
      (target?.disabled ? document.getElementById("session-date") : target)?.focus();
    };
    panel.querySelector("#session-previous")?.addEventListener("click", () => update(Math.max(0, this.offset - sessionPageSize), "session-previous"), options);
    panel.querySelector("#session-next")?.addEventListener("click", () => update(this.offset + sessionPageSize, "session-next"), options);
    panel.querySelector<HTMLInputElement>("#session-date")?.addEventListener("change", event => {
      const input = event.target as HTMLInputElement;
      if (!input.value || !input.checkValidity()) return;
      const delta = dayNumber(input.value) - sessionRange(this.data!).start;
      update(Math.floor(delta / sessionPageSize) * sessionPageSize, "session-date");
    }, options);
    panel.querySelector<HTMLDetailsElement>("details")?.addEventListener("toggle", event => {
      this.tableOpen = (event.target as HTMLDetailsElement).open;
    }, options);
  }

  unmount() {
    this.chart?.destroy();
    this.chart = undefined;
    this.events?.abort();
    this.events = undefined;
  }
}
