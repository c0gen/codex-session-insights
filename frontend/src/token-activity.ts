import "./token-activity.css";
import { calendarLabel } from "./calendar-dates";
import { compact } from "./format";
import { count, esc } from "./ui";
import type { Dashboard } from "./types";
import { buildTokenActivity, type TokenActivityData, type TokenActivityMode, type TokenYear } from "./token-activity-data";
import { tokenActivityChart } from "./token-activity-chart";
import { metricState } from "./metric-availability";

const modes: [TokenActivityMode, string][] = [["daily", "Daily"], ["weekly", "Weekly"], ["cumulative", "Cumulative"]];
const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function calendar(year: TokenYear) {
  const first = year.cells.find(day => day !== null)?.day;
  // Tiny partial months are covered by the range caption; avoid colliding labels.
  const labels: string[] = [];
  let nextColumn = year.columns + 2;
  for (const month of [...year.months].reverse()) {
    const column = Math.min(month.column, Math.max(1, year.columns - 1));
    if (nextColumn - column < 2) continue;
    labels.unshift(`<span style="grid-column:${column}/span ${Math.min(2, year.columns)}">${months[month.month - 1]}</span>`);
    nextColumn = column;
  }
  return `<div class="token-year"><h3>${year.year}</h3><div id="token-calendar-scroll-${year.year}" class="token-calendar-scroll" data-preserve-scroll data-weeks="${year.columns}">
    <div class="token-calendar" style="--weeks:${year.columns}">
      <div class="token-weekdays" aria-hidden="true">${weekdays.map((day, index) => `<span>${index % 2 === 0 ? day : ""}</span>`).join("")}</div>
      <div><div class="token-calendar-cells" role="group" aria-label="${year.year} daily token activity. Use arrow keys to explore days.">${year.cells.map(day => day
        ? `<button type="button" id="token-day-${day.day}" class="token-day" data-day="${day.day}" data-level="${day.level}" data-tokens="${day.tokens}" tabindex="${day.day === first ? 0 : -1}" aria-label="${esc(calendarLabel(day.day, { weekday: "long" }))}: ${count(day.tokens)} tokens"></button>`
        : '<span class="token-padding" aria-hidden="true"></span>').join("")}</div>
      <div class="token-calendar-months" aria-hidden="true">${labels.join("")}</div></div>
    </div></div></div>`;
}

/** Owns its charts/listeners so dashboard redraws never leave detached work behind. */
export class TokenActivityPanel {
  private mode: TokenActivityMode = "daily";
  private data: TokenActivityData | null = null;
  private chart: ReturnType<typeof tokenActivityChart> | null = null;
  private resize: ResizeObserver | null = null;
  private listeners: AbortController | null = null;

  render(dashboard: Dashboard): string {
    const data = this.data = buildTokenActivity(dashboard);
    const state = metricState(dashboard, "total"), unavailable = state === "unavailable";
    const range = !data.start ? `Through ${calendarLabel(data.end)}` : data.start === data.end
      ? calendarLabel(data.end) : `${calendarLabel(data.start)} – ${calendarLabel(data.end)}`;
    const legend = `<span class="token-legend" role="img" aria-label="Daily token intensity: gray is zero, four blue levels increase to ${count(data.max)} tokens">Less ${[0, 1, 2, 3, 4].map(level => `<i data-level="${level}"></i>`).join("")} More</span>`;
    const content = unavailable || !data.days.length ? "" : this.mode === "daily"
      ? `<div class="token-calendars">${data.years.map(calendar).join("")}</div>`
      : `<div class="token-chart"><canvas id="token-activity-chart" role="img" aria-label="${this.mode === "weekly" ? "Weekly token totals" : "Cumulative token usage"} · ${esc(range)} · ${count(data.total)} tokens"></canvas></div>`;
    return `<section id="token-activity" class="panel token-activity" aria-labelledby="token-activity-heading" data-mode="${this.mode}" data-total-tokens="${unavailable ? "" : data.total}">
      <div class="panel-heading"><div><h2 id="token-activity-heading">Token activity</h2><p>${esc(range)} · ${esc(dashboard.timezone)}</p></div>
      <div class="token-mode-controls" role="group" aria-label="Token activity view">${modes.map(([mode, label]) => `<button type="button" id="token-mode-${mode}" data-token-mode="${mode}" aria-pressed="${this.mode === mode}">${label}</button>`).join("")}</div></div>
      ${content}${unavailable ? '<p class="token-empty" role="status">Token counters unavailable in this range.</p>' : !data.total ? `<p class="token-empty" role="status">${state === "partial" ? "No tokens in recorded counters; coverage is partial." : "No token activity in this range."}</p>` : ""}
      <div class="token-activity-footer">${unavailable ? "" : `<span title="${count(data.total)} analyzed tokens"><strong>${compact(data.total)}</strong> analyzed tokens${state === "partial" ? " · partial coverage · recorded subtotal only" : ""}</span>${this.mode === "daily" ? legend : `<span>${this.mode === "weekly" ? "Monday–Sunday · selected days only" : "Running total within the selected range"}</span>`}`}</div>
      <div id="token-activity-tooltip" class="token-tooltip" role="tooltip" aria-hidden="true" hidden></div>
    </section>`;
  }

  unmount() {
    this.chart?.destroy();
    this.chart = null;
    this.resize?.disconnect();
    this.resize = null;
    this.listeners?.abort();
    this.listeners = null;
  }

  mount(redraw: () => void) {
    const panel = document.querySelector<HTMLElement>("#token-activity");
    if (!panel || !this.data) return;
    const signal = (this.listeners = new AbortController()).signal;
    panel.querySelectorAll<HTMLButtonElement>("[data-token-mode]").forEach(button => {
      button.addEventListener("click", () => {
        this.mode = button.dataset.tokenMode as TokenActivityMode;
        redraw();
      }, { signal });
    });
    const canvas = panel.querySelector<HTMLCanvasElement>("#token-activity-chart");
    if (canvas && this.mode !== "daily") this.chart = tokenActivityChart(canvas, this.data, this.mode);
    if (this.mode !== "daily") return;

    const sizeCalendars = () => panel.querySelectorAll<HTMLElement>(".token-calendar-scroll").forEach(scroll => {
      const weeks = Number(scroll.dataset.weeks);
      // Short ranges grow toward the panel width instead of leaving half of it empty.
      const size = Math.max(14, Math.min(30, Math.floor((scroll.clientWidth - 46 - (weeks - 1) * 4) / weeks)));
      scroll.style.setProperty("--token-cell", `${size}px`);
    });
    sizeCalendars();
    this.resize = new ResizeObserver(sizeCalendars);
    this.resize.observe(panel);

    const tooltip = panel.querySelector<HTMLElement>(".token-tooltip")!;
    let anchor: HTMLButtonElement | null = null;
    const hide = () => { tooltip.hidden = true; anchor = null; };
    const position = () => {
      if (!anchor) return;
      const rect = anchor.getBoundingClientRect();
      const viewport = anchor.closest(".token-calendar-scroll")!.getBoundingClientRect();
      if (rect.right < viewport.left || rect.left > viewport.right || rect.bottom < 0 || rect.top > innerHeight) {
        hide(); return;
      }
      const left = Math.max(8, Math.min(innerWidth - tooltip.offsetWidth - 8, rect.left + rect.width / 2 - tooltip.offsetWidth / 2));
      const top = rect.top - tooltip.offsetHeight - 10;
      tooltip.style.left = `${left}px`;
      tooltip.style.top = `${top >= 8 ? top : rect.bottom + 10}px`;
    };
    const show = (cell: HTMLButtonElement) => {
      anchor = cell;
      tooltip.innerHTML = `<span>${esc(calendarLabel(cell.dataset.day!, { weekday: "short" }))}</span><strong>${count(Number(cell.dataset.tokens))} tokens</strong>`;
      tooltip.hidden = false;
      position();
    };
    const cellFrom = (target: EventTarget | null) => target instanceof Element ? target.closest<HTMLButtonElement>(".token-day") : null;
    panel.addEventListener("pointerover", event => { const cell = cellFrom(event.target); if (cell) show(cell); }, { signal });
    panel.addEventListener("pointerout", event => {
      const cell = cellFrom(event.target);
      if (cell && anchor === cell && document.activeElement !== cell) hide();
    }, { signal });
    panel.addEventListener("focusin", event => {
      const cell = cellFrom(event.target);
      if (!cell) return;
      cell.closest(".token-year")!.querySelectorAll<HTMLButtonElement>(".token-day").forEach(day => { day.tabIndex = day === cell ? 0 : -1; });
      show(cell);
    }, { signal });
    panel.addEventListener("focusout", event => { if (cellFrom(event.target)) hide(); }, { signal });
    panel.addEventListener("click", event => { const cell = cellFrom(event.target); if (cell) { cell.focus({ preventScroll: true }); show(cell); } }, { signal });
    panel.addEventListener("keydown", event => {
      if (event.key === "Escape") { hide(); return; }
      const cell = cellFrom(event.target);
      if (!cell) return;
      const cells = Array.from(cell.closest(".token-year")!.querySelectorAll<HTMLButtonElement>(".token-day"));
      const index = cells.indexOf(cell);
      const move: Record<string, number> = { ArrowUp: index - 1, ArrowDown: index + 1, ArrowLeft: index - 7, ArrowRight: index + 7, Home: 0, End: cells.length - 1 };
      if (!(event.key in move)) return;
      event.preventDefault();
      cells[Math.max(0, Math.min(cells.length - 1, move[event.key]))].focus({ preventScroll: true });
      const focused = document.activeElement as HTMLButtonElement;
      focused.scrollIntoView({ block: "nearest", inline: "nearest" });
      show(focused);
    }, { signal });
    document.addEventListener("pointerdown", event => { if (!cellFrom(event.target)) hide(); }, { signal });
    document.addEventListener("scroll", position, { capture: true, signal });
    window.addEventListener("resize", position, { signal });
  }
}
