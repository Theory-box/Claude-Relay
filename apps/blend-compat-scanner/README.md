# blend-compat-scanner

Tells you **exactly what in a .blend file will break** when it moves to an older
Blender version — which node, in which object / material / graph, and what (if
anything) can be done about it.

Built for the round-trip pain: you work in 4.4/4.5, a client opens in 4.2, and
things silently break on their end. This finds them first.

## Status

Working and tested against local **4.4.3** and **4.2.23 LTS** builds. Diagnosis
is solid; automatic *repair* is intentionally not implemented yet (see below).

## Two modes (auto-detected)

| Mode | Run it in | Answers | Needs DB? |
|------|-----------|---------|-----------|
| **Predict** | the source version (4.4) | "what will break if I send this to 4.2" — exact node type + suggested action, before you downgrade | yes |
| **Detect** | the target version (4.2) | "what is broken in this file right now" — finds every `NodeUndefined` with its location | no |

Detect works because when an older Blender opens an unknown node, the node
collapses to `bl_idname == 'NodeUndefined'` but keeps its **name**, so it's
locatable even after the type is gone.

## Usage

```bash
# Predict (in the newer Blender), before handing the file over:
blender-4.4 -b myfile.blend --python blend_compat_scanner.py -- --target 4.2 --json report.json

# Detect (in the older Blender), on a file already opened there:
blender-4.2 -b myfile.blend --python blend_compat_scanner.py
```

It walks geometry-nodes modifiers, materials, worlds, the compositor, and every
nested node group (cycle-safe), and in predict mode also checks non-node settings
(EEVEE / render) that would be lost. It **only reports** — nothing is edited or
deleted.

## What it found for 4.4 -> 4.2 (ground truth, from the binaries)

Nodes:
- **21 nodes** exist in 4.4 but not 4.2 → become `Undefined` (19 geometry/function, 2 shader).
- **7 nodes** exist in both but changed sockets → may silently shift to old defaults.

Non-node (settings + types, also enumerated from the binaries):
- **3 settings** exist in 4.4 but not 4.2 and are lost on downgrade: `SceneEEVEE.use_fast_gi`
  (Fast GI), `RenderSettings.compositor_denoise_final_quality` / `..._preview_quality`.
  The scanner only flags one when it is actually turned on in the file.
- **1 critical** non-node warning: Grease Pencil v3 (4.3+) files don't open in 4.2.
- **Confirmed stable (no break):** World / environment / HDRI settings are identical
  between 4.2 and 4.4, and there are **no new object / modifier / constraint / light-probe
  types** in 4.4. So for this pair the real risk is nodes + Grease Pencil v3, not world/render.

Known limitation: a property present in both versions but with a *changed default* would
shift silently and is not yet detected (would need a value-level, not existence-level, diff).

Each missing node is tagged with a suggested strategy:

| class | meaning | examples |
|-------|---------|----------|
| `safe-drop` | no effect on output; strip with a warning | Gizmo nodes, Warning, SetGeometryName |
| `reconstruct` | rebuildable from older nodes | Integer Math, Matrix Determinant, Object/Collection Input, Metallic BSDF |
| `bake` | realize result into stored geometry | Import OBJ/PLY/STL |
| `manual` | no clean equivalent — user decides | For-Each zone, Hash, Gabor texture, Grease Pencil conversions |

The node lists are **empirical** (enumerated from both binaries, not scraped
from release notes). The `class`/`action` tags are advisory judgement and are
individually verifiable by output-diffing a reconstruction against the original.

## Files

- `blend_compat_scanner.py` — the scanner (predict + detect).
- `compat_db_4.4_to_4.2.json` — the compatibility database for this version pair.
- `tools/gen_compat_db.py` — regenerate the DB for **any** two versions:

```bash
python3 tools/gen_compat_db.py \
  --source-blender /path/to/4.5/blender --source-label 4.5.0 \
  --target-blender /path/to/4.2/blender --target-label 4.2.23 \
  --out compat_db_4.5_to_4.2.json
```

## Deliberately not done yet

- **Auto-repair.** Diagnosis first; it's low-risk and is most of the value. Repair
  is a separate, per-node effort where a wrong fix silently corrupts, so each
  reconstruction must be verified before it ships.
- **The 5.x boundary.** 5.0 changed the low-level file format; 5.x files are
  simply *invalid* to < 4.5. That needs the LTS-bridge route (open in 4.5, save
  down), not a node fixer — out of scope for this tool.
- **A UI add-on.** A future in-Blender panel could jump-select each broken node.
  The engine here is headless-first so it can back either a CLI or an add-on.
