# AI Onboarding — OpenGOAL Modding Environment

This document gets a fresh AI instance up and running on the OpenGOAL modding
toolchain as fast as possible. Read this first before anything else.

---

## What This Project Is

A Blender addon (`opengoal_tools`) that lets modders build custom Jak 1 levels
entirely from Blender — placing actors, triggers, cameras, enemies, platforms,
navmesh, and more — then compiles and launches the game with one button.

The addon wraps the OpenGOAL engine (an open-source reimplementation of Jak 1)
and its GOAL compiler. It outputs JSONC level files, GOAL source code, and DGO
packages that the game engine loads at runtime.

---

## Repo Structure

```
Claude-Relay/
├── CLAUDE-SKILLS.md              # Load at session start — git grep patterns etc.
├── addons/
│   └── opengoal_tools/           # The addon (split module, Blender 4.4+)
│       ├── __init__.py           # Registration, bl_info
│       ├── data.py               # All entity definitions, lump tables, enums
│       ├── export.py             # Scene → JSONC/GOAL/GLB pipeline
│       ├── build.py              # GOALC process management, build pipeline
│       ├── operators.py          # All bpy.types.Operator subclasses
│       ├── panels.py             # All bpy.types.Panel subclasses
│       ├── properties.py         # PropertyGroup definitions
│       ├── collections.py        # Collection path helpers, level accessors
│       └── utils.py              # Shared predicates (_is_linkable etc.)
├── knowledge-base/opengoal/      # Deep reference docs — load as needed
│   ├── modding-addon.md          # Addon architecture overview
│   ├── entity-spawning.md        # Full actor/entity reference
│   ├── lump-system.md            # Res-lump data format
│   ├── level-flow.md             # Continues, checkpoints, load boundaries
│   ├── navmesh-system.md         # NavMesh export and linking
│   ├── camera-system.md          # Camera actors and triggers
│   ├── platform-system.md        # Moving platforms
│   ├── enemy-activation.md       # Enemy aggro triggers
│   ├── audio-system.md           # Sound banks and emitters
│   └── [many more...]
├── session-notes/                # Per-feature progress — load at session start
└── scratch/                      # Throwaway files, test scripts
```

---

## Environment Setup

### Binaries (Linux x64)
All binaries live at `/home/claude/`:
```
extractor   — ISO extraction + decompile + compile (one-shot setup tool)
goalc       — GOAL compiler (keeps running, listens on nREPL port 8181)
gk          — Game kernel (the actual game executable)
```

### Data Directory
`/home/claude/data/` — the OpenGOAL project root:
```
data/
├── goal_src/jak1/          — GOAL source files (engine + levels)
│   ├── engine/             — Vanilla engine code (don't touch)
│   ├── levels/             — Level GOAL source (custom levels go here)
│   │   └── test-zone/      — Existing working test level
│   └── game.gp             — Build manifest (register custom levels here)
├── custom_assets/jak1/     — Custom level assets
│   └── levels/
│       └── test-zone/      — test-zone GLB, JSONC, GD
├── decompiler_out/         — Decompiled game objects (auto-generated, read-only)
├── out/jak1/iso/           — Compiled output DGOs/CGOs (auto-generated)
└── game/                   — Runtime assets (textures, fonts, etc.)
```

### ISO Data
`/home/claude/iso_data/iso_data/jak1/` — extracted Jak 1 NTSC v1 disc.
Required for decompile. Already decompiled — don't need to re-run extractor
unless starting completely fresh.

### Blender
`/home/claude/blender-4.4.3-linux-x64/blender` — Blender 4.4.3 binary.
Addon installed at: `/home/claude/blender-4.4.3-linux-x64/4.4/scripts/addons/opengoal_tools/`

---

## First-Time Setup (if starting fresh)

If the game hasn't been decompiled/compiled yet:
```bash
# 1. Decompile (reads ISO, writes goal_src decompiler output) — ~10 min
cd /home/claude
./extractor --proj-path /home/claude/data --folder --decompile \
  /home/claude/iso_data/iso_data/jak1

# 2. Compile (runs goalc on all source files, produces DGOs) — ~15 min
./extractor --proj-path /home/claude/data --folder --compile \
  /home/claude/iso_data/iso_data/jak1
```

Check compile finished:
```bash
# Should end with [100%] or similar
tail -5 /tmp/compile.log | sed 's/\x1b\[[0-9;]*m//g'
# Should contain GAME.CGO, ENGINE.CGO, KERNEL.CGO
ls /home/claude/data/out/jak1/iso/*.CGO
```

---

## Installing the Addon

```bash
ADDON_DIR="/home/claude/blender-4.4.3-linux-x64/4.4/scripts/addons"
cp -r /home/claude/Claude-Relay/addons/opengoal_tools "$ADDON_DIR/"
```

Always install from `feature/vis-blocker` branch unless told otherwise.
Check which branch is active:
```bash
cd /home/claude/Claude-Relay && git branch
```

---

## Running Blender Headlessly

```bash
BLENDER="/home/claude/blender-4.4.3-linux-x64/blender"
$BLENDER --background --python /path/to/script.py 2>&1 | grep -v "^Warning\|^Found\|^Read"
```

**Critical:** In headless mode, the addon dir is NOT in sys.path automatically.
Always add this at the top of headless scripts:
```python
import sys
sys.path.insert(0, "/home/claude/blender-4.4.3-linux-x64/4.4/scripts/addons")
import addon_utils
addon_utils.enable("opengoal_tools", default_set=True)
```

---

## Addon Preferences (required before building)

The addon needs to know where OpenGOAL lives. In headless scripts:
```python
import bpy
prefs = bpy.context.preferences.addons["opengoal_tools"].preferences
prefs.project_path = "/home/claude/data"
prefs.goalc_path   = "/home/claude/goalc"
prefs.gk_path      = "/home/claude/gk"
```

In the Blender UI: Edit → Preferences → Add-ons → OpenGOAL Tools.

---

## How a Level Gets Built

The full pipeline in order:

```
Blender scene
    │
    ▼ export_glb()          — exports level geometry as GLB
    │ export_vis_blocker_glbs() — exports VISMESH_ objects as individual GLBs
    │
    ▼ [background thread]
    │ collect_actors()       — ACTOR_ empties → JSONC actor dicts
    │ collect_vis_blockers() — VISMESH_ meshes → vis-blocker actor dicts
    │ collect_cameras()      — CAMERA_ objects → camera actor dicts
    │ collect_aggro_triggers() — VOL_→enemy links → aggro-trigger actors
    │ collect_vis_trigger_actors() — VOL_→VISMESH_ links → vis-trigger actors
    │
    ▼ write_jsonc()          — writes custom_assets/.../level.jsonc
    │ write_gd()             — writes .gd DGO descriptor
    │ write_gc()             — writes goal_src/.../level-obs.gc (GOAL types)
    │ patch_level_info()     — updates engine/level/level-info.gc
    │ patch_game_gp()        — registers level in game.gp build manifest
    │
    ▼ goalc (mi)             — GOAL compiler recompiles changed files
    │
    ▼ gk                    — game launches, loads level
```

---

## Key Naming Conventions

| Blender object name | Meaning |
|---|---|
| `ACTOR_babak_1` | Enemy/prop actor (etype=babak, uid=1) |
| `SPAWN_start` | Player spawn point |
| `CHECKPOINT_mid` | Checkpoint |
| `CAMERA_overview` | Camera position |
| `VOL_1` | Trigger volume (links to camera/checkpoint/enemy/VISMESH_) |
| `VISMESH_wall-1` | Vis-blocker mesh (hides/shows via trigger) |
| `WATER_pool` | Water volume |
| `NAVMESH_ground` | NavMesh geometry |

All objects must be inside the **level collection** to be exported.
Level collection custom property `og_level_name` sets the level name.

---

## Entity Types

All entity types are defined in `data.py` → `ENTITY_DEFS` dict.
Key fields per entity:
- `ag` — art-group filename (e.g. `"babak-ag.go"`)
- `cat` — category (Enemies, Props, Objects, Platforms, etc.)
- `ai_type` — `"nav-enemy"` or `"prop"` or `"process-drawable"`
- `is_prop` — decorative only, no AI
- `nav_safe` — False = needs navmesh or will crash

Common safe props to use in tests: `evilplant`, `tntbarrel`, `spike`.
Common enemies: `babak`, `hopper`, `lurker-crab` (all nav-enemies, need navmesh).

---

## GOAL Code Basics

The GOAL language used by Jak 1 is a Lisp dialect. Custom level obs.gc files
define new types using `deftype` and `defstate`. Key patterns:

```lisp
;; Define a new process-drawable type
(deftype my-actor (process-drawable)
  ((my-field int32 :offset-assert 176))
  :heap-base #x50
  :size-assert #xb8
  (:states my-actor-idle))

;; Define its idle state
(defstate my-actor-idle (my-actor)
  :code (behavior () (loop (suspend))))

;; Spawn from entity/JSONC — reads lumps here
(defmethod init-from-entity! ((this my-actor) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this my-field) (the int (res-lump-value arg0 'my-lump uint128)))
  (go my-actor-idle)
  (none))
```

**:offset-assert values** — these must be correct for the struct layout.
`process-drawable` ends at offset 176. Each new field adds 4 bytes (int32/float)
or 8 bytes (string pointer on 64-bit). Heap-base and size-assert follow from this.
A safe approach for simple types: use the same offsets as existing similar types
in obs.gc (camera-trigger, aggro-trigger, vis-trigger are all good references).

---

## Lump System (reading entity data in GOAL)

Lumps are per-entity key-value data stored in the JSONC and read at runtime:

```lisp
;; Read a string
(res-lump-struct arg0 'my-string-lump string)

;; Read a float
(res-lump-float arg0 'my-float-lump)

;; Read an integer
(the int (res-lump-value arg0 'my-int-lump uint128))

;; Read a meters value (already converted to game units)
(res-lump-float arg0 'bound-xmin)  ;; meters lump auto-converts
```

In the JSONC, lumps look like:
```json
"lump": {
  "name":       "my-actor-1",
  "my-string":  "hello",
  "my-float":   ["float", 3.14],
  "my-int":     ["uint32", 42],
  "my-meters":  ["meters", 5.0]
}
```

Full lump reference: `knowledge-base/opengoal/lump-system.md`

---

## The test-zone Level

There's a working test level already set up:
- Level name: `test-zone` (symbol `'test-zone`)
- Nickname: `tsz`
- Source: `goal_src/jak1/levels/test-zone/test-zone-obs.gc`
- Assets: `custom_assets/jak1/levels/test-zone/`
- Already registered in `level-info.gc` and `game.gp`

**To load it in game** (after compile):
```lisp
;; Send via nREPL (port 8181 when goalc is running)
(start 'play (get-continue-by-name *game-info* "test-zone-start"))
```

The continue point spawns Jak at `(0, 10m, 10m)` facing default direction.

---

## Build Cycle (incremental)

After initial compile, don't re-run the full extractor. Use nREPL:

```bash
# 1. Start goalc in one terminal (keeps running)
cd /home/claude && ./goalc --proj-path /home/claude/data

# 2. Connect and recompile changed files
# The addon does this automatically via (mi) when you hit Build & Play
# Manually: connect to port 8181 and send (mi)
```

The addon manages goalc automatically — it launches it if not running,
sends `(mi)` via nREPL, and polls for completion.

---

## Common Pitfalls

**"no proper process type named X exists"** — The etype string in the JSONC
doesn't match any loaded GOAL type. Either the obs.gc didn't compile, or the
type name has a typo. Check `goal_src/levels/<name>/<name>-obs.gc` was saved.

**Actor spawns but is invisible** — `draw-status hidden` is set, or the
art-group failed to load. Check `[vis-blocker] born:` log lines.
`initialize-skeleton-by-name` will silently fail if the art-group name is wrong.

**Game crashes on level load** — Usually a null pointer from a nav-enemy without
a navmesh, or a bad lump type. Check the obs.gc offset-assert values are correct.

**GLB not found** — The `gltf_file` path in JSONC must be relative to the
data directory and use forward slashes. Custom vis-blocker GLBs must be in the
same folder as the level JSONC.

**Compile "duplicate defstep"** — An enemy type that's already in GAME.CGO was
added to the custom DGO too. The addon handles this via `o_only=True` in
`ETYPE_CODE` — don't add vanilla types to the GD file manually.

---

## Testing Headlessly

The test suite for vis-blocker is at `scratch/test_vis_blocker.py`.
Run with:
```bash
/home/claude/blender-4.4.3-linux-x64/blender --background \
  --python /home/claude/Claude-Relay/scratch/test_vis_blocker.py \
  2>&1 | grep -E "PASS|FAIL|RESULT|All"
```
Expected: 16/16 PASS.

Template for new headless tests — see `scratch/test_vis_blocker.py` for the
sys.path fix and addon_utils.enable pattern.

---

## Key Source Files to Know

| File | What's in it |
|---|---|
| `addons/opengoal_tools/data.py` | `ENTITY_DEFS`, `ETYPE_AG`, `ETYPE_CODE`, all lump tables |
| `addons/opengoal_tools/export.py` | Full scene→files pipeline, all collect/write functions |
| `addons/opengoal_tools/build.py` | `_bg_build`, goalc process management |
| `data/goal_src/jak1/engine/entity/entity.gc` | How entity types are looked up at runtime |
| `data/goal_src/jak1/engine/common-obs/process-drawable.gc` | Base class for all actors |
| `data/goal_src/jak1/engine/common-obs/generic-obs.gc` | `manipy`, `med-res-level` |
| `data/goal_src/jak1/engine/data/art-h.gc` | `draw-status` enum (hidden flag is bit 1) |

---

## Active Feature Branches

| Branch | What's on it |
|---|---|
| `main` | Clean installable build, v1.4.0 |
| `feature/vis-blocker` | VISMESH_ hide/show trigger system (tested, not merged) |

Always check session-notes/ for the relevant branch before starting work.
`session-notes/vis-blocker-progress.md` has the current state of that feature.
