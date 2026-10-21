import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { resolve } from "node:path";
import { build } from "../frontend/node_modules/esbuild/lib/main.js";
import { metricFixture } from "./metric-interface-fixture.mjs";
import { coverageFixture } from "./dashboard-fixture.mjs";

const dir = "frontend/src/worlds/assets";
const manifest = JSON.parse(await readFile(`${dir}/manifest.json`, "utf8"));
const embedded = {};
let bytes = 0;
for (const asset of manifest.assets) {
  const buffer = await readFile(`${dir}/${asset.file}`);
  bytes += buffer.length;
  assert.equal(createHash("sha256").update(buffer).digest("hex"), asset.sha256);
  assert.equal(buffer.readUInt32LE(0), 0x46546c67);
  const gltf = JSON.parse(
    buffer.subarray(20, 20 + buffer.readUInt32LE(12)).toString(),
  );
  for (const anchor of ["ground", "top"])
    assert(
      gltf.nodes.some((n) => n.name === `${asset.id}-anchor-${anchor}`),
      `${asset.id} named ${anchor} attachment`,
    );
  assert(
    gltf.buffers.every((b) => !b.uri),
    "GLBs must have no external buffers",
  );
  assert(
    (gltf.images || []).every((i) => i.bufferView !== undefined),
    "Textures must be embedded",
  );
  assert(
    !(gltf.extensionsRequired || []).some((x) =>
      /draco|meshopt|basisu/i.test(x),
    ),
    "No external decoders",
  );
  assert(
    asset.triangles <=
      (["eiffel", "burj", "everest", "house"].includes(asset.id)
        ? 20000
        : 2000),
  );
  embedded[`./assets/${asset.file}`] =
    `data:model/gltf-binary;base64,${buffer.toString("base64")}`;
}
assert(bytes < 8 * 1024 * 1024);
assert.equal((await readdir(dir)).filter((x) => x.endsWith(".glb")).length, 14);
const compiled = await build({
  stdin: {
    contents: `export * from './frontend/src/worlds/data'; export * from './frontend/src/worlds/references';
    export * from './frontend/src/worlds/scenes'; export * from './frontend/src/worlds/assets';
    export * from './frontend/src/worlds/collection-layout'; export * from './frontend/src/worlds/camera'; export * from './frontend/src/worlds/annotations';
    export {Box3,Vector3,Mesh,InstancedMesh,PerspectiveCamera,OrthographicCamera} from './frontend/node_modules/three/build/three.module.js';`,
    resolveDir: resolve("."),
  },
  bundle: true,
  format: "esm",
  write: false,
  plugins: [
    {
      name: "embedded-models",
      setup(b) {
        b.onLoad({ filter: /worlds[\\/]assets\.ts$/ }, async (args) => ({
          contents: (await readFile(args.path, "utf8")).replace(
            /import\.meta\.glob\([^;]+\) as Record<string,\s*string>/,
            JSON.stringify(embedded),
          ),
          loader: "ts",
        }));
      },
    },
  ],
});
const m = await import(
  `data:text/javascript;base64,${Buffer.from(compiled.outputFiles[0].text).toString("base64")}`
);
const fixture = metricFixture();
const snapshot = (tokens) => {
  fixture.summary.total_tokens = tokens;
  return m.worldSnapshot(fixture, "total");
};
for (const [tokens, pages, height] of [
  [0, 0, 0],
  [1, 1, 0.0001016],
  [666, 1, 0.0001016],
  [667, 2, 0.0002032],
  [2000, 3, 0.0003048],
  [2001, 4, 0.0004064],
  [1e9, 1500000, 152.4],
  [1e12, 1500000000, 152400],
]) {
  const s = snapshot(tokens);
  assert.equal(s.values.pages, pages);
  assert(Math.abs(s.values.stack_meters - height) < 1e-8);
  assert(Math.abs(s.trailMetres - pages * 0.2794) < 1e-7);
}
assert.equal(snapshot(180000).values.novels, 1.5);
assert.equal(snapshot(540000).values.floppy_disks, 1.5);
assert.equal(snapshot(12000).readingMinutes, 60);
assert.equal(m.distance(152.4, "imperial"), "500 ft");
assert.notEqual(
  m.exhibitMeasure(snapshot(1), { ...m.DEFAULT_OPTIONS, world: "library" })
    .value,
  "0",
);
assert.notEqual(m.distance(0.0001016, "imperial"), "0 in");
for (const value of [-1, NaN, Infinity])
  assert.equal(snapshot(value).values, null);
assert.deepEqual(m.restoreWorldOptions("{bad"), m.DEFAULT_OPTIONS);
assert.equal(
  m.restoreWorldOptions(
    '{"world":"trail","units":"metric","proportions":"true"}',
  ).world,
  "trail",
);
for (const total of [0, 0.0001, 0.5, 1, 120, 120.5, 720, 1e6, 1e12]) {
  const g = m.groupedCount(total);
  assert(g.count <= 120);
  assert(
    Math.abs((g.count ? g.count - 1 + g.last : 0) * g.unit - total) <=
      Math.max(1e-12, total * 1e-12),
  );
}
for (const height of [0.0001016, 0.2, 1.75, 10, 152.4, 828, 8848.86, 152400]) {
  const p = m.paperLayout(height, "true");
  assert.equal(p.enlargement, 1);
  assert(Math.abs(p.width / p.height - 0.2159 / height) < 1e-9);
  assert(
    Math.abs(
      p.reference.height / p.unit / p.height - p.reference.height / height,
    ) < 1e-5,
  );
  const readable = m.paperLayout(height, "readable");
  assert.equal(readable.height, p.height);
  assert(Math.abs(readable.width - p.width * readable.enlargement) < 1e-12);
}
fixture.demo = false;
fixture.indexed_token_totals = {
  codex: { total_tokens: 500, state: "complete", sessions: 1 },
  claude_code: { total_tokens: 20, state: "complete", sessions: 1 },
  antigravity: { total_tokens: 30, state: "complete", sessions: 1 },
};
fixture.account_token_total = {
  total_tokens: 1000,
  accounts: 1,
  reported_accounts: 1,
  identity_complete: true,
  stale: false,
};
assert.equal(m.worldSnapshot(fixture, "total").tokens, 1050);
fixture.filters.range = "today";
assert.equal(m.worldSnapshot(fixture, "total").tokens, 1050);
assert.equal(m.worldSnapshot(fixture, "output").tokens, 20);
fixture.account_token_total.total_tokens = null;
assert.equal(m.worldSnapshot(fixture, "total").tokens, 550);
assert.match(
  m.worldSnapshot(fixture, "total").detail,
  /Indexed Codex fallback/,
);
Object.assign(fixture.account_token_total, {
  total_tokens: 1000,
  identity_complete: false,
  stale: true,
});
assert(
  m.worldSnapshot(fixture, "total").partial &&
    m.worldSnapshot(fixture, "total").stale,
);
fixture.readonly = true;
fixture.summary.total_tokens = 0;
assert.equal(m.worldSnapshot(fixture, "total").tokens, 0);
fixture.coverage = coverageFixture("unavailable");
assert.equal(m.worldSnapshot(fixture, "total").tokens, null);
fixture.coverage = coverageFixture("partial");
assert(m.worldSnapshot(fixture, "total").partial);
fixture.coverage = coverageFixture();

const assets = new m.AssetLibrary();
await assets.load(manifest.assets.map((a) => a.id));
for (const asset of manifest.assets) {
  const bounds = new m.Box3().setFromObject(assets.model(asset.id));
  const size = bounds.getSize(new m.Vector3()).toArray();
  size.forEach((n, i) =>
    assert(
      Math.abs(n - asset.sizeM[i]) < Math.max(0.00001, n * 1e-6),
      `${asset.id} physical dimensions`,
    ),
  );
  assert(Math.abs(bounds.min.y) < 0.00001, `${asset.id} ground origin`);
}
let maxTriangles = 0,
  maxObjects = 0;
for (const total of [
  0,
  1 / 120000,
  0.5,
  1,
  149.5,
  150,
  150.5,
  9600,
  9600.5,
  8333 + 1 / 3,
  8333333 + 1 / 3,
]) {
  const layout = new m.CollectionLayout(total, 150);
  assert.equal(layout.count, Math.ceil(total / 150));
  const spans = [];
  layout.sections((start, side) =>
    spans.push([start, Math.min(layout.count, start + side * side * 64)]),
  );
  spans.sort((a, b) => a[0] - b[0]);
  let cursor = 0;
  for (const [start, end] of spans) {
    assert.equal(start, cursor);
    cursor = end;
  }
  assert.equal(cursor, layout.count);
  const bigger = new m.CollectionLayout(total + 1e6, 150);
  for (const index of [0, Math.max(0, layout.count - 1)])
    assert.deepEqual(
      layout.position(index),
      bigger.position(index),
      "Growth preserves physical shelf positions",
    );
}
assert.equal(new m.CollectionLayout((1e12 * 0.75) / 90000, 150).count, 55556);
assert(Math.abs(m.readingElapsed(5e6, "30") / 525960 - 456.308464522) < 1e-8);
assert.equal(m.readingElapsed(60, "60"), 1440);
assert.equal(m.trailMode(m.EARTH_CIRCUIT_M / 4 - 1, "auto"), "unrolled");
assert.equal(m.trailMode(m.EARTH_CIRCUIT_M / 4, "auto"), "globe");
assert.equal(
  m.restoreWorldOptions('{"readingSchedule":"30"}').readingSchedule,
  "30",
);
for (const tokens of [0, 1, 2001, 180000, 540000, 86400000, 1e9, 1e12])
  for (const world of m.WORLDS) {
    const s = snapshot(tokens),
      options = { ...m.DEFAULT_OPTIONS, world: world.id };
    const scene = m.factories[world.id](s, options, assets);
    for (const presetName of ["fit", "inspect", "middle", "last"]) {
      if (presetName === "last")
        scene.select?.((scene.inspection?.().count ?? 1) - 1);
      if (presetName === "middle")
        scene.select?.(Math.floor((scene.inspection?.().count ?? 1) / 2));
      const preset =
        scene.presets[presetName === "middle" ? "inspect" : presetName] ??
        scene.presets.fit;
      const camera =
        preset.projection === "orthographic"
          ? new m.OrthographicCamera()
          : new m.PerspectiveCamera(38);
      const fit = m.fitCamera(camera, preset, 1100 / 436);
      scene.updateView?.({
        camera,
        target: fit.target,
        width: 1100,
        height: 436,
      });
      const info = scene.root.userData.collection;
      if (info) {
        if (
          world.id === "library" &&
          ["inspect", "middle", "last"].includes(presetName) &&
          s.values.novels >= 1
        )
          assert(
            info.detailedProps > 0,
            "Any selected section reveals individual books",
          );
        assert(info.detailedProps <= 2048);
        const spans = [...info.ranges].sort((a, b) => a[0] - b[0]);
        let end = 0;
        for (const span of spans) {
          assert(span[0] >= end);
          assert(span[1] <= info.total);
          end = span[1];
        }
        if (presetName === "fit")
          assert(
            Math.abs(spans.reduce((n, [a, b]) => n + b - a, 0) - info.total) <
              Math.max(1e-6, info.total * 1e-12),
            "Whole view represents every equivalent exactly once",
          );
      }
      if (world.id === "paper")
        for (const width of [320, 1100]) {
          const annotations = m.layoutAnnotations(
            scene.labels,
            scene.protectedBounds ?? [],
            camera,
            width,
            436,
            (text) => text.length * 7,
          );
          const height = annotations.labels.find(
            (l) => l.id === "stack-height",
          );
          assert(height, "Critical stack height always available");
          if (!height.docked)
            assert(
              !annotations.protected.some((r) => m.intersects(height, r)),
              "Height label avoids stack silhouette",
            );
        }
      let triangles = 0,
        objects = 0;
      scene.root.traverse((object) => {
        objects++;
        if (object.isMesh)
          triangles +=
            ((object.geometry.index?.count ??
              object.geometry.attributes.position.count) /
              3) *
            (object.isInstancedMesh ? object.count : 1);
      });
      maxTriangles = Math.max(maxTriangles, triangles);
      maxObjects = Math.max(maxObjects, objects);
      assert(objects < 80, `${world.id} bounded objects`);
      assert(triangles < 250000, `${world.id} bounded triangles: ${triangles}`);
      assert(
        scene.bounds.min
          .toArray()
          .concat(scene.bounds.max.toArray())
          .every(Number.isFinite),
      );
    }
    scene.dispose();
    assert.equal(scene.root.children.length, 0);
  }
assets.dispose();
await assert.rejects(assets.get("person"), /closed/);
console.log(
  `Token Worlds data/assets passed: 0–1T, coverage, ratios, fractions, ${manifest.assets.length} verified GLBs (${bytes} bytes); max ${maxObjects} objects / ${maxTriangles} triangles.`,
);
