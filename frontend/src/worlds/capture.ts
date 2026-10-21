import { MAX_IMAGE_BYTES } from "../image-transport";
import {
  exhibitMeasure,
  WORLDS,
  number,
  type WorldOptions,
  type WorldSnapshot,
} from "./data";
import { fallbackSvg } from "./fallback";
import type { WorldRenderer } from "./renderer";
import { inspectionMap } from "./inspection";

function wrap(
  ctx: CanvasRenderingContext2D,
  text: string,
  x: number,
  y: number,
  width: number,
  lineHeight = 19,
) {
  let line = "";
  for (const word of text.split(" ")) {
    if (ctx.measureText(line + word).width > width && line) {
      ctx.fillText(line.trim(), x, y);
      y += lineHeight;
      line = "";
    }
    line += word + " ";
  }
  ctx.fillText(line.trim(), x, y);
  return y + lineHeight;
}
async function svgImage(svg: string): Promise<HTMLImageElement> {
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try {
    const image = new Image();
    image.src = url;
    await image.decode();
    return image;
  } finally {
    URL.revokeObjectURL(url);
  }
}
export async function captureExhibit(
  s: WorldSnapshot,
  o: WorldOptions,
  note: string,
  renderer: WorldRenderer | null,
): Promise<Blob> {
  const canvas = document.createElement("canvas");
  canvas.width = 1200;
  canvas.height = 720;
  const ctx = canvas.getContext("2d")!;
  ctx.fillStyle = "#f0f1ec";
  ctx.fillRect(0, 0, 1200, 720);
  const frame = renderer?.capture();
  const inspection = renderer?.inspection();
  const inset =
    renderer?.overviewSvg() || (inspection ? inspectionMap(inspection) : "");
  const image = frame?.canvas ?? (await svgImage(fallbackSvg(s, o)));
  const width =
    "naturalWidth" in image ? image.naturalWidth || 800 : image.width;
  const height =
    "naturalHeight" in image ? image.naturalHeight || 360 : image.height;
  const scale = Math.min(1120 / width, 430 / height),
    w = width * scale,
    h = height * scale,
    x = (1200 - w) / 2,
    y = 125 + (430 - h) / 2;
  ctx.drawImage(image, x, y, w, h);
  if (frame && inset) {
    const svg = inset.replace(
      "<svg ",
      '<svg xmlns="http://www.w3.org/2000/svg" ',
    );
    const detail = await svgImage(svg),
      iw = inspection ? 180 : 160,
      ih = inspection ? 110 : 89;
    ctx.drawImage(detail, x + w - iw - 10, y + h - ih - 10, iw, ih);
  }
  if (frame) {
    ctx.font = "13px Arial";
    ctx.textAlign = "center";
    for (const l of frame.labels) {
      const tx = x + l.x * w,
        ty = y + l.y * h,
        tw = ctx.measureText(l.text).width;
      ctx.fillStyle = "rgba(248,249,245,.94)";
      ctx.fillRect(tx - tw / 2 - 7, ty - 4, tw + 14, 22);
      ctx.fillStyle = "#304a53";
      ctx.fillText(l.text, tx, ty + 11);
    }
  }
  ctx.textAlign = "left";
  const measure = exhibitMeasure(s, o);
  ctx.fillStyle = "#213c45";
  ctx.font = "bold 29px Arial";
  ctx.fillText(WORLDS.find((w) => w.id === o.world)!.title, 40, 48);
  ctx.font = "bold 24px Arial";
  ctx.fillText(`${measure.value} · ${measure.label}`, 40, 87);
  ctx.font = "15px Arial";
  ctx.fillStyle = "#52676c";
  ctx.fillText(
    `${s.tokens === null ? "Unavailable" : number(s.tokens, 0) + " tokens"} · ${s.basis === "total" ? "Total processed" : "Output only"} · ${o.units === "metric" ? "Metric" : "Imperial"} units${s.partial ? " · partial" : ""}${s.stale ? " · stale" : ""}${s.demo ? " · demo" : ""}${s.saved ? " · saved snapshot" : ""}`,
    40,
    112,
  );
  ctx.font = "13px Arial";
  let next = wrap(ctx, note, 40, 566, 1120, 16);
  next = wrap(ctx, measure.explanation, 40, next + 2, 1120, 16);
  // No account/provider identities, paths, or project names are captured.
  const scope = s.captureScope;
  next = wrap(
    ctx,
    scope +
      " " +
      (s.detail.includes("Indexed Codex fallback")
        ? "Indexed Codex fallback. "
        : "") +
      "0.75 words/token; approximate text volume.",
    40,
    next + 2,
    1120,
    16,
  );
  ctx.font = "13px Arial";
  ctx.fillText(
    "Includes repeated context; output includes reasoning and tool output.  •  Codex Session Insights",
    40,
    696,
  );
  const blob = await new Promise<Blob>((resolve, reject) =>
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("PNG encoding failed"))),
      "image/png",
    ),
  );
  if (blob.size > MAX_IMAGE_BYTES)
    throw new Error("Image exceeds the 2 MiB limit");
  return blob;
}
