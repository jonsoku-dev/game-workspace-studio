# Offline native Web 3D export

Woods Alight is a playable web sample, separate from the read-only Studio visualizer.
Move through a small forest, collect three crystals, and approach the lantern to
restore it with three attacks. The imported lantern GLB is the goal. Its authored
mesh-particle GLB and recipe supply the rising embers after restoration begins.
The player and environment are native Three.js meshes. No 2D billboard effect is
substituted for the 3D particles; sprite action games belong to `phaser/`.

From the workspace root:

```sh
python3 studio/engines/web/export.py \
  --source examples/forest-camp builds/lantern-embers-final/scene.runtime.json \
  --output /tmp/woods-alight
python3 -m http.server 8765 --bind 127.0.0.1 --directory /tmp/woods-alight
```

Open `http://127.0.0.1:8765`. Use WASD or arrows, Space to attack, R to restart.
The labelled direction buttons support pointer holds and keyboard activation;
Restore, Restart and Pause / Resume are ordinary accessible buttons.
Feel switches between baseline (A) and enhanced feedback (B); Sound is a separate,
explicit opt-in and starts off. Enhanced feedback uses distance-throttled steps,
local light/color confirmations and a fixed pool of real 3D crystal shards for
collection, restoration and the final celebration. Rejected restoration is throttled.
Reduced-motion preferences remove crystal bobbing and shard spin, shorten bursts
and hold the authored ember recipe at a still pose. Pause freezes world animation.
Progress and goals use a live status region. `file://` is unsupported because ES modules and GLB fetches
require an HTTP origin. A local HTTP server suffices; no API or internet is used.
WebGL2 is required. There is no install or package download in the exporter.

The exporter admits source artifacts through `studio/tools/runtime_inputs.py`.
The runtime must have a matching successful SSOT graph pin, and linked artifacts
(including reused original artifacts) must still match their digests and sizes.
It rejects escaping paths, external GLB resources, invalid particle parameters,
and missing or changed Three.js modules. A temporary sibling directory is
published atomically without replacing any existing output. Failure leaves no
partial output directory. Source/runtime files are never modified.

Only mesh runtime assets and their validation/receipt/credits are exported here.
Other asset kinds are admitted but omitted from this 3D sample. The forest's
relative hierarchy and particle recipe are retained; a 5× display scale and
translation place the lantern at the game's goal. The sample's game rules are
new adapter behavior, not a claim that its input observation-only scene was
already a game. It requires both a non-effect model and a mesh-particle asset.
Exactly one qualifying scene is required. Its single static model must be a
ground-level root with unit scale and Y rotation only; mesh effects must attach
directly to it. Effect-only or sprite scenes and unplaced assets are omitted;
multiple qualifying scenes are rejected. This is a bounded sample adapter, not
an arbitrary Studio game compiler.

Three.js 0.187.0 is loaded from the enabled installed model-assets plugin (or `MODEL_ASSETS_ROOT`) by
default; `--three PATH` may select another copy matching `three-lock.json`.
The lock covers exactly the ES module renderer/core, real GLTFLoader, its two
utility imports, the bundled Meshopt WASM decoder module, and the unchanged MIT
LICENSE. `MESHOPT-LICENSE.txt` preserves the decoder notice and MIT terms.
GLTFLoader uses this local decoder for required `EXT_meshopt_compression` GLBs;
the decoder embeds its WASM bytes and makes no remote request. No dependency tree, unrelated
source assets, Blender source, previews, or raw duplicate GLB is distributed.
`manifest.json` hashes every exported file except itself; `provenance.json`
retains original artifact URNs and source digests without local absolute paths.

Validation:

```sh
python3 -m unittest discover -s studio/engines/web -p test_export.py -v
node studio/engines/web/test-game.mjs
node --check studio/engines/web/game.mjs
```

`evidence/browser.json` records the actual Stagehand browser exercise and its
limits. `window.woodsAlight()` returns read-only render/game telemetry; it does
not expose mutation or bypass controls. Local telemetry is not a security or
anti-cheat boundary. No save persistence, enemies or physics collision system is
included in this sample.
Audio is synthesized locally through the shared feedback module, with no media
files or network requests. Read-only telemetry includes feedback mode, reduced
motion, semantic cue counts and active shard count for browser verification.

The genuine required-extension compression probe is documented in
`evidence/meshopt.json`, with the inspected render in `meshopt-probe.jpg`.
It loaded the local compressed fixture with the exported decoder and rendered
54 meshes / 46,320 triangles. This separate probe is not a claim of a new
SSOT-pinned compressed game runtime.
