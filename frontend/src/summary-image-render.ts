/** Render an analytics card independently of the dashboard DOM and its charts. */
import { compact, currency } from "./format";
import { count } from "./ui";
import type { SummaryImageSnapshot } from "./summary-image-data";

export const summaryImageSize = { width: 1200, height: 720 } as const;
const palette = { background: "#10171c", panel: "#172127", border: "#2a373f", text: "#e9edf6", muted: "#acbbce", mint: "#60dfba", red: "#ed8e91" };

export function summaryImageCanvas(snapshot: SummaryImageSnapshot): HTMLCanvasElement {
  const canvas = document.createElement("canvas");
  canvas.width = summaryImageSize.width;
  canvas.height = summaryImageSize.height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Image rendering is unavailable.");
  ctx.scale(2, 2);
  ctx.fillStyle = palette.background;
  ctx.fillRect(0, 0, 600, 360);
  const backdrop = ctx.createLinearGradient(0, 0, 600, 360);
  backdrop.addColorStop(0, "#1b2b30"); backdrop.addColorStop(1, palette.background);
  ctx.fillStyle = backdrop; ctx.fillRect(0, 0, 600, 360);

  function text(value: string, x: number, y: number, size = 10, color = palette.text, width = 552, weight = 400, minimum = size) {
    let actual = size;
    const font = () => { ctx!.font = `${weight} ${actual}px "Segoe UI", -apple-system, sans-serif`; };
    font();
    while (actual > minimum && ctx!.measureText(value).width > width) { actual -= 0.5; font(); }
    if (ctx!.measureText(value).width > width) {
      const characters = Array.from(value);
      while (characters.length && ctx!.measureText(characters.join("") + "…").width > width) characters.pop();
      value = characters.join("") + "…";
    }
    ctx!.fillStyle = color;
    ctx!.fillText(value, x, y);
  }
  function panel(x: number, y: number, w: number, h: number) {
    ctx!.beginPath(); ctx!.roundRect(x, y, w, h, 7);
    ctx!.fillStyle = palette.panel; ctx!.fill();
    ctx!.strokeStyle = palette.border; ctx!.lineWidth = 0.6; ctx!.stroke();
  }

  text("CODEX SESSION INSIGHTS", 24, 28, 10, palette.mint, 430, 600);
  text("Usage summary", 24, 58, 24, palette.text, 450, 650);
  if (snapshot.demo) {
    panel(501, 18, 75, 22);
    text("Demo data", 512, 33, 9, palette.mint, 55);
  }
  text(snapshot.dateLabel, 24, 82, 12, palette.text, 552, 500, 10);
  text(snapshot.context, 24, 102, 10, palette.muted);
  text(snapshot.timezone, 24, 118, 8, palette.muted);

  const width = 130.5, positions = [24, 164.5, 305, 445.5];
  positions.forEach(x => panel(x, 134, width, 91));
  const metric = (index: number, heading: string, value: string, note: string, shorter = value) => {
    const x = positions[index] + 11;
    text(heading, x, 153, 9, palette.muted, width - 22);
    ctx.font = '650 13px "Segoe UI", sans-serif';
    if (ctx.measureText(value).width > width - 22) value = shorter;
    text(value, x, 184, 25, palette.text, width - 22, 650, 13);
    text(note, x, 208, 8, palette.muted, width - 22);
  };
  metric(0, "Analyzed tokens", snapshot.tokens == null ? "Unavailable" : compact(snapshot.tokens), "Includes cached usage");
  metric(1, "Est. API-equivalent cost", snapshot.cost == null ? "Unavailable" : currency(snapshot.cost), `USD · ${snapshot.pricedPercent}% priced`, snapshot.cost == null ? "Unavailable" : `$${compact(snapshot.cost)}`);
  metric(2, "Observed line changes", count(snapshot.added + snapshot.removed), "", compact(snapshot.added + snapshot.removed));
  text(`+${count(snapshot.added)} added`, positions[2] + 11, 201, 8, palette.mint, width - 22);
  text(`−${count(snapshot.removed)} removed`, positions[2] + 11, 214, 8, palette.red, width - 22);
  metric(3, "Chats", count(snapshot.chats), "Main chats", compact(snapshot.chats));

  panel(24, 239, 552, 95);
  const values = snapshot.activity;
  const days = snapshot.start ? (Date.parse(snapshot.end) - Date.parse(snapshot.start)) / 86_400_000 + 1 : 0;
  text(days > 180 ? "Token activity · grouped calendar totals" : "Token activity · daily totals", 35, 256, 9, palette.muted);
  const left = 71, right = 562, top = 270, bottom = 310;
  ctx.strokeStyle = palette.border; ctx.lineWidth = 0.5;
  for (const y of [top, (top + bottom) / 2, bottom]) {
    ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(right, y); ctx.stroke();
  }
  const maximum = Math.max(1, ...values);
  text(snapshot.hasActivity ? compact(maximum) : "0", 35, top + 3, 7, palette.muted, 30);
  text("0", 35, bottom + 2, 7, palette.muted, 30);
  if (!snapshot.hasActivity) {
    text("No activity", 275, 292, 11, palette.muted, 200);
  } else if (values.length === 1) {
    const bar = (right - left) / 2 + left;
    ctx.fillStyle = palette.mint;
    ctx.beginPath(); ctx.roundRect(bar - 15, top, 30, bottom - top, [3, 3, 0, 0]); ctx.fill();
  } else {
    const points = values.map((value, index) => [left + index * (right - left) / (values.length - 1), bottom - value / maximum * (bottom - top)]);
    ctx.beginPath(); ctx.moveTo(left, bottom);
    points.forEach(([x, y]) => ctx.lineTo(x, y));
    ctx.lineTo(right, bottom); ctx.closePath();
    const fill = ctx.createLinearGradient(0, top, 0, bottom);
    fill.addColorStop(0, "rgba(96,223,186,.3)"); fill.addColorStop(1, "rgba(96,223,186,.025)");
    ctx.fillStyle = fill; ctx.fill();
    ctx.beginPath(); points.forEach(([x, y], index) => index ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
    ctx.strokeStyle = palette.mint; ctx.lineWidth = 1.4; ctx.stroke();
  }
  const dateText = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString("en-US", { timeZone: "UTC", month: "short", day: "numeric" });
  if (snapshot.start) text(dateText(snapshot.start), left, 325, 7, palette.muted, 150);
  const endLabel = dateText(snapshot.end);
  ctx.font = '400 7px "Segoe UI", sans-serif';
  text(endLabel, right - ctx.measureText(endLabel).width, 325, 7, palette.muted, 100);

  const notes = ["API-equivalent estimate", snapshot.partial ? "Partial observation · repeated edits count" : "Repeated edits count"];
  if (snapshot.fastPercent) notes.push(`${snapshot.fastPercent}% Fast assumed where unlogged`);
  text(notes.join(" · "), 24, 351, 8, palette.muted, 552, 400, 7);
  return canvas;
}

export function renderSummaryImage(snapshot: SummaryImageSnapshot): Promise<Blob> {
  const canvas = summaryImageCanvas(snapshot);
  return new Promise((resolve, reject) => canvas.toBlob(blob => {
    if (blob) resolve(blob); else reject(new Error("Could not generate the summary image."));
  }, "image/png"));
}
