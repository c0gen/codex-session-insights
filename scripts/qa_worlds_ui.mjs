import assert from "node:assert/strict";
import {
  chromium,
  expect,
} from "../frontend/node_modules/@playwright/test/index.mjs";
import { mkdir, writeFile, readFile } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { metricFixture } from "./metric-interface-fixture.mjs";
import { coverageFixture } from "./dashboard-fixture.mjs";
import { uiTestServer } from "./ui-test-server.mjs";

const output = ".local-data/token-worlds-qa";
await mkdir(output, { recursive: true });
const server = await uiTestServer();
const browser = await chromium.launch({
  headless: true,
  channel: process.env.PLAYWRIGHT_CHANNEL || "msedge",
});
const worlds = ["paper", "library", "trail", "reading", "vault"];
const fixture = metricFixture();
fixture.demo = false;
fixture.summary.total_tokens = 86400000;
fixture.summary.output_tokens = 540000;
fixture.settings.device_label = "PRIVATE_DEVICE";
fixture.sources[0].label = "PRIVATE_SOURCE";
fixture.indexed_token_totals = {
  codex: { total_tokens: 100, state: "complete", sessions: 1 },
};
let total = {
  total_tokens: 1e9,
  accounts: 1,
  reported_accounts: 1,
  identity_complete: true,
  stale: false,
};
let errors = [],
  network = [],
  stats = [],
  libraryFps;
const ready = async (page, world) => {
  await expect(page.locator("#world-viewport")).toHaveAttribute(
    "data-world",
    world,
    { timeout: 15000 },
  );
  await expect(page.locator("#world-viewport")).toHaveAttribute(
    "data-ready",
    "true",
  );
  await expect(page.locator("#world-copy")).toBeEnabled();
  await page.locator("#world-canvas").scrollIntoViewIfNeeded();
  await page.evaluate(
    () =>
      new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r))),
  );
};
async function clearStackTop(page) {
  const layout = JSON.parse(
    await page.locator("#world-viewport").getAttribute("data-annotations"),
  );
  const l = layout.labels.find((l) => l.id === "stack-height");
  assert(l, "Stack height must remain available");
  if (!l.docked)
    for (const r of layout.protected)
      assert(
        !(
          l.x < r.x + r.w &&
          l.x + l.w > r.x &&
          l.y < r.y + r.h &&
          l.y + l.h > r.y
        ),
        "Height label covers the stack",
      );
  return l;
}
async function interactionPerformance(page) {
  return page.evaluate(async () => {
    const canvas = document.querySelector("#world-canvas"),
      times = [];
    let previous = performance.now();
    for (let i = 0; i < 60; i++) {
      canvas.dispatchEvent(
        new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }),
      );
      await new Promise(requestAnimationFrame);
      const now = performance.now();
      times.push(now - previous);
      previous = now;
    }
    times.sort((a, b) => a - b);
    return { medianFps: 1000 / times[30], p95FrameMs: times[57] };
  });
}
try {
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1100 },
    reducedMotion: "reduce",
    acceptDownloads: true,
  });
  await context.addInitScript(() => {
    window.__worldCopies = [];
    window.__worldCopyFail = false;
    window.__worldTexts = [];
    const fill = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function (text, ...args) {
      if (this.canvas.width === 1200 && this.canvas.height === 720)
        window.__worldTexts.push(text);
      return fill.call(this, text, ...args);
    };
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        write: async (items) => {
          const blob = await items[0].getType("image/png");
          const bytes = new Uint8Array(await blob.arrayBuffer());
          window.__worldCopies.push(Array.from(bytes));
          if (window.__worldCopyFail) throw Error("Test clipboard failure");
        },
      },
    });
    window.__worldContexts = [];
    window.__gpuCalls = 0;
    const get = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (kind, ...args) {
      const value = get.call(this, kind, ...args);
      if (kind === "webgl2" && value && !window.__worldContexts.includes(value))
        window.__worldContexts.push(value);
      return value;
    };
    for (const name of [
      "drawElements",
      "drawElementsInstanced",
      "drawArrays",
    ]) {
      const draw = WebGL2RenderingContext.prototype[name];
      WebGL2RenderingContext.prototype[name] = function (...args) {
        window.__gpuCalls++;
        return draw.apply(this, args);
      };
    }
  });
  const page = await context.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (
      m.type() === "error" &&
      /Shader Error|VALIDATE_STATUS|WebGLProgram/i.test(m.text())
    )
      errors.push(m.text());
  });
  page.on("request", (r) => {
    if (!r.url().startsWith(server.url)) network.push(r.url());
  });
  await page.route("**/api/*", async (route) => {
    const name = route.request().url().split("/").pop();
    const args = route.request().postDataJSON();
    let value = {};
    if (name === "dashboard")
      value = { ...fixture, filters: args, account_token_total: total };
    if (name === "accounts")
      value = {
        accounts: [],
        login: { status: "idle" },
        allowed: false,
        enabled: true,
        token_total: total,
      };
    if (name === "provider_allowances") value = [];
    if (name === "status")
      value = { ...fixture.job, revision: fixture.revision };
    if (name === 'live_status') value = {ready: true, job: {...fixture.job, revision: fixture.revision}, desktop: {available: false},
      provider_allowances: [], account_token_total: total,
      usage_limits: {allowed: false, enabled: false, buckets: [], status: 'disabled', stale: false, refreshing: false, last_success_at: null}};
    await route.fulfill({ json: value });
  });
  await page.goto(server.url);
  await page.getByRole("button", { name: "Explore in 3D" }).click();
  await ready(page, "paper");
  await expect(page.locator("#world-value")).toHaveText("500 ft");
  await expect(page.locator("#world-note")).toContainText("width enlarged ×");
  await expect(page.locator("#filter-provider")).toHaveCount(0);
  await page.locator("#world-canvas").focus();
  await page.keyboard.press("ArrowLeft");
  await page.waitForTimeout(100);
  const landmark = page
    .locator(".world-labels span")
    .filter({ hasText: "Eiffel Tower" });
  const position = await landmark.getAttribute("style");
  total = { ...total, total_tokens: 1.1e9 };
  await expect(page.locator("#world-counter")).toContainText(
    "1,100,000,000 tokens",
    { timeout: 6000 },
  );
  await ready(page, "paper");
  assert.equal(
    await landmark.getAttribute("style"),
    position,
    "Live updates preserve camera",
  );
  assert.equal(
    await page.evaluate(() => document.activeElement?.id),
    "world-canvas",
  );
  await page.locator("#world-proportions").selectOption("true");
  await ready(page, "paper");
  await expect(page.locator("#world-note")).toContainText(
    "True sheet proportions",
  );
  await page.locator("#world-proportions").selectOption("readable");
  await page.locator("#world-units").selectOption("metric");
  await ready(page, "paper");
  await expect(page.locator("#world-value")).toHaveText("167.64 m");
  for (const reference of [
    "person",
    "house",
    "burj",
    "everest",
    "earth",
    "auto",
  ]) {
    await page.locator("#world-reference").selectOption(reference);
    await ready(page, "paper");
    await page.locator("#world-fit").click();
  }
  // Exactly one context throughout exhibit changes; warm caches remain bounded.
  await page.locator("#world-compare").click();
  await ready(page, "paper");
  assert.equal(
    JSON.parse(
      await page.locator("#world-viewport").getAttribute("data-camera"),
    ).projection,
    "orthographic",
  );
  for (const preset of ["fit", "top", "ground", "compare"]) {
    await page.locator(`#world-${preset}`).click();
    await ready(page, "paper");
    for (let i = 0; i < 12; i++) {
      await clearStackTop(page);
      for (let j = 0; j < 5; j++)
        await page.locator("#world-canvas").press("ArrowRight");
      await ready(page, "paper");
    }
  }
  await page.locator("#world-compare").click();
  await ready(page, "paper");
  for (let pass = 0; pass < 3; pass++)
    for (const world of worlds) {
      await page.locator(`button[data-world="${world}"]`).click();
      await ready(page, world);
      const info = await page
        .locator("#world-viewport")
        .evaluate((el) => ({ ...el.dataset }));
      assert(Number(info.triangles) < 250000);
      assert(Number(info.drawCalls) < 100);
      assert(Number(info.geometries) < 80);
      if (pass === 0) {
        stats.push(info);
        await page
          .locator(".world-exhibit")
          .screenshot({ path: `${output}/${world}.png` });
      }
      if (pass === 2)
        assert(
          Number(info.geometries) <= 80,
          "No accumulation after repeated changes",
        );
    }
  assert.equal(await page.evaluate(() => window.__worldContexts.length), 1);
  await page.locator('[data-world="library"]').click();
  await ready(page, "library");
  await expect(page.locator("#world-collection-summary")).toContainText(
    "62 occupied bookcases",
  );
  await page.locator("#world-container").fill("2");
  await page.locator("#world-container").press("Enter");
  await ready(page, "library");
  await expect(page.locator("#world-selection")).toContainText("Books 151–300");
  await page.locator("#world-last").click();
  await ready(page, "library");
  await expect(page.locator("#world-selection")).toContainText("66.67% filled");
  await page
    .locator(".world-exhibit")
    .screenshot({ path: `${output}/library-last.png` });
  assert(
    JSON.parse(
      await page.locator("#world-viewport").getAttribute("data-collection"),
    ).detailedProps > 0,
  );
  await page.locator("#world-inspect").click();
  await ready(page, "library");
  await page
    .locator(".world-exhibit")
    .screenshot({ path: `${output}/library-aisle.png` });
  await page.locator('[data-world="reading"]').click();
  await ready(page, "reading");
  await page.locator("#world-schedule").selectOption("30");
  await ready(page, "reading");
  await expect(page.locator("#world-value")).toHaveText("501.94 years");
  await expect(page.locator("#world-note")).toContainText(
    "10.46 years continuously",
  );
  await expect(page.locator("#world-units")).toBeHidden();
  await page
    .locator(".world-exhibit")
    .screenshot({ path: `${output}/reading-daily.png` });
  await page.locator("#world-schedule").selectOption("60");
  await ready(page, "reading");
  await expect(page.locator("#world-value")).toHaveText("250.97 years");
  await page.locator('[data-world="trail"]').click();
  await ready(page, "trail");
  await page.locator("#world-trail").selectOption("globe");
  await ready(page, "trail");
  await page.locator("#world-route").click();
  await ready(page, "trail");
  await expect(page.locator("#world-overview svg")).toBeVisible();
  await page
    .locator(".world-exhibit")
    .screenshot({ path: `${output}/trail-close.png` });
  await page.locator('[data-world="vault"]').click();
  await ready(page, "vault");
  await page.locator("#world-last").click();
  await ready(page, "vault");
  await expect(page.locator("#world-selection")).toContainText("55.56% filled");
  await page
    .locator(".world-exhibit")
    .screenshot({ path: `${output}/vault-last.png` });
  assert(
    JSON.parse(
      await page.locator("#world-viewport").getAttribute("data-collection"),
    ).detailedProps > 0,
  );
  const calls = await page.evaluate(() => window.__gpuCalls);
  await page.waitForTimeout(300);
  assert.equal(
    await page.evaluate(() => window.__gpuCalls),
    calls,
    "Idle scenes do not render",
  );
  await page.locator("#world-basis-output").click();
  await ready(page, "vault");
  await expect(page.locator("#world-counter")).toContainText("540,000 tokens");
  await expect(page.locator("#filter-provider")).toBeVisible();
  await expect(page.locator("#world-selection")).toContainText("Case 1 of 1");
  assert(
    JSON.parse(
      await page.locator("#world-viewport").getAttribute("data-collection"),
    ).detailedProps === 2,
    "Removing an inspected container reframes the remaining two disks",
  );
  await page.locator("#filter-provider").selectOption("claude_code");
  await ready(page, "vault");
  await expect(page.locator("#world-basis-output")).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  await page.locator("#world-copy").click();
  await expect
    .poll(() => page.evaluate(() => window.__worldCopies.length))
    .toBe(1);
  const bytes = Buffer.from(await page.evaluate(() => window.__worldCopies[0]));
  assert.equal(bytes.readUInt32BE(16), 1200);
  assert.equal(bytes.readUInt32BE(20), 720);
  assert(bytes.length < 2 * 1024 * 1024);
  await writeFile(`${output}/capture.png`, bytes);
  const words = await page.evaluate(() => window.__worldTexts.join(" "));
  assert.match(words, /540,000 tokens.*Output only/);
  assert.match(words, /Metric units/);
  assert.match(words, /2026-03-07 to 2026-03-10/);
  assert.match(words, /partial capacity/);
  assert.doesNotMatch(words, /PRIVATE_DEVICE|PRIVATE_SOURCE|PRIVATE_ACCOUNT/);
  await page.evaluate(() => {
    window.__worldCopyFail = true;
  });
  await page.locator("#world-copy").click();
  await expect(page.locator("#world-share-feedback")).toContainText(
    "try Save PNG",
  );
  const download = page.waitForEvent("download");
  await page.locator("#world-save").click();
  await (await download).saveAs(`${output}/saved.png`);
  assert.equal((await readFile(`${output}/saved.png`)).length, bytes.length);
  await page.locator("#world-copy").click();
  await expect(page.locator("#world-share-feedback")).toContainText(
    "try Save PNG",
  );
  await page.locator("#world-canvas").press("ArrowRight");
  await ready(page, "vault");
  const changedDownload = page.waitForEvent("download");
  await page.locator("#world-save").click();
  await (await changedDownload).saveAs(`${output}/changed-camera.png`);
  assert(
    !(await readFile(`${output}/changed-camera.png`)).equals(bytes),
    "Camera changes invalidate a failed clipboard image",
  );
  await page.locator("#world-basis-total").click();
  await ready(page, "vault");
  total = { ...total, total_tokens: 1e12 };
  await expect(page.locator("#world-counter")).toContainText(
    "1,000,000,000,000 tokens",
    { timeout: 6000 },
  );
  for (const world of worlds) {
    await page.locator(`button[data-world="${world}"]`).click();
    await ready(page, world);
    await page.locator("#world-fit").click();
    await ready(page, world);
    if (world === "library") {
      await expect(page.locator("#world-collection-summary")).toContainText(
        "55,556 occupied bookcases",
      );
      await page
        .locator(".world-exhibit")
        .screenshot({ path: `${output}/library-trillion.png` });
      const info = JSON.parse(
        await page.locator("#world-viewport").getAttribute("data-collection"),
      );
      const represented = info.ranges.reduce((sum, [a, b]) => sum + b - a, 0);
      assert(Math.abs(represented - (1e12 * 0.75) / 90000) < 0.001);
      await page.locator("#world-last").click();
      await ready(page, world);
      await expect(page.locator("#world-selection")).toContainText(
        "33.33% filled",
      );
      await page.locator("#world-container").fill("27778");
      await page.locator("#world-container").press("Enter");
      await ready(page, world);
      const detail = JSON.parse(
        await page.locator("#world-viewport").getAttribute("data-collection"),
      );
      assert(detail.detailedProps > 0 && detail.detailedProps <= 2048);
      assert(
        Number(
          await page.locator("#world-viewport").getAttribute("data-triangles"),
        ) < 250000,
      );
      libraryFps = await interactionPerformance(page);
      assert(
        libraryFps.medianFps >= 30,
        "Dense library interaction must sustain at least 30 fps",
      );
    }
  }
  const fps = await interactionPerformance(page);
  assert(fps.medianFps >= 30, "Interaction should sustain at least 30 fps");
  await page.setViewportSize({ width: 540, height: 900 });
  await page.locator('button[data-world="paper"]').click();
  await ready(page, "paper");
  await page.locator("#world-fit").click();
  await ready(page, "paper");
  await clearStackTop(page);
  await page.locator("#world-proportions").selectOption("true");
  await ready(page, "paper");
  await clearStackTop(page);
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  );
  await page
    .locator(".world-exhibit")
    .screenshot({ path: `${output}/narrow.png` });
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Overview", exact: true })
    .click();
  assert.equal(
    await page.evaluate(
      () => window.__worldContexts.filter((c) => !c.isContextLost()).length,
    ),
    0,
  );
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Visualizations", exact: true })
    .click();
  await ready(page, "paper");
  await expect(page.locator("#world-units")).toHaveValue("metric");
  await expect(page.locator("#world-schedule")).toHaveValue("60");
  await page.evaluate(() =>
    document
      .querySelector("#world-canvas")
      .getContext("webgl2")
      .getExtension("WEBGL_lose_context")
      .loseContext(),
  );
  await expect(page.locator("#world-fallback svg")).toBeVisible();
  await expect(page.locator("#world-counter")).toContainText(
    "1,000,000,000,000",
  );
  await page.locator("#world-retry").click();
  await ready(page, "paper");
  assert.equal(
    await page.evaluate(
      () => window.__worldContexts.filter((c) => !c.isContextLost()).length,
    ),
    1,
  );
  assert.deepEqual(network, []);
  // Saved reports are generated by the real Python exporter and opened through file:// offline.
  const exported = {
    ...fixture,
    account_token_total: { ...total, private: "PRIVATE_ACCOUNT" },
    accounts: ["PRIVATE_ACCOUNT"],
  };
  await writeFile(`${output}/fixture.json`, JSON.stringify(exported));
  const python =
    process.platform === "win32"
      ? ".venv/Scripts/python.exe"
      : ".venv/bin/python";
  execFileSync(python, [
    "-c",
    `import json; from pathlib import Path; from codex_insights.report import export_html; export_html(json.loads(Path('${output}/fixture.json').read_text(encoding='utf-8')), '${output}/report.html')`,
  ]);
  const html = await readFile(`${output}/report.html`, "utf8");
  assert(!html.includes("PRIVATE_ACCOUNT"));
  assert(!/<script[^>]+src=|<link[^>]+\.css/.test(html));
  await context.setOffline(true);
  const report = await context.newPage();
  const reportNetwork = [];
  report.on("pageerror", (e) => errors.push(e.message));
  report.on("request", (r) => {
    if (/^https?:/.test(r.url())) reportNetwork.push(r.url());
  });
  await report.goto(pathToFileURL(resolve(`${output}/report.html`)).href);
  await report
    .getByRole("navigation")
    .getByRole("button", { name: "Visualizations", exact: true })
    .click();
  for (const world of worlds) {
    await report.locator(`button[data-world="${world}"]`).click();
    await ready(report, world);
    if (world === "library" || world === "vault") {
      await report.locator("#world-last").click();
      await ready(report, world);
      await expect(report.locator("#world-selection")).toBeVisible();
    }
    if (world === "reading") {
      await report.locator("#world-schedule").selectOption("30");
      await ready(report, world);
    }
    if (world === "trail") {
      await report.locator("#world-trail").selectOption("globe");
      await ready(report, world);
      await report.locator("#world-route").click();
    }
    await expect(report.locator("#world-counter")).toContainText(
      "86,400,000 tokens",
    );
  }
  assert.deepEqual(reportNetwork, []);
  const broken = await context.newPage();
  // Exercise asynchronous model parsing failure independently of WebGL failure.
  const brokenHtml = html.replaceAll("Z2xURgIA", "QUJDRAIA");
  assert.notEqual(brokenHtml, html);
  await writeFile(`${output}/broken-assets.html`, brokenHtml);
  await broken.goto(
    pathToFileURL(resolve(`${output}/broken-assets.html`)).href,
  );
  await broken
    .getByRole("navigation")
    .getByRole("button", { name: "Visualizations", exact: true })
    .click();
  await expect(broken.locator("#world-fallback svg")).toBeVisible();
  await expect(broken.locator("#world-counter")).toContainText(
    "86,400,000 tokens",
  );
  await expect(broken.locator("#world-copy")).toBeEnabled();
  const fallback = await context.newPage();
  await fallback.addInitScript(() => {
    const get = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (kind, ...args) {
      return kind === "webgl2" ? null : get.call(this, kind, ...args);
    };
  });
  await fallback.goto(pathToFileURL(resolve(`${output}/report.html`)).href);
  await fallback
    .getByRole("navigation")
    .getByRole("button", { name: "Visualizations", exact: true })
    .click();
  for (const world of worlds) {
    await fallback.locator(`button[data-world="${world}"]`).click();
    await expect(fallback.locator("#world-fallback svg")).toBeVisible();
    await expect(fallback.locator("#world-copy")).toBeEnabled();
  }
  const fallbackDownload = fallback.waitForEvent("download");
  await fallback.locator("#world-save").click();
  await (await fallbackDownload).saveAs(`${output}/fallback.png`);
  await context.setOffline(false);
  fixture.demo = true;
  fixture.coverage = coverageFixture("unavailable");
  fixture.summary.total_tokens = 0;
  await page.reload();
  await page
    .getByRole("navigation")
    .getByRole("button", { name: "Visualizations", exact: true })
    .click();
  await expect(page.locator("#world-value")).toHaveText("Unavailable");
  await expect(page.locator("#world-copy")).toBeDisabled();
  assert.deepEqual(errors, []);
  await writeFile(
    `${output}/results.json`,
    JSON.stringify(
      {
        stats,
        fps,
        libraryFps,
        reportBytes: html.length,
        captureBytes: bytes.length,
      },
      null,
      2,
    ),
  );
  console.log(
    `Token Worlds UI/offline/PNG checks passed. Vault ${fps.medianFps.toFixed(1)} fps; dense library ${libraryFps.medianFps.toFixed(1)} fps. See ${output}.`,
  );
} finally {
  await browser.close();
  server.close();
}
