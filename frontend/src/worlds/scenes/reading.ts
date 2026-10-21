import { Group, Box3, Vector3, type Matrix4 } from "three";
import { duration, readingElapsed, scheduleName } from "../data";
import type { SceneFactory } from "../types";
import { matrix, label, finish, block } from "./common";

export function timelineStep(total: number) {
  if (!(total > 0)) return 1;
  const unit =
    total < 60
      ? 1
      : total < 1440
        ? 60
        : total < 525960
          ? 1440
          : total < 52596000
            ? 525960
            : 52596000;
  const raw = total / unit / 8,
    power = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 5, 10].find((n) => n * power >= raw)! * power * unit;
}
export const reading: SceneFactory = (s, o, assets) => {
  const root = new Group(),
    minutes = s.readingMinutes ?? 0,
    elapsed = readingElapsed(minutes, o.readingSchedule);
  const step = timelineStep(elapsed),
    count = Math.ceil(elapsed / step),
    length = (elapsed / step) * 1.4;
  const desk = assets.model("desk");
  desk.position.set(0, 0, 1.25);
  root.add(desk);
  const chair = assets.model("chair");
  chair.position.set(0, 0, 1.9);
  root.add(chair);
  if (length > 0)
    block(root, [3, 0.025, length], [0, -0.015, -length / 2], 0xd3d7ce);
  const bays: Matrix4[] = [];
  const labels = [label("Start reading", 0, 1.1, 1.25, 5)];
  for (let i = 0; i < count; i++) {
    bays.push(matrix(0, 0, -i * 1.4));
    if (i > 0) labels.push(label(duration(i * step), -1.65, 2.85, -i * 1.4, 2));
  }
  if (bays.length) root.add(assets.instances("bay", bays));
  if (elapsed > 0) block(root, [3, 0.035, 0.08], [0, 0.025, -length], 0xb08443);
  labels.push({
    ...label(
      `${duration(elapsed)} · ${scheduleName(o.readingSchedule)}`,
      0,
      3.05,
      -length,
      100,
    ),
    id: "reading-end",
    required: true,
    leader: true,
  });
  const scene = finish(
    root,
    labels,
    `Reading time: ${duration(minutes)} continuously. Elapsed: ${duration(elapsed)} at ${scheduleName(o.readingSchedule)}. Each bay = ${duration(step)}; distance is symbolic and the gold line marks the exact endpoint.`,
  );
  scene.presets.ground = {
    bounds: new Box3(new Vector3(-1.7, 0, -1), new Vector3(1.7, 2.9, 2.2)),
    direction: [0.5, 0.3, 1],
  };
  scene.presets.top = {
    bounds: new Box3(
      new Vector3(-1.7, 0, -length - 0.5),
      new Vector3(1.7, 3.2, -length + 1),
    ),
    direction: [0.6, 0.4, 1],
  };
  scene.presets.fit.direction = [1, 0.8, 1.3];
  return scene;
};
