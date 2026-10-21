import { Vector3, type Camera, type Box3 } from "three";
import type { SceneLabel } from "./types";
import { corners } from "./camera";

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}
export interface Annotation extends Rect {
  id: string;
  text: string;
  lines: string[];
  anchor: [number, number];
  leader: boolean;
  docked: boolean;
}
export const LABEL_FONT = "12px Arial";
export const LABEL_LINE = 16;
export function intersects(a: Rect, b: Rect, gap = 6) {
  return (
    a.x < b.x + b.w + gap &&
    a.x + a.w + gap > b.x &&
    a.y < b.y + b.h + gap &&
    a.y + a.h + gap > b.y
  );
}
export function projectedBounds(
  box: Box3,
  camera: Camera,
  width: number,
  height: number,
): Rect | null {
  const points = corners(box)
    .map((p) => p.project(camera))
    .filter((p) => p.z >= -1 && p.z <= 1);
  if (!points.length) return null;
  const xs = points.map((p) => ((p.x + 1) * width) / 2),
    ys = points.map((p) => ((1 - p.y) * height) / 2);
  return {
    x: Math.min(...xs) - 4,
    y: Math.min(...ys) - 4,
    w: Math.max(...xs) - Math.min(...xs) + 8,
    h: Math.max(...ys) - Math.min(...ys) + 8,
  };
}
export function wrapLabel(
  text: string,
  max: number,
  measure: (text: string) => number,
) {
  const lines: string[] = [];
  let line = "";
  for (const word of text.split(" ")) {
    if (line && measure(`${line} ${word}`) > max) {
      lines.push(line);
      line = "";
    }
    line += (line ? " " : "") + word;
  }
  if (line) lines.push(line);
  return lines;
}
/** The top rail is outside the drawing area: essential callouts never cover geometry. */
export function layoutAnnotations(
  labels: SceneLabel[],
  protectedBoxes: Box3[],
  camera: Camera,
  width: number,
  height: number,
  measure: (text: string) => number,
) {
  const avoid = protectedBoxes
    .map((b) => projectedBounds(b, camera, width, height))
    .filter((r): r is Rect => !!r);
  const placed: Annotation[] = [];
  for (const [i, label] of [...labels]
    .sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0))
    .entries()) {
    const p = label.position.clone().project(camera);
    if ((p.z < -1 || p.z > 1) && !label.required) continue;
    const ax = ((p.x + 1) * width) / 2,
      ay = ((1 - p.y) * height) / 2;
    const visible =
      p.z >= -1 &&
      p.z <= 1 &&
      ax >= 0 &&
      ax <= width &&
      ay >= 0 &&
      ay <= height;
    if (!visible && !label.required) continue;
    const lines = wrapLabel(label.text, Math.min(260, width - 32), measure);
    const w = Math.min(
        width - 16,
        Math.ceil(Math.max(...lines.map(measure))) + 18,
      ),
      h = lines.length * LABEL_LINE + 8;
    const side: Rect[] = [
      { x: ax - w - 22, y: ay - h / 2, w, h },
      { x: ax + 22, y: ay - h / 2, w, h },
    ];
    const above: Rect = { x: ax - w / 2, y: ay - h - 20, w, h };
    const candidates =
      label.placement === "side" ? [...side, above] : [above, ...side];
    // Also try beside the complete protected silhouette, not just beside its anchor.
    for (const r of avoid)
      candidates.push(
        {
          x: r.x - w - 14,
          y: Math.max(8, Math.min(height - h - 8, ay - h / 2)),
          w,
          h,
        },
        {
          x: r.x + r.w + 14,
          y: Math.max(8, Math.min(height - h - 8, ay - h / 2)),
          w,
          h,
        },
      );
    const found = visible
      ? candidates.find(
          (r) =>
            r.x >= 8 &&
            r.y >= 8 &&
            r.x + r.w <= width - 8 &&
            r.y + r.h <= height - 8 &&
            !avoid.some((a) => intersects(r, a)) &&
            !placed.some((a) => !a.docked && intersects(r, a)),
        )
      : undefined;
    if (!found && !label.required) continue;
    placed.push({
      ...(found ?? { x: 8, y: -h - 8, w, h }),
      id: label.id ?? `label-${i}`,
      text: label.text,
      lines,
      anchor: [ax, ay],
      leader:
        !!label.leader &&
        p.z >= -1 &&
        p.z <= 1 &&
        ax >= 0 &&
        ax <= width &&
        ay >= 0 &&
        ay <= height,
      docked: !found,
    });
  }
  return { labels: placed, protected: avoid };
}
export function drawAnnotations(
  ctx: CanvasRenderingContext2D,
  labels: Annotation[],
  offsetX = 0,
  offsetY = 0,
  scale = 1,
) {
  ctx.save();
  ctx.translate(offsetX, offsetY);
  ctx.scale(scale, scale);
  ctx.font = LABEL_FONT;
  ctx.textAlign = "left";
  for (const l of labels) {
    if (l.leader && !l.docked) {
      ctx.beginPath();
      ctx.moveTo(...l.anchor);
      ctx.lineTo(
        Math.max(l.x, Math.min(l.x + l.w, l.anchor[0])),
        Math.max(l.y, Math.min(l.y + l.h, l.anchor[1])),
      );
      ctx.strokeStyle = "#86683e";
      ctx.lineWidth = 1;
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(...l.anchor, 2, 0, Math.PI * 2);
      ctx.fillStyle = "#86683e";
      ctx.fill();
    }
    ctx.fillStyle = "rgba(250,251,244,.97)";
    ctx.fillRect(l.x, l.y, l.w, l.h);
    ctx.fillStyle = "#304a53";
    l.lines.forEach((line, i) =>
      ctx.fillText(line, l.x + 8, l.y + 17 + i * LABEL_LINE),
    );
  }
  ctx.restore();
}
