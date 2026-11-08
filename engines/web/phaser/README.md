# Phaser action-set game

This is a real Phaser 3 Scene, WebGL where available with Phaser's Canvas fallback.
It makes the admitted action-set atlas playable as **Scout · Training clearing**:
move, face the amber target, strike three times, finish, restart. Arrow keys/A/D,
Space/R and large pointer controls are available. Clicking or activating Left/Right with
the keyboard nudges the actor 32 pixels; holding a pointer moves continuously. The sample authors its own
training layout; it does not import a 3D Studio scene or claim to convert GLBs.

`ActionActor` in `game.mjs` consumes action-set v1 metadata: individual atlas
rectangles, exact frame durations, looping/non-looping actions, actor pivots,
event time, contact anchor and effect anchor. The example requires one actor
with idle/walk/attack and one non-looping attack contact event; it does not
synthesize missing art. Export rejects incompatible data, drift and missing
SSOT pins before publishing. The supplied scout's event is at 320ms. Like any
render loop, a threshold is displayed on the first rendered frame at or after
that timestamp; this is not a sub-frame hardware timing guarantee.

## Explicit dependency setup

Phaser **3.90.0** is deliberately pinned to its stable Phaser 3 API. Phaser 4 is
a separate version line, not silently selected by this adapter.

From this directory, explicitly install the lockfile before exporting:

```sh
npm ci --ignore-scripts --no-audit --no-fund
```

That setup downloads npm packages. Export never installs or downloads anything.
For offline export, prepare this installation in advance and copy/cache both
`phaser` and its sibling `eventemitter3` packages; `npm ci --offline
--ignore-scripts --no-audit --no-fund` works only with an already populated npm
cache. `--phaser-package /prepared/node_modules/phaser` selects an installation.
Both the version and the runtime/license bytes must match `runtime-lock.json`.
Do not commit `node_modules` or the minified runtime.

From the workspace root:

```sh
python3 studio/engines/web/phaser/export.py \
  --project examples/scout-actions \
  --runtime builds/attack-contact/scene.runtime.json \
  --output /tmp/scout-phaser
python3 -m http.server 8937 --bind 127.0.0.1 --directory /tmp/scout-phaser
```

Open `http://127.0.0.1:8937`. The exported directory is portable and self-hosted:
Phaser, actor atlas, effect PNG/metadata, credits, licenses and provenance are
local. Serve via HTTP; browser module loading does not support opening this
bundle via `file:`. No CDN, cloud API, upload or runtime install is used.

The shared `studio/tools/runtime_inputs.py` admits successful graph-pinned
runtime products, checks path containment and content hashes, copies verified
bytes, and publishes to a fresh destination atomically. `game.json` preserves
the RuntimeProduct pin; `provenance.json` preserves Artifact IDs and hashes.
Phaser and embedded EventEmitter3 notices are included in `vendor/`;
`PHASER-BUNDLED-NOTICES.txt` also preserves the original third-party copyright
and license comments from the hash-pinned official unminified distribution and
the Matter.js license source. The multi-megabyte unminified library is used only
at export time and is not shipped in the bundle; pixelfx
license and NOTICE remain beside the effect and are linked in the credits.

Official provenance:

- [Phaser 3.90.0 release](https://phaser.io/download/release/v3.90.0)
- [Phaser MIT license](https://phaser.io/download/license)
- [Official npm tarball](https://registry.npmjs.org/phaser/-/phaser-3.90.0.tgz)

Validation:

```sh
python3 -m unittest discover -s studio/engines/web/phaser -p 'test_*.py' -v
node studio/engines/web/phaser/test_timing.mjs
node --check studio/engines/web/phaser/game.mjs
```

`evidence/browser.json` records the observed Stagehand gameplay, local resource
requests and responsive inspection. This miniature demonstrates engine support;
it is not a full game-content pipeline, audio implementation or hardware/mobile
certification.
