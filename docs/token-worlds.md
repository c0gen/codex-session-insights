# Token Worlds

Open **Visualizations** in the sidebar or **Explore in 3D** on Overview. Five exhibits turn the existing token equivalents into interactive scenes. Total processed uses the same all-time combined count as the headline; Output only follows applied dashboard filters. Saved reports use analyzed snapshot totals and contain no live account totals.

## Scale and interpretation

| Exhibit | Calculation | Display conventions |
| --- | --- | --- |
| Paper Tower | `ceil(tokens × .75 / 500)` sheets × `.0001016 m` | Single-sided, uncompressed US Letter. Height stays linear. Readable width shows its enlargement factor; True proportions retains physical width and depth with a thin outline and a separately magnified sheet inset. |
| Infinite Library | `tokens × .75 / 90000` novels | One detailed book per novel equivalent; 30 books per tier and five tiers per bookcase. Full-sized final book with gold fill and translucent remainder. Double-sided rows and aisles grow with the actual collection. |
| Paper Trail | Sheets × `.2794 m` | Unrolled distance diagram below one-quarter of Earth's circumference by default; globe above it. Both views remain selectable. Gold arc, direction marker, route close-up and globe overview preserve orientation. Ribbon width is illustrative. |
| Reading Journey | `tokens × .75 / 150` minutes | Continuous reading by default. At 30 or 60 minutes/day, elapsed minutes = reading minutes × 1440 / daily minutes. 365.25 days/year; labeled milestones and exact endpoint. Corridor distance is symbolic. |
| Floppy Vault | `tokens × 4 / 1440000` disks | Fixed assumed capacities: 100 disks/case and 20 cases/rack. Inspect a case to reveal individual disks; the final disk has a gold capacity bar and percentage. |

One billion tokens gives 1,500,000 sheets, 152.4 metres (500 feet) tall. The .75 words/token assumption is an English-text approximation. These are processed-volume equivalents, including cached and repeated context, not unique authored text. Disk bytes are an illustrative text encoding estimate, not measured storage.

One billion tokens also gives 8,333⅓ novels: 55 full bookcases and 83⅓ novels in the final case. One trillion gives 8,333,333⅓ novels in 55,556 bookcases. At one billion tokens, reading takes 9.51 years continuously or 456.31 years at 30 minutes/day. No hypothetical token slider or historical-growth reconstruction is used.

Books use the existing 3.3 × 22 × 15.15 cm model. Bookcases are 1.32 × 1.8 × 0.289 m, arranged in double-sided rows with approximately 1.24 m clear aisles. These are illustrative layout assumptions. Library and vault offer whole-collection and close-up presets, a selectable floor plan, previous/next container buttons, and numeric container navigation. Container indices and physical positions stay stable as totals increase.

Paper height callouts use measured text bounds, avoid the projected stack silhouette and top, and connect to the top edge with a leader. If no clear placement is available, the value moves into a reserved strip outside the drawing area. Fit stack frames only the stack; Compare landmark uses an orthographic front view; Top uses an angled close-up. Readable paper width is at least physical width and otherwise 6% of stack height, avoiding flattened stacks when the selected landmark is much taller. The exact enlargement factor remains disclosed.

Reference dimensions are kept in `frontend/src/worlds/references.ts`: [Eiffel Tower, including antenna, 330 m](https://www.toureiffel.paris/en/news/history-and-culture/300-330-meters-story-towers-height); [Burj Khalifa architectural height, 828 m](https://www.burjkhalifa.ae/img/FACT-SHEET.pdf); [Everest summit elevation, 8,848.86 m above sea level](https://science.nasa.gov/earth/earth-observatory/himalayas-near-and-far-147980/); and [spherical Earth mean radius, 6,371 km](https://science.nasa.gov/moon/by-the-numbers/). The person (1.75 m) and house (10 m) are assumptions. Terrain and reference placement are illustrative, not surveyed geography. Perspective and orbit change apparent screen sizes while world dimensions remain linear.

## Implementation

`frontend/src/worlds/` contains the calculation adapter, reference catalog, typed contracts, asset loader, camera fitting, shared annotation layout, collection layout and geometry, inspection UI, gallery controller, capture utility, static fallback and exhibit modules. `WorldScene` supports camera-dependent detail updates and inspectable containers; `SceneLabel` supports anchored callouts, required labels and protected geometry. `frontend/src/image-transport.ts` shares the existing native/browser PNG transport with summary images. No database, usage endpoint or transfer format changes are required.

The gallery creates one renderer on entry, reuses it across exhibits, retains its actual canvas through dashboard redraws, and releases the context, observers, meshes and asset cache on exit. Scene loads are generation-guarded. Camera, selection and focus survive updates; each exhibit retains its camera while switching. Exhibit, units, proportions and reading schedule use optional local storage. Saved reports start on Paper Tower.

If applying a smaller scope removes the inspected container, selection clamps to the last remaining container and the camera reframes it. Otherwise the current camera remains untouched. Empty collections receive an empty overview.

Rendering happens only on data, camera or size changes. Hidden/offscreen scenes stop scheduling work. There is no automatic motion or damping; reduced-motion users receive the same immediate controls. Pixel ratio is capped at two. A stable spatial hierarchy calculates occupied ranges and bounds without allocating every book or disk. Nearby books use GLB instances; farther tiers use counted spine patterns; distant sections use the same physical shelf/aisle footprint. Frustum culling and bounded detail keep detailed props below 2,048 and active geometry below 250,000 triangles. Selected sections remain inspectable at every scale. Model prototypes remain cached only for the current gallery visit.

Orbit by dragging, zoom by scrolling or buttons, and pan with Shift + drag. On the focused canvas, arrows orbit, Shift + arrows pan, plus/minus zoom and Home fits the exhibit. Paper also has Ground, Top and landmark presets. Graphics initialization, model parsing and context-loss failures switch to calculated SVG and accessible text, with Retry 3D available.

Copy exhibit / Save PNG captures the current view at 1200 × 720, under 2 MiB, with token total, basis, units, coverage qualifiers, privacy-safe filter/date scope and scale disclosures. Annotation geometry and measured line breaks are shared with the interactive view. Collection floor plans or the globe overview are included when relevant. Account identities, source paths and project/model names are omitted. Clipboard failure retains the generated image for Save PNG only while its data, options, selection and camera match the view.

## AI Design sources and delivery

Authoring project: `G:\AI Design\projects\three_d\projects\token-worlds`.

- `source/build.py` and `source/geometry.py` reproduce fourteen measured props in Blender. `source/asset.blend` is the editable review board; the build script exports individual props at physical scale before arranging the board.
- Each GLB uses metres, +Y up, applied transforms, a ground-centre origin and named `<asset>-anchor-ground` / `<asset>-anchor-top` nodes. Materials are embedded colors; no images or decoder dependencies are required.
- The runtime pack is **300,500 bytes** before embedding. Repeated props stay below 2,000 triangles and landmarks below 20,000. The largest landmark has 1,824 triangles. Small authored geometry and material merging avoid the need for an external compression decoder.
- `frontend/src/worlds/assets/manifest.json` records dimensions, bounds, triangle/byte counts, SHA-256, source revision, artifact IDs, provenance, review views and validation/bundle evidence. Only runtime GLBs and this manifest are copied into the frontend.
- Final build/render/export/validation job: `30ab5c84da11480c941ade95a279c499`. Validation artifact: `1a06b951eeca8c8967e832aec9540b7a`. Source revision: `d5a15375a5eb77b522a8df28dffb198230dcca0325c633447a84f61af7dc0e02`.
- Digital package job: `ff52f026c401474c9b7d516b496df284`. Package: `G:\AI Design\.local\runs\ff52f026c401474c9b7d516b496df284\operation\token-worlds-runtime-v2.zip`. Package SHA-256: `99c47a52d6a8c33eabdee64f6508945ef97aa9ce19b20791dac9d3751d9ed7c5`.

Front, side, three-quarter, clay and textured views were inspected and accepted separately from technical validation. Orthographic kit views overlap some props; the three-quarter view resolves them. The models intentionally use simplified recognizable silhouettes. Previous run directories retain earlier revisions and diagnostics.

For changes, use AI Design discovery/readiness and its project workflow: build → render → export → validate → explicit visual review → digital package. Use new request keys for changed inputs, preserve run IDs, and reconcile uncertain jobs before resubmitting. Copy only reviewed final models into the frontend, update the manifest with current artifact/hash evidence, and rerun the checks below. Do not modify registered run artifacts in place.

## Offline behavior and verification

Vite imports GLBs with `?url&inline`; the loader parses embedded bytes only when an exhibit needs them. The existing HTML exporter embeds the one JS entry and CSS, preserving analyzed-snapshot semantics. There are no dynamic chunks, CDN scripts, model downloads or texture requests. The widget remains a separate build and does not import Three.js.

Run from `desktop-app`:

```powershell
node scripts/qa_worlds_data.mjs
npm run build --prefix frontend
node scripts/qa_worlds_ui.mjs
```

`qa_worlds_data` is also part of `scripts/check.ps1`. It covers zero through one trillion tokens, sheet boundaries, partial books/disks, nonzero tiny values, invalid values, coverage/fallback states, physical landmark ratios, imported bounds, attachment nodes, artifact hashes, external-dependency rejection and geometry budgets.

`qa_worlds_ui` uses synthetic fixtures and the production build. It checks navigation, live totals, output filters, camera/focus preservation, keyboard use, unit/proportion preferences, bounded cached geometry, idle rendering, context disposal, reduced motion, narrow layout, PNG metadata/privacy/dimensions, clipboard failure and saving. It opens a real Python-exported HTML report through `file://` with networking disabled, exercises all five scenes, and tests both unavailable WebGL and corrupted embedded models. Evidence is saved under `.local-data/token-worlds-qa/`.

Validation of the collection/clarity pass on 2026-10-20: **559 Python tests passed**, existing frontend data suites passed, dashboard UI and summary-image/native-bridge regression suites passed, and both frontend/widget production builds passed. The expanded checks cover exact collection partitions, full and fractional containers, stable positions, all-round paper-label placement, daily schedules, close-up selection and trillion-token totals. Local Windows Edge performance and geometry measurements are saved in `.local-data/token-worlds-qa/results.json`; these are browser measurements, not a packaged WebView2 benchmark. Native packaged Windows and Mac binaries were not rebuilt.

The single app JS bundle is about 1.37 MB (342 KB gzip); Vite's default 500 KB chunk advisory is expected because standalone reports require embedded code and assets. Report text/controls/SVG remain available on browsers without WebGL2. This pass reuses the fourteen validated AI Design models without changing their bytes or provenance.

The final acceptance run measured approximately **102 fps** in the dense library (21.5 ms p95 frame interval) and **167 fps** in the vault. The largest calculation/rendering fixture used **176,448 triangles and 22 scene objects**, below the 250,000-triangle budget. The synthetic offline report is approximately 1.42 MB; the captured PNG is 110,539 bytes at 1200 × 720. PNGs, overview/aisle/partial-item screenshots, a trillion-token library view and a narrow true-proportion paper view were visually reviewed.
