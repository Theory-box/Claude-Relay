# Enemy Activation & Trigger-Driven Aggro

How Jak 1 enemies decide when to wake up, and how to override that per-enemy
or via trigger volumes. All mechanisms below are existing engine features
exposed through res-lumps — no engine patches required.

## Why this exists

Two related player-facing problems:
1. Enemies sometimes "stand there frozen" until the player walks closer than
   expected, then suddenly start patrolling. This is the engine's
   `idle-distance` mechanism — it's working as designed but the default
   range (80m) is too generous for tight custom levels.
2. There's no built-in way to script enemy aggro from level geometry. You
   can't say "when the player walks through this doorway, the babak in the
   next room wakes up." But the engine already supports it via the
   `'cue-chase` event handler — we just need to expose it.

## Idle Distance — per-enemy activation range

### Engine mechanism

Every enemy/boss inherits `fact-info-enemy`, which reads `idle-distance` from
the entity's res-lump on construction:

```
goal_src/jak1/engine/game/fact-h.gc:191
(set! (-> this idle-distance) (res-lump-float entity 'idle-distance :default 327680.0))
```

327680 fixed-point = **80 meters** (the default activation range).

The nav-enemy update logic checks this every frame in `nav-enemy.gc`:

```
goal_src/jak1/engine/common-obs/nav-enemy.gc:495, 534, 709, 754
((>= (-> self enemy-info idle-distance)
     (vector-vector-distance (-> self collide-info trans) (-> *target* control trans))) ...)
```

When the player is **farther than `idle-distance`**, the enemy stays in its
idle state — it doesn't notice the player, doesn't patrol, doesn't path-find.
When the player crosses inside that radius, the normal AI takes over.

### Addon exposure

Every enemy/boss in the addon now has an `og_idle_distance` custom property
(default 80.0m). At build time the actor's lump dict gets:

```python
lump["idle-distance"] = ["meters", float(og_idle_distance)]
```

UI: select an enemy → "Activation" box → `-5m / Idle Distance: 80m / +5m`
nudge buttons. Range 0–500m. Lower = enemy stays asleep longer; higher =
wakes up sooner.

This applies to **all** enemies and bosses regardless of AI type — both
nav-enemies (Babak, Hopper, etc.) and process-drawable enemies (Yeti, Bully,
Mother Spider, etc.) inherit `fact-info-enemy`.

## Trigger-Driven Aggro — make enemies wake on command

### Engine mechanism

Nav-enemies have an event handler at `nav-enemy.gc:142` that responds to
three quoted symbols:

```
goal_src/jak1/engine/common-obs/nav-enemy.gc:142-144
(('cue-chase) (go-virtual nav-enemy-chase))
(('cue-patrol) (go-virtual nav-enemy-patrol))
(('go-wait-for-cue) (go-virtual nav-enemy-wait-for-cue))
```

The base game uses this in `battlecontroller.gc` to wake enemies during
boss arena fights:

```
goal_src/jak1/levels/common/battlecontroller.gc:114, 203
(send-event s4-0 'cue-chase)
```

To send these events from a trigger volume, the trigger needs to find the
target enemy at runtime by name. The engine provides a built-in helper:

```
goal_src/jak1/engine/entity/entity.gc:167
(defun process-by-ename ((arg0 string))
  "Get the process for the entity with the given name. If there is no entity or process, #f."
  (let ((v1-0 (entity-by-name arg0))) (if v1-0 (-> v1-0 extra process))))
```

`entity-by-name` (line 92) walks all loaded levels' actor lists and matches
the `'name` lump. Since the addon already writes a `'name` lump on every
actor at build time, we can look up any enemy by its Blender object name
verbatim.

### Critical limitation: nav-enemies only

**Process-drawable enemies do NOT respond to `'cue-chase`.** The handler is
defined on `nav-enemy`, not on `process-drawable`. Affected enemies that
**will not** aggro from triggers:

- Jungle Snake, Lurker Worm, Swamp Bat, Yeti, Bully, Puffer
- Flying Lurker, Plunger Lurker, Mother Spider, Gnawer
- Driller Lurker, Dark Crystal, Cave Crusher, Quicksand Lurker
- Ram, Lightning Mole, Ice Cube, Fire Boulder

Enemies that **will** aggro (the `nav_safe=False` set in `ENTITY_DEFS`):

- Babak, Lurker Crab, Lurker Puppy, Hopper, Swamp Rat, Kermit
- Snow Bunny, Double Lurker, Bone Lurker, Muse, Baby Spider, Green Eco Lurker

The addon enforces this at link time — `_actor_supports_aggro_trigger()`
returns False for process-drawable enemies, so the "Add Aggro Trigger" button
and the link UI only appear for nav-enemies.

### The aggro-trigger entity

The addon emits a new GOAL deftype `aggro-trigger` (similar pattern to the
existing `camera-trigger` and `checkpoint-trigger`). It's an AABB-polling
process-drawable that:

1. Reads `target-name` (string lump), `event-id` (uint32 lump, 0/1/2),
   and 6 `bound-*` floats from its res-lump on init
2. Each frame, checks if `*target* control trans` is inside the AABB
3. On rising edge (player entered, `inside` flag was false), looks up
   `(process-by-ename target-name)` and sends the matching event symbol
4. On falling edge (player exited), clears `inside` so the trigger can
   re-fire on re-entry

The `event-id` to symbol mapping is hardcoded in the trigger's state code
(no string-to-symbol gymnastics):

```lisp
(cond
  ((zero? (-> self event-id))    (send-event proc 'cue-chase))
  ((= (-> self event-id) 1)      (send-event proc 'cue-patrol))
  ((= (-> self event-id) 2)      (send-event proc 'go-wait-for-cue)))
```

The full deftype + state + init-from-entity code is emitted by `write_gc()`
in `addons/opengoal_tools.py` when `has_aggro_triggers=True`.

### Re-fire semantics

Aggro triggers re-fire every time the player re-enters the volume. If the
player walks out of range and back in, the enemy gets re-aggro'd. This
matches camera-trigger behavior. (Checkpoint-triggers, by contrast, latch
once via a `triggered` flag — that's the right call for save points but
wrong for combat triggers.)

If "wake once and stay woken" is needed later, it can be added as a
per-link option without engine changes (just a `latch` boolean lump).

## Multi-link volume system (data model)

A trigger volume (VOL_ mesh) holds a `CollectionProperty` of `OGVolLink`
entries on `bpy.types.Object.og_vol_links`. Each entry has:

- `target_name: StringProperty` — name of a Blender object the volume links to
- `behaviour: EnumProperty` — `cue-chase` / `cue-patrol` / `go-wait-for-cue`
  (only meaningful for nav-enemy targets; ignored for cameras and checkpoints)

A single volume can hold N links of mixed types. At build time, three
independent passes scan every volume's link collection:

- `collect_cameras()` emits a `camera-trigger` actor for each camera link
- `collect_actors()` emits a `checkpoint-trigger` actor for each checkpoint link
- `collect_aggro_triggers()` emits an `aggro-trigger` actor for each enemy link

Three actors at the same AABB position is legal — they run independent state
machines and don't interact.

### Volume naming convention

Volume names are pure labels — link data lives in the collection, not the name:

- 0 links → `VOL_<id>` (e.g. `VOL_4`)
- 1 link → `VOL_<target_name>` (e.g. `VOL_CAMERA_3`, `VOL_ACTOR_babak_0`)
- 2+ links → `VOL_<id>_<n>links` (e.g. `VOL_4_3links`)

Renaming is automatic via `_rename_vol_for_links()` after every add/remove.

### Migration from legacy single-string format

Old `.blend` files used `og_vol_link` (single string). The migration shim
in `_vol_links()` converts on first read:

```python
legacy = vol.get("og_vol_link", "")
if legacy and len(vol.og_vol_links) == 0:
    entry = vol.og_vol_links.add()
    entry.target_name = legacy
    entry.behaviour   = "cue-chase"
    del vol["og_vol_link"]
```

Idempotent and lazy — happens whenever any code path reads a volume's links.

### Duplicate-link rules

- **Same volume → same target twice**: blocked at link time for all target
  types (it would emit duplicate trigger actors at the same position)
- **Two different volumes → same camera/checkpoint**: blocked at link time
  (one camera/checkpoint should have one trigger system-wide)
- **Two different volumes → same enemy**: allowed (deliberate use case —
  one volume in the entrance, another in a flank position, both aggro the
  same babak)

### Orphan handling

When a target object is deleted via `OG_OT_DeleteObject`, the addon walks
every volume and removes link entries pointing at the deleted target. The
volumes themselves are never auto-deleted, even if they end up with zero
links — orphaned `VOL_<id>` volumes stay in the scene for the user to
re-link or delete manually. `OG_OT_CleanOrphanedLinks` is the manual sweep
button.

## Volume color coding

- Green `(0.0, 0.9, 0.3, 0.4)` — camera triggers
- Yellow `(1.0, 0.85, 0.0, 0.4)` — checkpoint triggers
- Red-orange `(1.0, 0.3, 0.0, 0.4)` — aggro triggers (enemy targets)
- Default green when spawned standalone

A multi-link volume keeps the color of whichever target type it was first
spawned for — visual indication is approximate, the link list is the source
of truth.

## Engine reference quick index

| Topic | File | Line |
|---|---|---|
| `idle-distance` lump read | `engine/game/fact-h.gc` | 191 |
| `idle-distance` AI check  | `engine/common-obs/nav-enemy.gc` | 495, 534, 709, 754 |
| `cue-chase` / `cue-patrol` / `go-wait-for-cue` event handlers | `engine/common-obs/nav-enemy.gc` | 142–144 |
| `entity-by-name` (string → entity) | `engine/entity/entity.gc` | 92 |
| `process-by-ename` (string → process) | `engine/entity/entity.gc` | 167 |
| Battlecontroller wake-up usage | `levels/common/battlecontroller.gc` | 114, 203 |
| Per-enemy `notice-distance` (in `nav-info`, NOT per-instance) | `levels/snow/snow-bunny.gc` | 73 |

`notice-distance` is mentioned in the engine alongside `idle-distance` but
it's defined per-type in `nav-info`, not per-entity, so it can't be
overridden via res-lump. The addon doesn't expose it. `idle-distance` is the
right knob for "wake up sooner" tuning.
