import { Group, Box3, Vector3 } from "three";
import { paperLayout } from "../references";
import { distance, number } from "../data";
import type { SceneFactory } from "../types";
import { block, lines, label, finish, globe } from "./common";

export const paper: SceneFactory = (s, o, assets) => {
  const root = new Group(),
    height = s.values?.stack_meters ?? 0;
  const p = paperLayout(height, o.proportions, o.landmark),
    x = -0.55;
  const labels = [
    label(
      height ? distance(height, o.units) : "0 sheets",
      x - p.width / 2,
      p.height,
      p.depth / 2,
      100,
    ),
  ];
  Object.assign(labels[0], {
    id: "stack-height",
    placement: "side",
    required: true,
    leader: true,
  });
  const stackBounds = new Box3(
    new Vector3(x - p.width / 2, 0, -p.depth / 2),
    new Vector3(x + p.width / 2, Math.max(p.height, 0.000001), p.depth / 2),
  );
  if (height > 0) {
    block(root, [p.width, p.height, p.depth], [x, p.height / 2, 0]);
    const bands: number[] = [];
    for (let i = 1; i < Math.min(s.values!.pages, 64); i++) {
      const y = (p.height * i) / Math.min(s.values!.pages, 64);
      bands.push(
        x - p.width / 2,
        y,
        p.depth / 2 + 0.0001,
        x + p.width / 2,
        y,
        p.depth / 2 + 0.0001,
      );
    }
    lines(root, bands, 0xb8b5ac);
    // Selection outline stays legible even when true paper width is subpixel.
    lines(root, [x, p.height, 0, x, 0, 0], 0xb77d3a);
    const ruler = x - p.width / 2 - 0.12,
      ticks: number[] = [ruler, 0, 0, ruler, p.height, 0];
    for (let i = 0; i <= 4; i++) {
      const y = (p.height * i) / 4;
      ticks.push(ruler - 0.02, y, 0, ruler + 0.02, y, 0);
      if (i > 0 && i < 4)
        labels.push(
          label(distance((height * i) / 4, o.units), ruler - 0.06, y, 0),
        );
    }
    lines(root, ticks, 0x526a70);
  }
  let refX = 0.55;
  if (p.showReference) {
    if (p.reference.id === "earth")
      globe(
        root,
        p.reference.height / p.unit / 2,
        refX,
        p.reference.height / p.unit / 2,
      );
    else {
      const model = assets.model(p.reference.id, 1 / p.unit);
      const width = new Box3().setFromObject(model).getSize(new Vector3()).x;
      refX = Math.max(0.55, p.width / 2 + width / 2 + 0.1);
      model.position.x = refX;
      root.add(model);
    }
    labels.push(
      label(
        `${p.reference.name} · ${distance(p.reference.height, o.units)}`,
        refX,
        p.reference.height / p.unit + 0.06,
        0,
        5,
      ),
    );
  }
  const note =
    (p.enlargement > 1
      ? `Height to scale · paper width enlarged ×${number(p.enlargement)}. Edge bands are illustrative.`
      : "True sheet proportions · highlighted centre line keeps thin paper visible.") +
    (height && p.showReference
      ? ` ${number((height / p.reference.height) * 100)}% of ${p.reference.name} (${p.reference.note.toLowerCase()}).`
      : "");
  const scene = finish(root, labels, note, {
    ground: [x, 0, 0],
    top: [x, p.height, 0],
    landmark: [refX, p.reference.height / p.unit / 2, 0],
  });
  scene.protectedBounds = [stackBounds];
  scene.presets.fit = {
    bounds: stackBounds
      .clone()
      .expandByScalar(Math.max(p.height, p.width, p.depth) * 0.05),
    direction: [0.7, 0.35, 1.5],
  };
  scene.presets.landmark = {
    bounds: scene.bounds.clone(),
    direction: [0, 0, 1],
    projection: "orthographic",
  };
  const close = Math.max(p.width, p.depth, p.height * 0.1, 0.0001);
  scene.presets.top = {
    bounds: new Box3().setFromCenterAndSize(
      new Vector3(x, p.height - close * 0.15, 0),
      new Vector3(close * 1.6, close * 0.7, close * 1.6),
    ),
    direction: [0.6, 0.65, 1],
  };
  scene.presets.ground = {
    bounds: new Box3().setFromCenterAndSize(
      new Vector3(x, close * 0.3, 0),
      new Vector3(close * 1.6, close * 0.7, close * 1.6),
    ),
    direction: [0.6, 0.3, 1],
  };
  scene.initialPreset = p.showReference ? "landmark" : "fit";
  return scene;
};
