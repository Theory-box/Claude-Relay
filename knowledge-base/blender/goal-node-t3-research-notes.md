# GOAL Nodes — T3 Feature Research Notes

> Follow-up to `goal-node-advanced-vocabulary-brainstorm.md §20`. The three T3 items flagged there as needing dedicated research before they can be scoped: **particle effects, cam-spline, and battlecontroller**. This document gathers what each actually requires so future sessions can decide whether they're in scope.

---

## 0. The framing insight

**These three items are not primarily GOAL-node features.** They're *scene-authoring* features that extend the JSONC and per-level file emission pipeline. The runtime behaviour is engine-native — you don't write a `:trans` handler for "be a particle spawner," you declare one via lumps and the engine does the rest.

That matters because the GOAL Node Compiler I've built targets runtime behaviour for `ACTOR_*` empties. Particle spawners, cam-spline cameras, and battlecontrollers need:

1. A new entity *category* in the addon (beyond the current `ACTOR_*`)
2. JSONC emission extensions in `addons/opengoal_tools/export.py`
3. For particles only — a new `<levelname>-part.gc` source file generator
4. Graph nodes to *reference* these entities, but not *define* them via the graph

So the honest design answer is: **the graph is the wrong tool for the core of these features**. What the graph *can* provide is convenience nodes that send events/commands referencing these entities (e.g. `SpawnParticleAt(group-name)`, `CameraSwitchToSpline(cam-name)`).

This reframes the T3 scope considerably — from "add N particle nodes to the graph" to "extend the addon's scene-authoring surface + add a handful of node-graph conveniences."

---

## 1. `cam-string` — rubber-band follow camera

**Complexity: LOW.** Simplest of the three.

### What it is
A third-person follow camera constrained within an AABB trigger volume. Normal follow behaviour, just scoped to the zone. When Jak exits the zone, camera reverts to the default camera system. Excellent for large outdoor areas where fixed camera framing would feel claustrophobic.

### What the addon would need
Two new lumps on camera entities:
- `stringMaxLength` — meters, max tether distance
- `stringCliffHeight` — meters, max upward Y offset tracked

That's it. No new entity type, no new GOAL source. The existing `camera-marker` + `camera-trigger` JSONC format already supports an arbitrary lump bag — just extend the camera panel in `addons/opengoal_tools/panels.py` to expose these two fields and write them through in `export.py`.

### Graph integration

Minimal. No new node types needed — the camera is just a `CAMERA_` empty with different lumps. If users want gameplay logic that *reacts* to camera-string state (e.g. "when Jak enters this camera zone, do X"), the existing `TriggerOnVolEntered` covers it.

### Open questions

- Sane default values? `future-research.md` notes these aren't documented.
- Does it interact with `stringCliffHeight` when Jak is on a platform vs the ground? Needs in-game testing.

### Effort estimate

- Addon panel + export: ~1 day
- Graph node: zero (uses existing infrastructure)

---

## 2. `cam-spline` — scripted camera paths

**Complexity: MEDIUM.**

### What it is
Camera follows a spline path as Jak moves through a trigger zone. `spline-follow-dist` controls whether it's lookahead-projected or closest-point-tracking. Always aims at Jak unless `flags 0x8000`. This is what vanilla uses for corridor-style cinematography — you walk through the canyon and the camera glides along with you.

### What the addon would need

Four new lumps on camera entities (all from `camera-system.md §9`):
- `campath` — `vector4m` multi-point: spline control points
- `campath-k` — `float` array: spline knot values, one per control point
- `spline-offset` — `vector`: offset applied to whole path
- `spline-follow-dist` — `float`: distance ahead of Jak along spline

**Blender source:** a Bezier or poly curve. The addon converts curve control points to `campath` and generates sensible knot values for `campath-k`. This is the only non-trivial code — curve → `vector4m` array is straightforward, but the knot values need thought.

**Knot parameterisation is the open question.** `future-research.md §2`:
> "What is `campath-k` exactly — knot values, uniform spacing, or arc-length parameterized?"

Without this answered, we don't know how to convert a Blender curve correctly. Needs either source-read of the engine's spline eval code (`cam-states.gc`) or in-game experimentation with multiple parameterisations.

### Graph integration

Two candidate nodes:
- `CameraSwitchToSpline(cam_name)` — INSTANT action, sends `'change-to-entity-by-name` then whatever event activates spline mode (need to verify this is automatic when spline lumps are present).
- `OnCameraSplineExit` / `OnCameraSplineEnter` — trigger nodes that fire on volume enter/exit, same as `OnVolEntered` just with a semantic rename.

Neither is critical — existing camera switch and volume trigger nodes cover it.

### Effort estimate

- Engine research + knot parameterisation: ~1 day of in-game experimentation
- Curve export in addon: ~1 day
- Camera panel UI: ~0.5 day
- Total: ~2-3 days after the research is unblocked

---

## 3. Particle effects — the biggest of the three

**Complexity: HIGH.** Not because any single piece is hard, but because the surface is broad.

### What it is

Source: `knowledge-base/opengoal/particle-effects-system.md`.

Every vanilla level has a `<levelname>-part.gc` file alongside `<levelname>-obs.gc`. It defines:
1. A `part-spawner` subtype for that level: `(deftype villagea-part (part-spawner) ())`
2. One or more `defpartgroup` — named effects composed of multiple items
3. One or more `defpart` — individual particle launchers with ~20 parameters each

`part-spawner` instances in the JSONC reference a group by name via the `art-name` lump. On init, the spawner looks up the group in `*part-group-id-table*` (a 1024-slot global table, 709-1023 safe for custom levels).

### What the addon would need

Three new things:

**1. A new per-level file generator** — analogous to `write_gc` but for `<levelname>-part.gc`. Same pattern. Needs to go in `export.py` alongside the existing GC emission.

**2. A new entity category** — `EFFECT_` empties analogous to `ACTOR_`. Each carries a group name (`art-name` lump) pointing at a defined group.

**3. ID allocation** — `defpart` IDs 2969-3583 (615 slots) and `defpartgroup` IDs 709-1023 (315 slots) must be unique per compile. The addon needs to track used IDs and assign new ones deterministically.

### Design question for particle authoring UX

There are three plausible approaches to exposing `defpart`/`defpartgroup` to users:

**Option A — Preset recipes only.** Ship ~10-15 pre-tuned particle effects (campfire, drip, sparkles, smoke, waterfall mist, lightning, etc.) as part of the addon. User picks a preset + a few tuning knobs (colour, scale, rate). No custom particle authoring.
- Pro: covers 90% of modder needs; simple UX; no node-graph complexity
- Con: users can't create truly custom effects

**Option B — Per-parameter node graph.** A ParticleGroup node with children that are Part nodes, each exposing all ~20 init-spec fields as socket inputs. Full authoring power.
- Pro: complete customisation; the graph metaphor is consistent
- Con: ~20 parameters per particle × tens of particles = massive graph surface; hard to visualise; `defpart` syntax has ranges and `:copy` references that are awkward as sockets

**Option C — Hybrid: presets + raw text override.** Preset picker by default, with a "View Lisp source" button that drops into a Blender text block containing the raw `defpart`/`defpartgroup` source for power users to edit by hand.
- Pro: recovers expert-user escape hatch; simple common case
- Con: round-tripping edits (text → preset) is hard; breaks single source of truth

**My recommendation: Option A first**, expandable to Option C later. Particles are high-impact-per-workhour when done as presets — most modders want "put a campfire here," not "author a custom particle emitter from scratch." Full authoring (Option B) is feature creep.

### Graph integration

If we go with presets:
- A `ParticlePreset` enum in the addon (campfire, torch, drip, sparkle, smoke, waterfall, magic, embers, rain, lightning, fog, electricity, dust, steam, lava-drip)
- `EFFECT_<preset>_<uid>` empties in Blender, similar to `ACTOR_` convention
- Graph nodes:
  - `SpawnParticleAt` — INSTANT action, `(process-spawn part-spawner ...)` at a position
  - `StartParticle(effect-name)` — send 'start event to a persistent `EFFECT_` empty
  - `StopParticle(effect-name)` — send 'stop
  - `OnParticleStart` / `OnParticleDone` — if users want chained effects

### Effort estimate

- Preset library + `<levelname>-part.gc` generator: ~3-4 days
- `EFFECT_` entity category + panels: ~2 days
- ID allocation logic: ~0.5 day
- Graph nodes (all 3-4): ~1 day
- Total (Option A): ~1 week

---

## 4. `battlecontroller` — multi-wave enemy encounters

**Complexity: MEDIUM.**

Source: `entity-spawning.md §12 + §13`.

### What it is

A pre-built enemy wave controller. One `battlecontroller` entity manages:
- Camera lock during combat
- Multiple spawn positions via `pathspawn` waypoints
- Mixed enemy types with per-type spawn probabilities
- Delay between waves
- Final reward pickup after all waves cleared

Used by vanilla for arena fights. The base `battlecontroller` type works directly in custom levels — no custom subclass needed.

### What the addon would need

Nine lumps on a new entity type (`battlecontroller` etype):
- `camera-name` — camera to activate during combat
- `pathspawn` — spawn position waypoints
- `delay` — seconds between waves
- `num-lurkers` — total enemy count
- `lurker-type` — type array of enemies to spawn
- `percent` — probability array, parallel to `lurker-type`
- `final-pickup` — reward pickup-type enum
- `pickup-type` / `max-pickup-count` / `pickup-percent` — per-type pickup overrides
- `mode` — 1 = prespawn

This is **pure JSONC config — no GOAL code needed**.

### Critical subtlety

Spawned enemies inherit the controller's entity for lump lookups:
```lisp
(set! (-> self entity) (-> arg0 entity))  ; arg0 = battlecontroller instance
```

So shared config (idle-distance, vis-dist, nav-mesh-sphere) goes on the **controller's lumps**, not per-enemy lumps.

### Graph integration

A battlecontroller is wired into gameplay via events:
- `'trigger` to the battlecontroller → starts the wave
- `'trigger` from the battlecontroller → sent to `trigger-actor` refs when cleared (typically opens a door)

Both expressible with existing nodes: `SendEvent` to start, `OnEvent('trigger)` on the door to listen. No new node types strictly needed.

Convenience node candidates:
- `StartBattleWave(controller-name)` — label-clear shortcut for `SendEvent trigger`
- `OnBattleCleared(controller-name)` — semantic-clear wrapper on `OnEvent('trigger)`

Useful but not critical.

### Effort estimate

- Entity definition in `data.py`: ~0.5 day
- Panel UI for the 9 lumps (including enemy type array editor, probability list): ~2 days
- `pathspawn` waypoint support: ~1 day (mostly reuse of existing path export)
- In-game testing: ~1 day
- Total: ~4-5 days

---

## 5. Cross-cutting: what these three have in common

| Feature           | Graph-node surface | Addon surface               | Level-side files              |
|---                |---                 |---                          |---                            |
| cam-string        | 0 nodes            | 2 new lumps in camera panel | None                          |
| cam-spline        | 1-2 convenience    | 4 new lumps + curve export  | None                          |
| Particle presets  | 3-4 convenience    | New `EFFECT_` category, preset library, ID allocator | `<name>-part.gc` generator |
| battlecontroller  | 0-2 convenience    | New entity type + 9 lumps   | None                          |

**Total graph-node surface across all three:** 4-8 new node types, all convenience wrappers over existing primitives.
**Total addon surface:** substantial — new entity categories, lump families, and for particles, a whole new file generator.

This tells me: **T3 work lives mostly in the existing addon, not in the graph compiler**. The graph only gets lightweight additions once the addon-side work is done.

---

## 6. Sequencing recommendation

Given effort estimates:
1. **cam-string** — 1 day, obvious win, trivial
2. **battlecontroller** — 4-5 days, high impact for modders who want combat
3. **cam-spline** — 2-3 days + unresolved research (knot parameterisation)
4. **Particle presets (Option A)** — ~1 week, significant scope but high polish value

Do them in that order unless the user prioritises differently. Particles last because the scope is largest and preset library design warrants its own conversation.

All four are distinct enough from the GOAL Node Compiler that they could be separate feature branches — one per item — with independent PRs to main.

---

## 7. Does this change the graph vocabulary?

Minimally. Add to the T2 roadmap:
- `SpawnParticleAt(preset-name, position)`
- `StartPersistentParticle(effect-name)` / `StopPersistentParticle(effect-name)`
- `CameraSwitchToSpline(cam-name)`
- `StartBattleWave(controller-name)` / `OnBattleCleared(controller-name)`

All INSTANT actions or thin trigger wrappers — no new category, no compiler changes required.

Drop from T3, promote to T2. Leave T3 for genuinely speculative items (live parameter tweaking, runtime graph editing, replays).

---

## 8. Open questions for follow-up

1. **Knot parameterisation for cam-spline** — engine source `cam-states.gc` needs a read. Without this, curve export is guesswork.
2. **Particle preset library composition** — which 10-15 effects are most useful? Needs to align with what `future-research.md §11` identifies as high-value.
3. **Does base `battlecontroller` truly work without a level-specific subtype?** `future-research.md §5` flags this as unconfirmed. First battlecontroller test will answer.
4. **ID-space management for particles across multiple custom levels** — if a modder has 3 custom levels, they'll collide on the 709-1023 range. Global registry needed.
5. **EFFECT_ vs ACTOR_ — should they share infrastructure?** A persistent EFFECT_ is really just an ACTOR_ with etype=`<level>-part`. Argument for sharing: every empty in the scene goes through one pipeline. Argument against: different UI panels, different lump families, conceptual confusion.
