import { icon } from "./icons";
export const esc = (value: unknown) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ]!,
  );
export const count = (n: number) =>
  new Intl.NumberFormat("en-US").format(n || 0);
export const dateLabel = (value: string) =>
  value
    ? new Date(value + "T12:00:00").toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      })
    : "—";
export const tip = (text: string) =>
  `<span class="info" tabindex="0" title="${esc(text)}" aria-label="${esc(text)}">${icon("info", 16)}</span>`;
export const button = (
  id: string,
  label: string,
  symbol: string,
  primary = false,
) =>
  `<button id="${id}" class="button ${primary ? "primary" : ""}">${icon(symbol)}<span>${label}</span></button>`;
export const segment = (
  name: string,
  values: [string, string][],
  selected: string,
) =>
  `<div class="segmented" role="group" aria-label="${name}">${values.map(([value, label]) => `<button data-${name}="${value}" class="${selected === value ? "selected" : ""}" aria-pressed="${selected === value}">${label}</button>`).join("")}</div>`;
