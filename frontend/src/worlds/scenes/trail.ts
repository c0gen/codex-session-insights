import {
  Group,
  BufferGeometry,
  Vector3,
  Line,
  LineBasicMaterial,
  Box3,
  Mesh,
  ConeGeometry,
  MeshStandardMaterial,
} from "three";
import {
  EARTH_RADIUS_M,
  EARTH_CIRCUIT_M,
  distance,
  number,
  trailMode,
} from "../data";
import type { SceneFactory } from "../types";
import { finish, globe, block, lines, label } from "./common";

export const trail: SceneFactory = (s, o, assets) => {
  const root = new Group(),
    metres = s.trailMetres ?? 0;
  if (trailMode(metres, o.trailView) === "unrolled") {
    const unit = Math.max(metres, 1),
      length = metres / unit,
      width = Math.max(0.2159 / unit, 0.024);
    if (metres > 0) block(root, [length, 0.003, width], [length / 2, 0, 0]);
    const labels = [
      {
        ...label(`End · ${distance(metres, o.units)}`, length, 0.015, 0, 100),
        required: true,
        leader: true,
      },
    ];
    const ticks: number[] = [];
    for (let i = 0; i <= 4; i++) {
      const x = (length * i) / 4;
      ticks.push(x, 0.004, width / 2 + 0.018, x, 0.004, width / 2 + 0.035);
      if (i < 4)
        labels.push({
          ...label(
            i ? distance((metres * i) / 4, o.units) : "Start",
            x,
            0.004,
            width / 2 + 0.055,
            5,
          ),
          required: false,
          leader: false,
        });
    }
    lines(root, ticks, 0x526a70);
    if (metres > 0) {
      block(root, [0.008, 0.025, width], [0, 0.01, 0], 0x547f7a);
      block(root, [0.008, 0.025, width], [length, 0.01, 0], 0xb98436);
    }
    if (metres < 15) {
      const person = assets.model("person", 1 / unit);
      person.position.set(0, 0, -width / 2 - 0.3 / unit);
      root.add(person);
    }
    const scene = finish(
      root,
      labels,
      `Unrolled distance diagram · length to scale; ribbon width enlarged when needed. Sheet detail is independently magnified. ${number(metres / EARTH_CIRCUIT_M, 3)} Earth circuits.`,
    );
    scene.presets.fit.direction = [0.15, 1.25, 1];
    scene.presets.route = scene.presets.fit;
    return scene;
  }
  globe(root);
  const laps = Math.floor(metres / EARTH_CIRCUIT_M),
    remainder = metres % EARTH_CIRCUIT_M,
    angle = remainder / EARTH_RADIUS_M;
  function arc(a: number, color: number) {
    const points = Array.from(
      { length: 257 },
      (_, i) =>
        new Vector3(
          Math.sin((a * i) / 256) * 1.014,
          1,
          Math.cos((a * i) / 256) * 1.014,
        ),
    );
    root.add(
      new Line(
        new BufferGeometry().setFromPoints(points),
        new LineBasicMaterial({ color }),
      ),
    );
    return points;
  }
  if (laps > 0) arc(Math.PI * 2, 0xabc5c1);
  const points = arc(angle, 0xffcb64);
  const start = new Vector3(0, 1, 1.02),
    end = new Vector3(Math.sin(angle) * 1.02, 1, Math.cos(angle) * 1.02);
  const marker = Math.min(0.014, Math.max(0.0004, angle * 0.035));
  block(root, [marker, marker * 2, marker], start.toArray(), 0x74bba8);
  block(root, [marker, marker * 2, marker], end.toArray(), 0xffc75b);
  if (angle > 0.005) {
    const a = angle / 2,
      length = Math.min(0.05, angle * 0.15);
    const arrow = new Mesh(
      new ConeGeometry(length * 0.23, length, 8),
      new MeshStandardMaterial({ color: 0xffcb64 }),
    );
    arrow.position.set(Math.sin(a) * 1.014, 1, Math.cos(a) * 1.014);
    arrow.quaternion.setFromUnitVectors(
      new Vector3(0, 1, 0),
      new Vector3(Math.cos(a), 0, -Math.sin(a)),
    );
    root.add(arrow);
  }
  const labels = [
    {
      ...label(
        `${number(laps, 0)} complete circuits + ${distance(remainder, o.units)}`,
        0,
        2.08,
        0,
        100,
      ),
      required: true,
    },
    label("Start", ...start.toArray(), 5),
    label("End", ...end.toArray(), 10),
  ];
  const scene = finish(
    root,
    labels,
    "Spherical Earth · gold shows the remaining route and its direction; the pale circuit represents the counted complete laps. Route thickness enlarged.",
  );
  scene.presets.fit.direction = [0.3, 0.5, 1.5];
  const bounds = new Box3().setFromPoints(points).expandByScalar(0.035);
  scene.presets.route = {
    bounds,
    direction: [Math.sin(angle / 2), 0.35, Math.cos(angle / 2)],
  };
  const dash = 2 * Math.PI * 31 * (remainder / EARTH_CIRCUIT_M);
  scene.overviewSvg = () =>
    `<svg viewBox="0 0 180 100" role="img" aria-label="Whole Earth overview: ${number(laps, 0)} complete circuits"><circle cx="50" cy="46" r="31" fill="#406779"/><circle cx="50" cy="46" r="31" fill="none" stroke="#e8be72" stroke-width="3" stroke-dasharray="${dash} 195" transform="rotate(-90 50 46)"/><text x="91" y="40">${number(laps, 0)} full laps</text><text x="91" y="57">+ ${number((remainder / EARTH_CIRCUIT_M) * 100)}%</text><text x="19" y="94">Whole Earth overview</text></svg>`;
  return scene;
};
