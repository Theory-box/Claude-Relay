# OpenGOAL Level Tools — Jak 1 Blender Addon

A Blender 4.x addon for building custom levels in [OpenGOAL](https://opengoal.dev/) (the Jak 1 PC port).  
Handles geometry export, actor placement, trigger/camera authoring, navmesh, sound, light baking, and one-click compile + launch.

> **Target game:** Jak and Daxter: The Precursor Legacy (Jak 1) via OpenGOAL.  
> **Blender version:** 4.0+  
> **Status:** Active development. See [Known Issues](#known-issues--not-yet-working) below.

---

## Feature Overview

### Level Management
- Create a new level collection with a name, base actor ID, and auto-incremented ID assignment
- Assign an existing Blender collection as a level
- Multi-level support — switch between levels in the same `.blend` file
- Level name validation (max 10 chars, auto-derives ISO name and nickname used by GOAL)
- Optional vis-nick override for custom visibility culling nicknames
- Sub-collection toggle to disable export per collection (e.g. hide reference geometry)
- **Sort Collection Objects** — auto-sorts loose objects into the correct sub-collections based on name prefix

---

### Spawn System
- Place **Player Spawns** (`SPAWN_`) with linked camera anchor (`SPAWN_xxx_CAM`)
- Place **Checkpoints** (`CHECKPOINT_`) with camera anchor and linked trigger volume
- UI lists all placed spawns and checkpoints with quick-select and delete
- Autolink: one-click "Add Trigger Volume" creates and links a volume to a checkpoint
- Camera anchor creation directly from the spawn/checkpoint context

---

### Entity Spawning (~160 entity types)

All entities are searchable via **Quick Search** (fuzzy text match across all categories).

#### Enemies (~30 types)
Lurker soldiers, lurker shooters, lurker stompers, lurker ambushers, lurker explorers, lurker spiders, lurker runners, lurker miners, lurker widowmakers, swamp bats, swamp bat masters (spawners), swamp rats, swamp rat nests, lurker fishers, lurker crabs, lurker jellyfish, dark crystals, yetis, rock-riders, villa starfish, and others.

Each nav-enemy gets:
- **NavMesh link** — shift-select a mesh + click Link; shows triangle count
- **Activation distance** (idle-distance lump) — how close the player must be to wake the enemy; default 80 m
- **Trigger Behaviour** — link trigger volumes to control aggro/patrol/wait-for-cue behaviour per-link
- **Waypoints** — add/remove patrol path points; Path A and Path B (for swamp-bat slave routes)
- **Vis distance** override (default 200 m)
- **Spawner count** override (swamp-bat master, yeti, villa starfish, swamp rat nest)

#### Platforms (~25 types)
Moving platforms, bounce pads (springbox), launchers, flip platforms, orbit platforms, square platforms, wedge platforms, wall platforms, teeter-totters, warp gates, cave elevators, and others.

Platform-specific settings:
- **Launcher** — spring height override, launch destination empty, fly time override
- **Flip platform** — delay down/up (s), phase offset for staggering multiples
- **Orbit platform** — orbit scale and timeout; requires entity link to center actor
- **Square platform** — travel range up/down (m)
- **Cave elevator** — mode 0/1, rotation offset
- **Rope bridge** — variant selector (32 m / 36 m / 52 m / 70 m, snow, village3)

#### Props & Objects (~40 types)
Crates, TNT barrels, dark eco vents, eco vents (blue/red/yellow), whirlpools, windmills, wind turbines, bone bridges, shover hazards, lava balloons, dark eco barrels, orb cache tops, breakaway platforms, cave flame pots, pontoons, oracles, and others.

Object-specific settings:
- **Crate** — type (steel / iron / wood / dark-eco / steel-lurker), contents (money × N, health, blue/red/yellow/dark eco, scout fly), amount stepper; scout fly enforces iron/steel
- **Dark crystal** — underwater variant toggle (mode 0 vs 1)
- **Power cell (fuel-cell)** — skip jump animation toggle
- **Orb cache** — orb count (default 20)
- **Whirlpool** — base speed and variation
- **Rope bridge** — variant selector
- **Breakaway** — fall height offsets H1 / H2
- **Sunken fish** — school size
- **Sharkey** — scale, delay, detection range, speed
- **Cave flame pots** — launch force, cycle period/phase/pause
- **Shover** — shove force, rotation offset
- **Lava balloon / dark eco barrel** — movement speed (needs waypoints)
- **Wind turbine** — particle effects toggle
- **Orbit platform** — orbit scale and timeout

#### NPCs (~15 types)
Farmers, fishermen, mayor, uncle, warrior, geologist, yakow, kermit, sage (all four), and others.

#### Pickups (~10 types)
Power cells, scout flies, orb clusters, eco vents (all types), precursor orbs.

#### Doors (~5 types)
- **Eco door / jungle iris door / sidedoor / rounddoor** — auto-close, one-way, starts-open flags; optional state-actor link (button-controlled lock)
- **Launcherdoor** — continue point selector (lists all checkpoints/spawns in scene)
- **Sun iris door** — proximity toggle, auto-close timeout; triggered via volume or basebutton
- **Basebutton** — reset timeout (permanent or timed)

---

### Tpage Budget Filter
- Enable a filter on the Quick Search and entity lists showing only actors compatible with the current level's tpage group budget (max 2 non-global groups)
- Two dropdown slots; warns on duplicate group selection

---

### Trigger Volumes
- Add box-shaped trigger volumes (`VOL_` prefix)
- Link volumes to: checkpoints, cameras, nav-enemies (with per-link behaviour: `aggro`, `patrol`, `wait-for-cue`)
- Link UI: shift-select the target, click "Link →"; detects already-linked targets and warns
- Volume list in scene with link status, orphan detection and one-click cleanup
- **Aggro triggers** — spawn from a selected enemy; sets up a fully linked volume automatically

---

### Camera System
- Place named cameras (`CAMERA_`) with three modes: **Fixed**, **Side-Scroll (standoff)**, **Orbit**
- Per-camera blend time (s) and FOV (°) controls
- Side-scroll mode requires a `_ALIGN` anchor (player position reference)
- Orbit mode requires a `_PIVOT` anchor
- **Look-At target** — camera ignores its rotation and aims at an empty; clears with one button
- Rotation quaternion readout + warning when camera has no rotation
- Camera list with inline mode/blend/FOV controls
- Link cameras to trigger volumes (always-active if no volume linked)

---

### Sound Emitters
- Place ambient sound emitters (`AMBIENT_`) at cursor
- Sound picker dialog — searchable list of all ~1,200 SFX IDs grouped by bank
- Per-emitter: sound name, mode (loop / once), radius (m)
- Scene list of placed emitters (up to 8 shown inline)
- **Music panel** — set level music bank and up to 2 sound banks (warns on duplicate, shows available SFX count)

---

### Water
- **Water volumes** (`WATER_` mesh) — define surface Y, wade depth, swim depth, bottom Y; damage type (drown / lava / dark-eco-pool / heat / drown-death)
- **Sync from mesh** — auto-sets heights from mesh bounding box top/bottom
- **Water-vol actor** (legacy) — scale warning, surface/wade/swim/bottom height nudgers with sync-from-object-Y

---

### NavMesh
- Mark any mesh as navmesh geometry (tagged with `og_navmesh`)
- Link a navmesh mesh to a nav-enemy (stores `og_navmesh_link`); shows triangle count
- Unlink navmesh; shows which actors reference a mesh
- Fallback sphere radius readout per enemy

---

### Waypoints
- Add/delete waypoints for any patrolling enemy (`ACTOR_xxx_wp_00`, `_wp_01`, ...)
- Dual-path support: Path A (`_wp_`) and Path B (`_wpb_`) for swamp-bat slaves
- Crash warnings when required paths are missing

---

### Actor Links (Entity-to-Entity References)
- Some entities carry lump-based references to other actors (e.g. eco-door → basebutton via `state-actor`, launcher → destination empty, orbit-platform → center actor)
- Per-slot UI: shows current linked actor, jump-to button, clear button
- Link UI: shift-select a compatible actor → click "Link →"; validates accepted actor types per slot
- Slot compatibility enforced (accepted types shown on mismatch)

---

### Custom Lumps
- Per-actor raw lump editor — key / type (int, float, string, vector, bool, etc.) / value
- Inline parse error display for the selected row
- Warning when a key overrides an addon-managed default
- **Lump Reference panel** — shows all documented universal and actor-specific lumps with one-click "Add prefilled row"

---

### Collision (Per Mesh)
- Toggle collision on/off per mesh
- Set: ignore, collide mode, collide material, collide event
- Four flags: no-edge, no-entity, no-line-of-sight, no-camera
- Visibility flags: set-invisible, enable-custom-weights, copy-eye-draws, copy-mod-draws

---

### Geometry — Export As (Vertex Export)
- Assign a mesh's vertices as spawn positions for an entity type
- Each vertex becomes one actor instance at export time
- Searchable entity picker; shows evaluated vertex count (post-modifier)

---

### Light Baking
- Bake Cycles lighting to vertex color layer `BakedLight` on selected meshes
- Sample count control
- Accessible from Level panel and per-mesh in Selected Object panel

---

### Level Audit
- One-click scan of the active level for errors, warnings, and info
- Checks include:
  - Tpage budget (> 2 non-global groups = warning)
  - Nav-enemy missing navmesh link
  - Nav-enemy navmesh has unsafe type
  - Patrolling enemy missing waypoints
  - Swamp-bat missing Path B
  - Spawns missing camera anchor
  - Checkpoints missing camera anchor or trigger volume
  - Cameras with no rotation
  - Trigger volumes with orphaned (deleted) link targets
  - Required actor links missing
- Click any result's select icon to jump to the offending object
- Error/warning count shown in panel header

---

### Build & Play
- **Export & Compile** — writes `.jsonc`, `.glb`, `.gd`, `.gc`, patches `level-info.gc` and `game.gp`, launches GOALC, sends REPL commands to hot-load the level, then launches the game
- **Quick Geo Rebuild** — re-exports geometry and re-sends only the geo rebuild REPL commands (skips actor/entity recompile); faster iteration loop
- **Launch Game (Debug)** — launches `gk` with the game data path and debug flags
- Background threading — build and play run without blocking Blender's UI
- GOALC nREPL management — auto-finds a free port, launches GOALC as a subprocess, sends commands, kills on exit

---

### Developer Tools
- Path validation — checks `gk`, `goalc`, `game.gp` exist; links to addon preferences
- **Clean Level Files** — deletes generated `.jsonc`, `.glb`, `.gd`, `-obs.gc` to force a clean rebuild
- Quick Open buttons — one-click open of `goal_src/`, `game.gp`, `level-info.gc`, `entity.gc`, level folder, level files, `custom_assets/`, game logs, `startup.gc`
- **Reload Addon** — hot-reloads all Python modules without restarting Blender

---

### Texture Tools (v1.9.0)
- Replace textures on selected faces in Edit Mode, or on whole objects in Object Mode
- Search textures by name; apply to selection

---

## In-Progress Features (Active Branches)

| Branch | Feature | Status |
|---|---|---|
| `feature/lighting` | Time-of-day (TOD) patch editor — edit ambient/directional lighting curves exported to GOAL | Active; backup/restore done, TOD panel mostly working |
| `feature/native-checkpoints` | Native GOAL checkpoint volumes (closed/open boundary polygon triggers) | Active; boundary flag bug worked around, nearly complete |
| `feature/vis-blocker` | Vis-blocker geometry support — mark meshes to block visibility culling | 16/16 tests passing; integration pending |

---

## Known Issues / Not Yet Working

| Area | Issue |
|---|---|
| **Navmesh adjacency** | Nav-mesh adjacency path-finding (BFS shortest-path routes between polys) is computed and written to GOAL structs, but has not been validated in-game against all enemy types. Enemies with complex nav behaviour may not path correctly. |
| **Orbit platform** | Requires an entity link to a center actor; if that link is missing the platform will not orbit. The UI warns but does not prevent export. |
| **Water-vol actor (legacy)** | The `water-vol` actor type is marked Hidden in the entity list. It exports but its behaviour in custom levels is not fully verified — prefer the `WATER_` mesh approach. |
| **Villa starfish** | Has no AG file (`ag: None`). Spawning works but the enemy's art group must already be loaded by the level's tpage group (Village1). Will not appear in levels outside Village1 tpage. |
| **process-drawable enemies outside their tpage** | Any enemy whose `tpage_group` is not in the active level's tpage budget will fail to load art at runtime. The tpage filter UI helps prevent this but does not enforce it at export. |
| **Look-At camera in orbit mode** | Combining orbit mode with a Look-At target is untested. The export writes both, but engine behaviour is unknown. |
| **Multiple levels in one .blend** | Export always targets the active level. Exporting all levels in one pass is not supported. |
| **Checkpoint native volumes** (`feature/native-checkpoints`) | Branch not yet merged. Existing checkpoint system uses a fallback sphere radius or a `VOL_` box volume — neither is a native GOAL polygon trigger. |
| **Time-of-day editor** (`feature/lighting`) | Not yet merged to main. Lighting on main branch exports with default TOD values only. |
| **GLB export with zero-geometry modifiers** | Meshes with modifiers that produce zero geometry at export time may silently produce empty actors. |
| **GOALC auto-launch on Linux/Mac** | Tested primarily on Windows. Linux/Mac users may need to manually start GOALC and connect; path handling for non-Windows EXE extensions is implemented but less tested. |

---

## Installation

1. Download the `opengoal_tools` folder (or zip it)
2. In Blender: Edit → Preferences → Add-ons → Install → select the folder/zip
3. Enable **OpenGOAL Level Tools**
4. In addon preferences, set:
   - **EXE path** — folder containing `gk` and `goalc`
   - **Data path** — OpenGOAL project root (the folder containing `data/`)

The panel appears in the **3D Viewport → N panel → OpenGOAL** tab.

---

## Repository Structure

```
addons/opengoal_tools/            Active addon (modular, split-file)
addons/opengoal_tools_PRE_SPLIT.py  Legacy monolithic version (reference only)
knowledge-base/                   Documented knowledge by topic
session-notes/                    Per-topic progress tracking
scratch/                          Temporary working files
CLAUDE-SKILLS.md                  Techniques reference
```
