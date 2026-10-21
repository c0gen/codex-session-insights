import {
  Group,
  Box3,
  Vector3,
  Matrix4,
  Frustum,
  PerspectiveCamera,
  type Mesh,
} from "three";
import type { AssetLibrary } from "../assets";
import type { ViewFrame, WorldScene } from "../types";
import { number } from "../data";
import {
  CollectionLayout,
  occupancy,
  BOOKS_PER_CASE,
  DISKS_PER_CASE,
  CASES_PER_RACK,
} from "../collection-layout";
import { solids, type Solid } from "../collection-geometry";
import { block, clearGroup, finish, label, matrix } from "./common";

type Kind = "library" | "vault";
const transform = (
  p: { x: number; z: number; rotation: number },
  x: number,
  y: number,
  z: number,
) =>
  new Vector3(
    p.x + x * Math.cos(p.rotation) + z * Math.sin(p.rotation),
    y,
    p.z - x * Math.sin(p.rotation) + z * Math.cos(p.rotation),
  );
const boundsAt = (p: Vector3, w: number, h: number, d: number) =>
  new Box3(
    new Vector3(p.x - w / 2, p.y, p.z - d / 2),
    new Vector3(p.x + w / 2, p.y + h, p.z + d / 2),
  );
const bookPosition = (slot: number) =>
  [-0.57 + (slot % 30) * 0.039, 0.06 + Math.floor(slot / 30) * 0.34, 0] as [
    number,
    number,
    number,
  ];
const casePosition = (slot: number) =>
  [-0.45 + (slot % 4) * 0.3, 0.06 + Math.floor(slot / 4) * 0.34, 0] as [
    number,
    number,
    number,
  ];
const diskPosition = (slot: number) =>
  [
    -0.055 + Math.floor(slot / 50) * 0.11,
    0.012,
    -0.104 + (slot % 50) * 0.00425,
  ] as [number, number, number];

export function collectionScene(
  kind: Kind,
  total: number,
  assets: AssetLibrary,
): WorldScene {
  const library = kind === "library",
    capacity = library ? BOOKS_PER_CASE : DISKS_PER_CASE * CASES_PER_RACK;
  const layout = new CollectionLayout(total, capacity),
    count = occupancy(total, library ? 150 : 100).count;
  const root = new Group(),
    dynamic = new Group();
  root.add(dynamic);
  const parts = occupancy(total, capacity),
    last = occupancy(total),
    boxes = occupancy(total, 100);
  const summary = library
    ? `${number(parts.full, 0)} full bookcases${parts.remainder ? ` + ${number(parts.remainder)} novels in the final case` : ""} · ${number(layout.count, 0)} occupied bookcases`
    : `${number(parts.full, 0)} full racks + ${number(Math.floor(parts.remainder / 100), 0)} full cases + ${number(parts.remainder % 100)} disks · ${number(boxes.count, 0)} occupied cases`;
  const note = library
    ? "One detailed book = one 90,000-word novel equivalent. 30 books/tier × 5 tiers = 150/bookcase. Book dimensions and 1.24 m aisles are assumed; distant shelves simplify geometry, not quantity."
    : "100 disks/case × 20 cases/rack (assumed storage layout). One detailed disk = one disk equivalent; the final disk shows partial capacity.";
  const scene = finish(root, [], note + " " + summary, {}, layout.bounds);
  scene.presets.fit.direction = [0.7, 1, 1.2];
  let selected = 0,
    key = "";
  const rackIndex = () => (library ? selected : Math.floor(selected / 20));
  const selectedPosition = () => {
    const p = layout.position(rackIndex());
    return library
      ? new Vector3(p.x, 0, p.z)
      : transform(p, ...casePosition(selected % 20));
  };
  const itemAmount = () =>
    Math.max(
      0,
      Math.min(library ? 150 : 100, total - selected * (library ? 150 : 100)),
    );
  const selectedBounds = () =>
    boundsAt(
      selectedPosition(),
      library ? 1.32 : 0.27,
      library ? 1.8 : 0.175,
      library ? 0.3 : 0.23,
    );
  scene.selectedBounds = selectedBounds;
  scene.select = (index) => {
    selected = Math.max(
      0,
      Math.min(Math.max(0, count - 1), Math.floor(index) || 0),
    );
    key = "";
    const p = layout.position(rackIndex()),
      facing = p.rotation ? -1 : 1,
      b = selectedBounds();
    scene.protectedBounds = [b];
    scene.presets.inspect = {
      bounds: b.clone().expandByScalar(library ? 0.25 : 0.04),
      direction: [0.3 * facing, 0.25, facing],
    };
    if (library)
      Object.assign(scene.presets.inspect, {
        position: [p.x + 0.7 * facing, 1.5, p.z + 0.85 * facing],
        target: [p.x - 0.35 * facing, 1.1, p.z],
        fov: 60,
      });
    const lastSlot = Math.max(0, occupancy(itemAmount()).count - 1);
    const item = library
      ? transform(p, ...bookPosition(lastSlot))
      : selectedPosition().add(
          new Vector3(...diskPosition(lastSlot)).applyAxisAngle(
            new Vector3(0, 1, 0),
            p.rotation,
          ),
        );
    scene.presets.last = {
      bounds: boundsAt(
        item,
        library ? 0.16 : 0.15,
        library ? 0.28 : 0.13,
        library ? 0.2 : 0.06,
      ),
      direction: [0.4 * facing, 0.4, facing],
    };
    scene.labels = [
      {
        ...label(
          count
            ? `${library ? "Bookcase" : "Case"} ${number(selected + 1, 0)} · ${number(itemAmount())} ${library ? "novels" : "disks"}`
            : "Empty collection",
          b.getCenter(new Vector3()).x,
          b.max.y + 0.12,
          b.getCenter(new Vector3()).z,
          50,
        ),
        leader: true,
      },
    ];
    if (last.remainder && selected === count - 1) {
      scene.labels.push({
        ...label(
          `Final ${library ? "novel" : "disk"}: ${number(last.remainder * 100)}% filled`,
          item.x,
          item.y + (library ? 0.25 : 0.13),
          item.z,
          100,
        ),
        required: true,
        leader: true,
      });
    }
  };
  scene.inspection = () => ({
    count,
    selected,
    noun: library ? "Bookcase" : "Case",
    summary,
    description: count
      ? `${library ? "Bookcase" : "Case"} ${number(selected + 1, 0)} of ${number(count, 0)} · ${number(itemAmount())} ${library ? "novel" : "disk"} equivalents · ${library ? "Books" : "Disks"} ${number(selected * (library ? 150 : 100) + 1, 0)}–${number(Math.ceil(Math.min(total, (selected + 1) * (library ? 150 : 100))), 0)}${selected === count - 1 && last.remainder ? ` · final ${library ? "novel" : "disk"} ${number(last.remainder * 100)}% filled` : ""}`
      : "No occupied containers",
    map: {
      ...layout.map(),
      cells: layout.map().cells.map((c) => ({
        ...c,
        index: c.index * (library ? 1 : 20),
        count: c.count * (library ? 1 : 20),
      })),
    },
  });
  scene.select(0);
  scene.updateView = (view: ViewFrame) => {
    const { camera, height } = view;
    const frustum = new Frustum().setFromProjectionMatrix(
      new Matrix4().multiplyMatrices(
        camera.projectionMatrix,
        camera.matrixWorldInverse,
      ),
    );
    const pixelHeight = (box: Box3) => {
      const distance = Math.max(0.001, box.distanceToPoint(camera.position));
      return camera instanceof PerspectiveCamera
        ? (1.8 * height) /
            (2 * Math.tan((camera.fov * Math.PI) / 360) * distance)
        : (1.8 * height * Math.abs(camera.projectionMatrix.elements[5])) / 2;
    };
    const cases: number[] = [],
      far: { start: number; side: number; x: number; z: number }[] = [];
    const visit = (start: number, side: number, x: number, z: number) => {
      if (start >= layout.count) return;
      const box = layout.sectionBounds(side, x, z);
      if (!frustum.intersectsBox(box)) return;
      const full = start + side * side * 64 <= layout.count;
      const containsSelection =
        rackIndex() >= start && rackIndex() < start + side * side * 64;
      if (
        full &&
        !containsSelection &&
        (pixelHeight(box) < 10 ||
          cases.length >= (library ? 448 : 160) ||
          (far.length > 240 && side > 1))
      ) {
        far.push({ start, side, x, z });
        return;
      }
      if (side === 1) {
        for (let i = start; i < Math.min(layout.count, start + 64); i++)
          if (frustum.intersectsBox(layout.caseBounds(i))) cases.push(i);
        return;
      }
      const half = side / 2,
        step = half * half * 64;
      for (let q = 0; q < 4; q++)
        visit(
          start + q * step,
          half,
          x + (q % 2) * half,
          z + Math.floor(q / 2) * half,
        );
    };
    visit(0, layout.side, 0, 0);
    cases.sort(
      (a, b) =>
        layout
          .caseBounds(a)
          .getCenter(new Vector3())
          .distanceToSquared(camera.position) -
        layout
          .caseBounds(b)
          .getCenter(new Vector3())
          .distanceToSquared(camera.position),
    );
    const detailed = new Set(
      library
        ? cases
            .filter(
              (i) => (pixelHeight(layout.caseBounds(i)) * 0.22) / 1.8 >= 8,
            )
            .slice(0, 13)
        : [],
    );
    const inspectVault =
      !library &&
      cases.includes(rackIndex()) &&
      pixelHeight(selectedBounds()) > 400;
    cases.sort((a, b) => a - b);
    const signature = JSON.stringify([
      cases,
      far.map((f) => [f.start, f.side]),
      [...detailed].sort((a, b) => a - b),
      selected,
      inspectVault,
    ]);
    if (signature === key) return;
    key = signature;
    clearGroup(dynamic);
    const shelves: Matrix4[] = [],
      books: Matrix4[][] = [[], [], []],
      storage: Matrix4[] = [],
      disks: Matrix4[] = [],
      bands: Solid[] = [],
      proxies: Solid[] = [];
    for (const f of far) {
      const b = layout.sectionBounds(f.side, f.x, f.z),
        size = b.getSize(new Vector3()),
        p = b.getCenter(new Vector3());
      proxies.push({ x: p.x, y: 0.9, z: p.z, w: size.x, h: 1.8, d: size.z });
    }
    for (const index of cases) {
      const p = layout.position(index),
        amount = layout.amount(index);
      shelves.push(matrix(p.x, 0, p.z, 1, 1, p.rotation));
      if (library) {
        const used = occupancy(amount);
        if (detailed.has(index)) {
          for (let slot = 0; slot < used.count; slot++) {
            const v = transform(p, ...bookPosition(slot)),
              fraction =
                slot === used.count - 1 && used.remainder ? used.remainder : 1;
            if (fraction === 1)
              books[(index * 150 + slot) % 3].push(
                matrix(v.x, v.y, v.z, 1, 1, p.rotation + Math.PI),
              );
            else partialBook(dynamic, v, p.rotation, fraction);
          }
        } else
          for (let tier = 0; tier < 5; tier++) {
            const n = Math.max(0, Math.min(30, amount - tier * 30));
            if (!n) continue;
            const whole = Math.floor(n),
              fraction = n - whole;
            if (whole) {
              const width = (whole - 1) * 0.039 + 0.033;
              const v = transform(
                p,
                -0.57 + width / 2 - 0.0165,
                0.17 + tier * 0.34,
                0,
              );
              bands.push({
                x: v.x,
                y: v.y,
                z: v.z,
                w: width,
                h: 0.22,
                d: 0.1515,
                rotation: p.rotation,
                items: whole,
              });
            }
            if (fraction)
              partialBook(
                dynamic,
                transform(p, ...bookPosition(tier * 30 + whole)),
                p.rotation,
                fraction,
              );
          }
      } else {
        const used = occupancy(amount, 100);
        for (let slot = 0; slot < used.count; slot++) {
          const v = transform(p, ...casePosition(slot)),
            caseIndex = index * 20 + slot,
            fill = Math.min(100, amount - slot * 100);
          if (inspectVault && caseIndex === selected) {
            openCase(dynamic, v, p.rotation);
            const occupied = occupancy(fill);
            for (let disk = 0; disk < occupied.count; disk++) {
              const point = v
                .clone()
                .add(
                  new Vector3(...diskPosition(disk)).applyAxisAngle(
                    new Vector3(0, 1, 0),
                    p.rotation,
                  ),
                );
              disks.push(matrix(point.x, point.y, point.z, 1, 1, p.rotation));
              if (disk === occupied.count - 1 && occupied.remainder)
                fillMarker(
                  dynamic,
                  point,
                  p.rotation,
                  occupied.remainder,
                  false,
                );
            }
          } else {
            storage.push(matrix(v.x, v.y, v.z, 1, 1, p.rotation));
            if (fill < 100)
              fillMarker(dynamic, v, p.rotation, fill / 100, true);
          }
        }
      }
    }
    if (shelves.length) dynamic.add(assets.instances("shelf", shelves));
    ["book-blue", "book-red", "book-green"].forEach((id, i) => {
      if (books[i].length) dynamic.add(assets.instances(id, books[i]));
    });
    if (storage.length) dynamic.add(assets.instances("storage-box", storage));
    if (disks.length) dynamic.add(assets.instances("floppy", disks));
    solids(dynamic, bands, 0x567f86, "spines");
    solids(dynamic, proxies, 0x8c7960, "sections");
    dynamic.traverse((o) => {
      o.castShadow = false;
    });
    // Selected container outline remains meaningful even when distant detail is simplified.
    const b = selectedBounds(),
      v = b.getCenter(new Vector3());
    if (count && frustum.intersectsBox(b)) {
      const marker = block(
        dynamic,
        [b.max.x - b.min.x + 0.025, 0.012, b.max.z - b.min.z + 0.025],
        [v.x, b.min.y + 0.005, v.z],
        0xbf9449,
      );
      marker.castShadow = false;
    }
    root.userData.collection = {
      total,
      containers: layout.count,
      detailedProps: books.reduce((n, b) => n + b.length, 0) + disks.length,
      visibleCases: cases.length,
      farSections: far.length,
      ranges: [
        ...cases.map((i) => [
          i * capacity,
          Math.min(total, (i + 1) * capacity),
        ]),
        ...far.map((f) => [
          f.start * capacity,
          Math.min(total, (f.start + f.side * f.side * 64) * capacity),
        ]),
      ],
    };
  };
  return scene;
}
function partialBook(
  root: Group,
  p: Vector3,
  rotation: number,
  fraction: number,
) {
  const ghost = block(
    root,
    [0.033, 0.22, 0.1515],
    [p.x, p.y + 0.11, p.z],
    0x7a9c9b,
  );
  ghost.rotation.y = rotation;
  const material = ghost.material as import("three").MeshStandardMaterial;
  material.transparent = true;
  material.opacity = 0.2;
  material.depthWrite = false;
  const offset = new Vector3(
    (-0.033 * (1 - fraction)) / 2,
    0,
    0,
  ).applyAxisAngle(new Vector3(0, 1, 0), rotation);
  const fill = block(
    root,
    [Math.max(0.000001, 0.033 * fraction), 0.214, 0.147],
    [p.x + offset.x, p.y + 0.11, p.z + offset.z],
    0xc89c51,
  );
  fill.rotation.y = rotation;
}
function fillMarker(
  root: Group,
  p: Vector3,
  rotation: number,
  fraction: number,
  box: boolean,
) {
  const width = box ? 0.12 : 0.062,
    point = p
      .clone()
      .add(
        new Vector3(
          (-width * (1 - fraction)) / 2,
          box ? 0.085 : 0.035,
          box ? 0.113 : 0.0029,
        ).applyAxisAngle(new Vector3(0, 1, 0), rotation),
      );
  const bar = block(
    root,
    [Math.max(0.000001, width * fraction), box ? 0.012 : 0.006, 0.001],
    point.toArray(),
    0xbe8c42,
  );
  bar.rotation.y = rotation;
}
function openCase(root: Group, p: Vector3, rotation: number) {
  const group = new Group();
  group.position.copy(p);
  group.rotation.y = rotation;
  root.add(group);
  block(group, [0.26, 0.006, 0.22], [0, 0.003, 0], 0x9b9d8c);
  for (const x of [-0.128, 0.128])
    block(group, [0.004, 0.045, 0.22], [x, 0.0225, 0], 0x9b9d8c);
  for (const z of [-0.108, 0.108])
    block(group, [0.26, 0.045, 0.004], [0, 0.0225, z], 0x9b9d8c);
}
