import { calendarLabel, dayNumber, dayString } from "./calendar-dates";
import { cacheRateChart, cachePeriodLabel } from "./cache-rate-chart";
import { cachePageSize, cachePercent, cachePeriods, cacheRange, cacheReasons } from "./cache-rate-data";
import type { CacheRateMode } from "./cache-rate-data";
import type { Dashboard } from "./types";
import { count, esc, segment, tip } from "./ui";
import "./cache-rate.css";

export class CacheRatePanel {
  private mode: CacheRateMode = "daily";
  private offset = 0;
  private rangeKey = "";
  private tableOpen = false;
  private data?: Dashboard;
  private chart?: ReturnType<typeof cacheRateChart>;
  private events?: AbortController;

  render(data: Dashboard): string {
    this.data = data;
    const range = cacheRange(data, this.mode);
    const key = JSON.stringify([data.date_bounds, data.filters, data.timezone, this.mode]);
    if (key !== this.rangeKey) {
      this.rangeKey = key;
      this.offset = Math.max(0, Math.floor((range.length - 1) / cachePageSize) * cachePageSize);
    }
    const periods = cachePeriods(data, this.mode, this.offset);
    const first = periods[0]?.start, last = periods.at(-1)?.end;
    const period = first && last ? `${calendarLabel(first)} – ${calendarLabel(last)}` : "";
    const empty = !data.cache_rate_timeline ? "Cache rate history is unavailable in this snapshot."
      : !periods.length ? "No observed date range for cache reuse." : "";
    return `<section class="panel cache-rate" id="cache-rate"><div class="panel-heading"><div><h2>Cache reuse rate over time ${tip("Cached reads ÷ all input tokens × 100. Input includes cache reads and writes. Daily and Monday–Sunday weekly rates use aggregate tokens, not averaged percentages. Gaps mean no input, missing counters or an invalid ratio.")}</h2><p>Cached reads ÷ input tokens · ${esc(data.timezone)}</p></div>
      ${segment("cache-mode", [["daily", "Daily"], ["weekly", "Weekly"]], this.mode)}</div>
      ${empty ? `<p class="cache-rate-empty">${empty}</p>` : `<div class="cache-rate-toolbar"><p id="cache-rate-period" role="status">${esc(period)} · ${count(periods.length)} of ${count(range.length)} ${this.mode === "daily" ? "days" : "weeks"}</p>
      ${range.length > cachePageSize ? `<div class="cache-rate-controls" aria-label="Cache rate dates"><button id="cache-previous" class="button small" ${this.offset === 0 ? "disabled" : ""}>Previous ${this.mode === "daily" ? "days" : "weeks"}</button><label>Go to date <input id="cache-date" type="date" min="${dayString(range.start)}" max="${dayString(range.end)}" value="${first}"></label><button id="cache-next" class="button small" ${this.offset + periods.length >= range.length ? "disabled" : ""}>Next ${this.mode === "daily" ? "days" : "weeks"}</button></div>` : ""}</div>
      <div class="cache-rate-chart"><canvas role="img" aria-label="${this.mode === "daily" ? "Daily" : "Weekly"} cache reuse percentage from zero to one hundred. Exact values and gap explanations are in the table below." aria-describedby="cache-rate-period"></canvas></div>
      <p class="fine-print">${this.mode === "weekly" ? "Monday–Sunday · selected days only. " : ""}Gaps indicate no input, missing counters or invalid ratios.</p>
      ${periods.every(row => row.percent == null) ? '<p class="cache-rate-empty">No cache reuse rate available in these dates. See exact values for details.</p>' : ""}
      <details id="cache-rate-values" ${this.tableOpen ? "open" : ""}><summary>Exact values and coverage</summary><div class="cache-rate-table" tabindex="0" role="region" aria-label="Scrollable cache reuse values"><table><caption>${esc(period)} · ${esc(data.timezone)} · selected filters</caption><thead><tr><th scope="col">Period</th><th scope="col">Cache reuse</th><th scope="col">Cached reads</th><th scope="col">Input tokens</th><th scope="col">Counter coverage</th></tr></thead><tbody>${periods.map(row => `<tr><th scope="row">${esc(cachePeriodLabel(row))}</th><td>${row.percent == null ? "Unavailable" : cachePercent(row.percent)}</td><td>${count(row.cached_tokens)}</td><td>${count(row.input_tokens)}</td><td>${cacheReasons[row.status]}${row.observations ? ` · input ${count(row.input_available)}/${count(row.observations)} · cached ${count(row.cached_available)}/${count(row.observations)} responses` : ""}</td></tr>`).join("")}</tbody></table></div></details>`}</section>`;
  }

  mount() {
    const panel = document.querySelector<HTMLElement>("#cache-rate");
    if (!panel || !this.data) return;
    this.events = new AbortController();
    const options = { signal: this.events.signal };
    const canvas = panel.querySelector<HTMLCanvasElement>("canvas");
    if (canvas) this.chart = cacheRateChart(canvas, cachePeriods(this.data, this.mode, this.offset));
    const update = (focus: string) => {
      this.unmount();
      panel.outerHTML = this.render(this.data!);
      this.mount();
      const target = document.querySelector<HTMLButtonElement | HTMLInputElement>(focus);
      (target?.disabled ? document.querySelector<HTMLInputElement>("#cache-date") : target)?.focus();
    };
    panel.querySelectorAll<HTMLButtonElement>("[data-cache-mode]").forEach(button => button.addEventListener("click", () => {
      this.mode = button.dataset.cacheMode as CacheRateMode;
      update(`[data-cache-mode="${this.mode}"]`);
    }, options));
    panel.querySelector("#cache-previous")?.addEventListener("click", () => {
      this.offset = Math.max(0, this.offset - cachePageSize); update("#cache-previous");
    }, options);
    panel.querySelector("#cache-next")?.addEventListener("click", () => {
      this.offset += cachePageSize; update("#cache-next");
    }, options);
    panel.querySelector<HTMLInputElement>("#cache-date")?.addEventListener("change", event => {
      const input = event.target as HTMLInputElement;
      if (!input.value || !input.checkValidity()) return;
      const range = cacheRange(this.data!, this.mode);
      const period = Math.floor((dayNumber(input.value) - range.anchor) / range.step);
      this.offset = Math.floor(period / cachePageSize) * cachePageSize;
      update("#cache-date");
    }, options);
    panel.querySelector("details")?.addEventListener("toggle", event => {
      this.tableOpen = (event.target as HTMLDetailsElement).open;
    }, options);
  }

  unmount() {
    this.chart?.destroy(); this.chart = undefined;
    this.events?.abort(); this.events = undefined;
  }
}
