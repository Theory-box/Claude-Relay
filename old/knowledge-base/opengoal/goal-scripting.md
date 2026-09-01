# GOAL Scripting for Custom Levels

This document covers everything needed to write custom GOAL code for OpenGOAL Jak 1 custom levels.
All information sourced from `goal_src/jak1/` engine source.

---

## Table of Contents

1. [What GOAL Code Can Do](#what-goal-code-can-do)
2. [How Code Gets Into the Game](#how-code-gets-into-the-game)
3. [Language Fundamentals](#language-fundamentals)
4. [Unit System](#unit-system)
5. [Defining a Custom Entity](#defining-a-custom-entity)
6. [States](#states)
7. [The Event System](#the-event-system)
8. [Reading Lumps (Entity Data)](#reading-lumps-entity-data)
9. [Moving Objects](#moving-objects)
10. [Timing](#timing)
11. [Jak / Target Interaction](#jak--target-interaction)
12. [Sound](#sound)
13. [Game Settings](#game-settings)
14. [Skeletal Animation](#skeletal-animation)
15. [Permanent Entity Flags](#permanent-entity-flags)
16. [Wiring Entities Together](#wiring-entities-together)
17. [Complete Examples](#complete-examples)
18. [Offset-Assert Quick Reference](#offset-assert-quick-reference)
19. [Limitations](#limitations)

---

## What GOAL Code Can Do

Everything goes into `levels/<name>/<name>-obs.gc`, compiled with the level.
The addon already generates this file. Custom code is appended to it.

**Fully supported:**
- Define new entity types (deftypes) that spawn from empties exported by the addon
- Move, rotate, and scale objects every frame with transform math
- Read per-entity data (position, lumps) set from Blender
- Listen for and send events between entities and to Jak/camera
- Play sounds from the loaded bank
- Control game settings (music, volume, camera, letterbox, etc.)
- Run timed sequences and multi-state logic
- Follow waypoint paths exported by the addon
- Read Jak's position and distance to trigger logic
- Mark entities as dead/complete (persistent within session)
- Spawn particle effects from loaded tables

**Requires art assets in the DGO (advanced):**
- Skeletal animation (needs `defskelgroup` + art baked in)
- Custom meshes with collision

**Not possible from obs.gc alone:**
- Loading new art at runtime
- Modifying collision meshes after export
- Persistent save-game state (no free save slots in Jak 1)

---

## How Code Gets Into the Game

### Addon workflow (feature/goal-code)

The addon handles all injection automatically. You never edit `obs.gc` directly.

**Step-by-step:**

1. **Spawn your custom actor** — Spawn panel → ⚙ Custom Types → enter your type name (e.g. `spin-prop`) → Spawn. Places `ACTOR_spin-prop_0` at the 3D cursor.

2. **Attach a code block** — Select the empty → Selected Object panel → **GOAL Code** sub-panel → **Create boilerplate block**. Creates a Blender text block pre-filled with correct boilerplate for that etype.

3. **Write your code** — Open a Text Editor area (Shift+F11) → **Open in Editor** in the GOAL Code panel. Edit the block. The `deftype` name must match the etype exactly.

4. **Export+Build** — Build log shows:
   ```
   [write_gc] injected 1 custom GOAL code block(s): spin-prop-goal-code
   ```
   And `goal_src/levels/<n>/<n>-obs.gc` has your code at the bottom.

5. **In-game** — Entity spawns via `entity-actor.birth!` automatically. No nREPL call needed.

### What obs.gc always contains

The addon generates this file every export. Custom blocks come after:
- `camera-marker` deftype (always present)
- `camera-trigger` deftype (if trigger volumes exist)
- `checkpoint-trigger` deftype (if checkpoints exist)
- `aggro-trigger` deftype (if aggro trigger volumes exist)
- **Your custom code blocks**, in order, if any ACTOR_ empty has an enabled block assigned

### Multiple actors, one block

Multiple actors can share the same text block — it is emitted only once (deduplicated by text block name). Useful for placing several instances of the same type.

### Entity name matching

`ACTOR_spin-prop_0` → entity lump name `spin-prop-0` → requires `(deftype spin-prop ...)` in the code block. The uid suffix is stripped; the etype is the middle segment.

### Compile errors

Errors appear in the goalc build log, not in Blender. See [Limitations](#limitations) for the most common causes.

---
## Language Fundamentals

GOAL is a Lisp. Everything is an expression. Key syntax:

```lisp
;; Comment

;; Variable
(let ((x 5.0)
      (y (meters 3.0)))
  (+ x y))

;; Set a field
(set! (-> self root trans x) 0.0)

;; Conditional
(if condition then-expr else-expr)
(when condition body...)
(cond
  (test1 result1)
  (test2 result2)
  (else fallback))

;; Loop
(loop body...)                        ;; infinite loop — must contain (suspend)
(while condition body...)
(until condition body...)
(dotimes (i 10) body...)              ;; i from 0 to 9

;; Arithmetic
(+ a b)  (- a b)  (* a b)  (/ a b)
(fabs x)   ;; absolute value float
(fmin a b) ;; min float
(fmax a b) ;; max float
(sqrtf x)  ;; square root

;; Type casting
(the float integer-val)     ;; int → float
(the int float-val)         ;; float → int (truncate)
(the-as type-name val)      ;; reinterpret cast (unsafe, use with care)

;; Boolean
#t   ;; true
#f   ;; false
(not x)
(and a b)
(or a b)
```

---

## Unit System

The engine stores everything in internal units.
**Always use these macros** — never hardcode raw values.

```lisp
;; Distance: 1 meter = 4096 internal units
(meters 5.0)       ;; → 20480.0   (5 meters)
(meters 0.5)       ;; → 2048.0    (half a meter)

;; Rotation: full rotation = 65536 units
(degrees 90.0)     ;; → 16384.0   (quarter turn)
(degrees 180.0)    ;; → 32768.0   (half turn)
(degrees 360.0)    ;; → 65536.0   (full turn)

;; Time: 1 second = 300 ticks (works at both 50 and 60 fps)
(seconds 1)        ;; → 300
(seconds 0.5)      ;; → 150
(seconds 2.5)      ;; → 750
```

---

## Defining a Custom Entity

A custom entity is a `deftype` that inherits from `process-drawable`.
It must have an `init-from-entity!` method and at least one state.

### Minimal "do nothing" entity

```lisp
(deftype my-marker (process-drawable)
  ()
  (:states my-marker-idle))

(defstate my-marker-idle (my-marker)
  :code (behavior () (loop (suspend))))

(defmethod init-from-entity! ((this my-marker) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (go my-marker-idle)
  (none))
```

Place an `ACTOR_my-marker` empty in Blender. It will spawn and sit idle.

### Entity with custom fields

Fields start at offset 176 (end of process-drawable base).
Each field is 4 bytes. Increment offset by 4 per field (8 for 64-bit, 16 for vector/quaternion).

```lisp
(deftype spinning-prop (process-drawable)
  ((spin-speed  float  :offset-assert 176)   ;; radians/tick (use degrees macro)
   (spin-angle  float  :offset-assert 180)   ;; current angle
   (my-flag     symbol :offset-assert 184))  ;; #t or #f
  :heap-base #x70
  :size-assert #xbc                          ;; 176 + 12 bytes of fields, rounded
  (:states spinning-prop-idle))
```

**Offset-assert formula:**
- Start at 176 for first field
- `float`, `int32`, `symbol`, `pointer` → 4 bytes each
- `vector` (inline) → 16 bytes
- `handle` → 8 bytes
- `:size-assert` = last offset + last field size, rounded to nearest 4

See [Offset-Assert Quick Reference](#offset-assert-quick-reference) for a calculator table.

---

## States

States are the state machine for an entity. An entity is always in exactly one state.
Use `(go state-name)` to transition.

### State handlers

```lisp
(defstate my-state (my-type)
  :event    ;; receives events sent to this entity
    (behavior ((proc process) (argc int) (message symbol) (block event-message-block))
      (case message
        (('trigger) (go my-other-state))
        (('die)     (deactivate self))))

  :enter    ;; runs once on entering this state
    (behavior ()
      (sound-play "switch-down"))

  :exit     ;; runs once on leaving this state
    (behavior ()
      (remove-setting! 'allow-look-around))

  :trans    ;; runs every frame BEFORE :code (use for per-frame checks)
    (behavior ()
      (when (and *target*
                 (< (vector-vector-distance (-> self root trans)
                                           (-> *target* control trans))
                    (meters 3.0)))
        (go my-activated-state)))

  :code     ;; main coroutine — must call (suspend) in any loop
    (behavior ()
      (loop
        (suspend)))

  :post     ;; runs every frame AFTER :code (use ja-post for animated entities)
    transform-post)   ;; or: ja-post, rider-post, pusher-post
```

### Common `:post` values

| Value | Use |
|---|---|
| `transform-post` | Non-animated entity that moves (updates collision) |
| `ja-post` | Animated entity with skeleton |
| `rider-post` | Platform that Jak can ride |
| `pusher-post` | Entity that pushes Jak |

### State transitions

```lisp
(go my-state)                    ;; transition to state
(go-virtual my-virtual-state)    ;; transition to overridden state (in subtypes)
(deactivate self)                ;; kill this process entirely
```

---

## The Event System

Events are messages sent between processes. They are the main wiring mechanism.

### Receiving events (in :event handler)

```lisp
:event
  (behavior ((proc process) (argc int) (message symbol) (block event-message-block))
    (case message
      (('trigger)
       ;; sent by trigger volumes, basebutton alt-actor, etc.
       (go my-active-state))
      (('notify)
       ;; sent by some internal engine things
       (format 0 "[my-entity] got notify~%"))
      (('attack)
       ;; Jak attacked/hit this entity
       (go my-hurt-state))
      (('touch)
       ;; Jak touched this entity's collision
       (go my-touched-state))
      (('die)
       (deactivate self))))
```

### Sending events to other entities

```lisp
;; Send to named entity (looked up by entity lump name)
(let ((proc (process-by-ename "door-0")))
  (when proc
    (send-event proc 'trigger)))

;; Send to Jak
(send-event *target* 'reset-height)
(send-event *target* 'launch 16384.0 #f #f 0)   ;; launch Jak into the air

;; Send to camera
(send-event *camera* 'change-to-entity-by-name "cam-marker-0")
(send-event *camera* 'clear-entity)
(send-event *camera* 'teleport)

;; Send with parameters (via block)
(let ((msg (new 'stack-no-clear 'event-message-block)))
  (set! (-> msg from) self)
  (set! (-> msg num-params) 1)
  (set! (-> msg message) 'my-event)
  (set! (-> msg param 0) (the-as uint 42))
  (send-event-function target-proc msg))
```

### Common events reference

| Event | Direction | Effect |
|---|---|---|
| `'trigger` | → entity | Activates doors, buttons, custom handlers |
| `'notify` | → entity | Generic notification (also used by engine) |
| `'attack` | → entity | Damage signal |
| `'touch` | → entity | Collision touch |
| `'die` | → entity | Kill the process |
| `'reset-height` | → `*target*` | Clears Jak's jump height tracking |
| `'change-to-entity-by-name name` | → `*camera*` | Switch to named camera marker |
| `'clear-entity` | → `*camera*` | Revert camera to default |
| `'teleport` | → `*camera*` | Hard-cut camera (no blend) |
| `'cue-chase` | → nav-enemy | Wake enemy, chase Jak |
| `'cue-patrol` | → nav-enemy | Return to patrol |
| `'go-wait-for-cue` | → nav-enemy | Freeze until next cue |

---

## Reading Lumps (Entity Data)

Lumps are key-value pairs stored on each entity-actor. The addon writes them into
the JSONC and they are readable at runtime. Use them to configure per-entity behaviour
from Blender without recompiling code.

```lisp
;; Read a float lump (with fallback default)
(res-lump-float arg0 'my-speed :default 1.0)

;; Read an integer/flag lump
(the int (res-lump-value arg0 'my-flag uint128))

;; Read a string lump
(res-lump-struct arg0 'target-name string)

;; Read entity name (always present)
(res-lump-struct arg0 'name string)

;; Check if a flag lump is nonzero
(!= 0 (the int (res-lump-value arg0 'is-enabled uint128)))
```

### In init-from-entity!

```lisp
(defmethod init-from-entity! ((this my-door) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  ;; Read custom lumps
  (set! (-> this open-speed) (res-lump-float arg0 'open-speed :default 2.0))
  (set! (-> this target-name) (res-lump-struct arg0 'target-name string))
  (go my-door-closed)
  (none))
```

### Standard lump names written by addon

| Lump key | Type | Written for |
|---|---|---|
| `'name` | string | Every actor |
| `'trans` | vector | Every actor position |
| `'quat` | quaternion | Every actor rotation |
| `'bsphere` | vector | Cull sphere (xyz = center, w = radius) |
| `'cam-name` | string | Camera markers |
| `'continue-name` | string | Checkpoint triggers |
| `'target-name` | string | Aggro triggers |
| `'bound-xmin/xmax/ymin/ymax/zmin/zmax` | float | Trigger volume AABB |
| `'path` | inline-array | Waypoint path |
| `'idle-distance` | float | Nav enemy idle range |

---

## Moving Objects

Objects are moved by modifying `(-> self root trans)` each frame.
Always call `transform-post` (or `rider-post`) as the `:post` handler so collision updates.

### Direct position set

```lisp
;; Set absolute position
(set! (-> self root trans x) (meters 10.0))
(set! (-> self root trans y) (meters 2.0))
(set! (-> self root trans z) (meters -5.0))

;; Copy position from another vector
(set! (-> self root trans quad) (-> some-other-vector quad))

;; Move to a computed point
(move-to-point! (-> self root) target-vector)
```

### Lerp / smooth movement

```lisp
;; Linearly interpolate between two vectors (alpha 0.0–1.0)
(vector-lerp! dest-vec start-vec end-vec alpha)

;; Lerp a float
(lerp 0.0 100.0 0.5)           ;; → 50.0

;; Lerp with input remapping (clamped)
;; "when in goes from min-in to max-in, out goes from min-out to max-out"
(lerp-scale 0.0 1.0 current-time 0.0 300.0)   ;; 0→1 over 1 second

;; Seek a float toward target by at most 'rate' per call
(seek! (-> self my-float) target-val rate)

;; Smooth seek with exponential falloff
(seek-with-smooth current target max-step alpha deadband)
```

### Oscillation (example: floating up/down)

```lisp
;; In :trans or :code, each frame:
(let* ((t    (the float (mod (current-time) 300)))   ;; 0–299 repeating
       (frac (/ t 300.0))                             ;; 0.0–1.0
       (y    (* (meters 0.5) (sin (* 65536.0 frac))));; ±0.5m sine wave
  (set! (-> self root trans y) (+ (-> self base-y) y)))
```

### Rotation

```lisp
;; Rotate around Y axis by a delta each frame
(+! (-> self spin-angle) (degrees 1.0))   ;; 1 degree per tick = 60°/sec

;; Apply rotation as quaternion
(quaternion-axis-angle! (-> self root quat) 0.0 1.0 0.0 (-> self spin-angle))

;; Smooth quaternion interpolation (slerp)
(quaternion-slerp! dest-quat quat-a quat-b alpha)

;; Rotate a vector around Y
(vector-rotate-around-y! out-vec in-vec angle-in-degrees-units)
```

### Following a path (waypoints)

```lisp
;; In init-from-entity!, create path from lumps:
(set! (-> this path) (new 'process 'curve-control this 'path -1000000000.0))

;; In :trans, evaluate position along path (pos 0.0 = start, 1.0 = end):
(let ((pos-vec (new 'stack-no-clear 'vector)))
  (eval-path-curve! (-> self path) pos-vec (-> self path-pos) 'interp)
  (move-to-point! (-> self root) pos-vec))

;; Move path-pos toward 1.0 smoothly:
(set! (-> self path-pos)
      (seek-with-smooth (-> self path-pos) 1.0
                        (* 0.1 (seconds-per-frame)) 0.25 0.001))
```

---

## Timing

```lisp
;; Get current frame counter (time-frame integer, 300 ticks/sec)
(current-time)

;; Record a timestamp
(set-time! (-> self state-time))     ;; uses built-in state-time field

;; Check if duration has elapsed since timestamp
(time-elapsed? (-> self state-time) (seconds 2.0))

;; Sleep for a fixed duration (non-blocking — suspends the coroutine)
(suspend-for (seconds 1.5)
  ;; optional: body runs every frame during the wait
  (format 0 "waiting...~%"))

;; Wait for a condition with timeout
(let ((t0 (current-time)))
  (until (or my-condition (time-elapsed? t0 (seconds 5.0)))
    (suspend)))

;; Check frame counter parity (run every 4 frames to reduce cost)
(when (zero? (mod (-> *display* base-frame-counter) 4))
  ;; cheaper per-frame check here
  )
```

---

## Jak / Target Interaction

`*target*` is the global pointer to Jak. Always null-check it first.

```lisp
;; Get Jak's position
(-> *target* control trans)       ;; vector — world position at feet

;; Using helper (node 0 = feet, other indices = bone positions)
(target-pos 0)                    ;; same as above, null-safe

;; Distance from this entity to Jak
(vector-vector-distance (-> self root trans) (-> *target* control trans))

;; Is Jak within N meters?
(when (and *target*
           (< (vector-vector-distance (-> self root trans)
                                      (-> *target* control trans))
              (meters 8.0)))
  (go my-activated-state))

;; XZ only distance (ignores height)
(vector-vector-xz-distance (-> self root trans) (-> *target* control trans))

;; Query Jak's state
(logtest? (-> *target* control status) ...)    ;; check status flags

;; Send event to Jak
(send-event *target* 'reset-height)
```

---

## Sound

Sounds must be in the loaded bank. For custom levels that's the ambient bank
(usually village1 or the level's own SBK).

```lisp
;; Play a one-shot sound by name
(sound-play "darkeco-activate")

;; Play with options
(sound-play "amb-wind"
            :vol 80.0       ;; 0–100
            :pitch 0        ;; semitones * 256, 0 = normal
            :group sfx)     ;; sfx, music, ambient, or voice

;; Play and keep the ID so you can stop it
(let ((sid (new-sound-id)))
  (sound-play "my-loop" :id sid)
  ;; ... later:
  (sound-stop sid))

;; Play at a specific world position (3D positional)
;; Default :position #t already uses self's root trans if called from a process.
;; Pass #f for non-positional (full volume everywhere):
(sound-play "jingle" :position #f)
```

---

## Game Settings

`set-setting!` controls global game state. Settings are per-process and automatically
removed when the process dies (use `remove-setting!` in `:exit` for explicit cleanup).

```lisp
;; Music: change to a named song
(set-setting! 'music 'village1 0.0 0)

;; Volume control (abs = absolute, rel = relative multiplier)
(set-setting! 'music-volume 'abs 0.5 0)    ;; 50% music volume
(set-setting! 'sfx-volume   'abs 0.8 0)    ;; 80% sfx volume
(set-setting! 'ambient-volume 'abs 0.3 0)

;; Letterbox / movie mode (black bars)
(set-setting! 'allow-progress #f 0.0 0)    ;; disable pause menu

;; Look-around lock (fixed camera sequences)
(set-setting! 'allow-look-around #f 0.0 0)
;; Don't forget :exit cleanup:
(remove-setting! 'allow-look-around)

;; Background color/alpha (fog, fade to black, etc.)
(set-setting! 'bg-r 0.0 0.0 0)   ;; red component
(set-setting! 'bg-g 0.0 0.0 0)
(set-setting! 'bg-b 0.0 0.0 0)
(set-setting! 'bg-a 1.0 0.0 0)   ;; 1.0 = fully opaque black overlay

;; Sound flava (changes ambient sound mix)
(set-setting! 'sound-flava #f 20.0 (music-flava assistant))

;; Remove a setting (revert to default)
(remove-setting! 'music-volume)
(remove-setting! 'bg-a)
```

### All valid setting keys

| Key | Effect |
|---|---|
| `'music` | Current music track symbol |
| `'music-volume` | Music volume (abs/rel) |
| `'sfx-volume` | SFX volume (abs/rel) |
| `'ambient-volume` | Ambient volume (abs/rel) |
| `'dialog-volume` | Dialog volume (abs/rel) |
| `'sound-flava` | Sound flava / mix preset |
| `'allow-progress` | Enable/disable pause menu |
| `'allow-pause` | Enable/disable pausing |
| `'allow-look-around` | Enable/disable camera look-around |
| `'bg-r/g/b/a` | Screen overlay RGBA color |
| `'bg-a-speed` | Alpha transition speed |
| `'ocean-off` | Disable ocean rendering |
| `'border-mode` | Camera border mode |
| `'vibration` | Controller vibration |

---

## Skeletal Animation

Skeletal animation requires art assets baked into the level DGO at build time.
The art group name must match the baked `.go` file name exactly.

### Defining a skeleton group

```lisp
;; This declares the art group reference. The strings match filenames in the DGO.
;; my-object        = art group name (my-object-ag.go in the DGO)
;; my-object-lod0-jg = joint geo (the skeleton hierarchy)
;; my-object-idle-ja = default animation
;; meters 20        = LOD switch distance
(defskelgroup *my-object-sg*
  my-object
  my-object-lod0-jg
  my-object-idle-ja
  ((my-object-lod0-mg (meters 20)) (my-object-lod1-mg (meters 999999)))
  :bounds (static-spherem 0 1 0 3))
```

### Playing animations with `ja` macro

```lisp
;; In init-from-entity!, load the skeleton:
(initialize-skeleton this *my-object-sg* '())

;; In :post, call ja-post to evaluate joints every frame:
:post ja-post

;; Play animation once (seek to end)
(ja :group! my-object-open-ja :num! (seek!))

;; Loop animation
(ja :group! my-object-idle-ja :num! (loop!))

;; Advance one frame per tick (manual)
(ja :num! (+!))

;; Wait for animation to finish (use inside :code)
(until (ja-done? 0)
  (suspend)
  (ja :num! (seek!)))

;; Set a specific frame
(ja :group! my-object-idle-ja :num! (identity 0.0))     ;; frame 0
(ja :num! (identity (ja-aframe 15 0)))                  ;; frame 15

;; Blend two animations (channel 0 = base, channel 1 = overlay)
(ja-channel-push! 2 (seconds 0.1))   ;; set 2 channels with 0.1s blend
(ja :chan 0 :group! my-object-walk-ja   :num! (loop!))
(ja :chan 1 :group! my-object-shoot-ja  :num! (loop!) :frame-interp 0.5)
```

### Using `manipy` (puppet type for scripted animation)

`manipy` plays animations on any existing game actor. No custom art needed.

```lisp
;; Spawn a manipy to animate a game mesh at a position
(manipy-spawn
  (-> self root trans)         ;; world position
  (-> self entity)             ;; entity reference (can be #f)
  *babak-sg*                   ;; skeleton group (use an existing game actor's sg)
  #f)                          ;; no special collision

;; Send events to a manipy to control it
(send-event manipy-handle 'anim-mode 'loop)
(send-event manipy-handle 'art-joint-anim babak-idle-ja)
```

---

## Permanent Entity Flags

These flags persist for the current play session (cleared on game-over).

```lisp
;; Mark this entity as dead (won't respawn until reload)
(process-entity-status! self (entity-perm-status dead) #t)

;; Mark as completed (used for doors, power cells, etc.)
(process-entity-status! self (entity-perm-status complete) #t)

;; Check if entity is already dead before spawning
(if (logtest? (-> this entity extra perm status) (entity-perm-status dead))
  (deactivate this))

;; Set a custom user flag (user-set-from-cstage = bit 5)
(logior! (-> this entity extra perm status) (entity-perm-status user-set-from-cstage))

;; Check a custom user flag
(logtest? (-> this entity extra perm status) (entity-perm-status user-set-from-cstage))
```

**All entity-perm-status flags:**

| Flag | Meaning |
|---|---|
| `dead` | Entity is dead, won't re-birth |
| `complete` | Entity/task is complete |
| `real-complete` | Double-complete (for cells etc.) |
| `user-set-from-cstage` | Free user flag |
| `bit-0` through `bit-10` | Raw bit flags, meaning varies |

---

## Wiring Entities Together

### Look up another entity by name

```lisp
;; Get the process running on a named entity
;; "door-0" is the entity lump name (e.g. "ACTOR_jng-iris-door_0" → "jng-iris-door-0")
(let ((door-proc (process-by-ename "jng-iris-door-0")))
  (when door-proc
    (send-event door-proc 'trigger)))
```

### Read a name from a lump (set from addon's Actor Links panel)

```lisp
;; In init-from-entity!:
(set! (-> this linked-name) (res-lump-struct arg0 'alt-actor string))

;; In a state:
(let ((linked (process-by-ename (-> self linked-name))))
  (when linked
    (send-event linked 'trigger)))
```

### Spawning a child process

```lisp
;; Spawn a simple inline process
(let ((proc (get-process *default-dead-pool* process 1024)))
  (when proc
    (activate proc *active-pool* 'child-proc *kernel-dram-stack*)
    (run-next-time-in-process proc
      (lambda ()
        (suspend-for (seconds 2.0))
        (sound-play "explosion")))))
```

---

## Complete Examples

### Example 1: Proximity trigger → sound + camera switch

Plays a sound and switches camera when Jak gets within 5 meters.
Fires once, then goes dormant.

```lisp
(deftype prox-sound-trigger (process-drawable)
  ((cam-name   string :offset-assert 176)
   (fired?     symbol :offset-assert 180))
  :heap-base #x70
  :size-assert #xb8
  (:states prox-sound-trigger-idle prox-sound-trigger-done))

(defstate prox-sound-trigger-idle (prox-sound-trigger)
  :trans
    (behavior ()
      (when (and *target*
                 (< (vector-vector-distance (-> self root trans)
                                            (-> *target* control trans))
                    (meters 5.0)))
        (sound-play "power-on")
        (when (-> self cam-name)
          (send-event *camera* 'change-to-entity-by-name (-> self cam-name)))
        (go prox-sound-trigger-done)))
  :code
    (behavior ()
      (loop (suspend))))

(defstate prox-sound-trigger-done (prox-sound-trigger)
  :code
    (behavior ()
      ;; Mark complete so it doesn't re-fire if level reloads
      (process-entity-status! self (entity-perm-status complete) #t)
      (loop (suspend))))

(defmethod init-from-entity! ((this prox-sound-trigger) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this cam-name) (res-lump-struct arg0 'cam-name string))
  ;; If already fired this session, skip straight to done
  (if (logtest? (-> this entity extra perm status) (entity-perm-status complete))
    (go prox-sound-trigger-done)
    (go prox-sound-trigger-idle))
  (none))
```

---

### Example 2: Continuously rotating object

A prop that spins around its Y axis. Speed is configurable per-object via a lump.

```lisp
(deftype spin-prop (process-drawable)
  ((spin-rate  float :offset-assert 176)   ;; degrees-units per tick
   (angle      float :offset-assert 180))  ;; current angle (accumulates)
  :heap-base #x70
  :size-assert #xb4
  (:states spin-prop-idle))

(defstate spin-prop-idle (spin-prop)
  :trans
    (behavior ()
      ;; Advance angle each frame
      (+! (-> self angle) (-> self spin-rate))
      ;; Apply as quaternion rotation around Y
      (quaternion-axis-angle! (-> self root quat) 0.0 1.0 0.0 (-> self angle)))
  :code
    (behavior ()
      (loop (suspend)))
  :post transform-post)

(defmethod init-from-entity! ((this spin-prop) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  ;; Read spin speed from lump; default = 0.5 degrees/tick = 30°/sec at 60fps
  (set! (-> this spin-rate)
        (res-lump-float arg0 'spin-rate :default (degrees 0.5)))
  (set! (-> this angle) 0.0)
  (go spin-prop-idle)
  (none))
```

In Blender: place `ACTOR_spin-prop`, add a custom lump `spin-rate` = `(degrees 1.0)` for faster spin.

---

### Example 3: Triggered door (listen for 'trigger event)

A simple on/off toggle. Receives `'trigger` to open, `'trigger` again to close.
Combines well with basebutton or a VOL_ trigger volume.

```lisp
(deftype toggle-door (process-drawable)
  ((open-y   float :offset-assert 176)   ;; Y position when open
   (closed-y float :offset-assert 180)   ;; Y position when closed
   (t        float :offset-assert 184))  ;; lerp parameter 0.0 (closed)–1.0 (open)
  :heap-base #x70
  :size-assert #xbc
  (:states toggle-door-closed toggle-door-opening toggle-door-open toggle-door-closing))

(defstate toggle-door-closed (toggle-door)
  :event
    (behavior ((proc process) (argc int) (message symbol) (block event-message-block))
      (case message
        (('trigger) (go toggle-door-opening))))
  :code (behavior () (loop (suspend)))
  :post transform-post)

(defstate toggle-door-opening (toggle-door)
  :code
    (behavior ()
      ;; Slide open over 0.5 seconds
      (until (>= (-> self t) 1.0)
        (set! (-> self t) (fmin 1.0 (+ (-> self t) (* 2.0 (seconds-per-frame)))))
        (set! (-> self root trans y)
              (lerp (-> self closed-y) (-> self open-y) (-> self t)))
        (suspend))
      (go toggle-door-open))
  :post transform-post)

(defstate toggle-door-open (toggle-door)
  :event
    (behavior ((proc process) (argc int) (message symbol) (block event-message-block))
      (case message
        (('trigger) (go toggle-door-closing))))
  :code (behavior () (loop (suspend)))
  :post transform-post)

(defstate toggle-door-closing (toggle-door)
  :code
    (behavior ()
      (until (<= (-> self t) 0.0)
        (set! (-> self t) (fmax 0.0 (- (-> self t) (* 2.0 (seconds-per-frame)))))
        (set! (-> self root trans y)
              (lerp (-> self closed-y) (-> self open-y) (-> self t)))
        (suspend))
      (go toggle-door-closed))
  :post transform-post)

(defmethod init-from-entity! ((this toggle-door) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  ;; closed-y = entity's actual Y; open-y = closed-y + open-height lump
  (set! (-> this closed-y) (-> this root trans y))
  (set! (-> this open-y)
        (+ (-> this closed-y)
           (res-lump-float arg0 'open-height :default (meters 4.0))))
  (set! (-> this t) 0.0)
  (go toggle-door-closed)
  (none))
```

---

### Example 4: Timed sequence (scripted event chain)

Waits for Jak to enter a zone, then runs a timed sequence:
fade to black → sound → camera switch → fade back in.

```lisp
(deftype scripted-sequence (process-drawable)
  ((cam-name  string :offset-assert 176)
   (radius    float  :offset-assert 180))
  :heap-base #x70
  :size-assert #xb4
  (:states scripted-sequence-wait scripted-sequence-run scripted-sequence-done))

(defstate scripted-sequence-wait (scripted-sequence)
  :trans
    (behavior ()
      (when (and *target*
                 (< (vector-vector-xz-distance (-> self root trans)
                                               (-> *target* control trans))
                    (-> self radius)))
        (go scripted-sequence-run)))
  :code (behavior () (loop (suspend))))

(defstate scripted-sequence-run (scripted-sequence)
  :enter
    (behavior ()
      ;; Lock controls and pause menu
      (set-setting! 'allow-progress #f 0.0 0)
      (set-setting! 'allow-look-around #f 0.0 0))
  :exit
    (behavior ()
      (remove-setting! 'allow-progress)
      (remove-setting! 'allow-look-around)
      (remove-setting! 'bg-a))
  :code
    (behavior ()
      ;; 1. Fade to black over 0.5s
      (let ((t0 (current-time)))
        (until (time-elapsed? t0 (seconds 0.5))
          (set-setting! 'bg-a 'abs
                        (lerp-scale 0.0 1.0
                                    (the float (- (current-time) t0))
                                    0.0 (fsec 0.5))
                        0)
          (suspend)))
      (set-setting! 'bg-a 'abs 1.0 0)

      ;; 2. Switch camera and play sound
      (sound-play "secret-found" :position #f)
      (when (-> self cam-name)
        (send-event *camera* 'change-to-entity-by-name (-> self cam-name)))

      ;; 3. Hold for 2 seconds
      (suspend-for (seconds 2.0))

      ;; 4. Revert camera
      (send-event *camera* 'clear-entity)

      ;; 5. Fade back in over 0.5s
      (let ((t1 (current-time)))
        (until (time-elapsed? t1 (seconds 0.5))
          (set-setting! 'bg-a 'abs
                        (lerp-scale 1.0 0.0
                                    (the float (- (current-time) t1))
                                    0.0 (fsec 0.5))
                        0)
          (suspend)))
      (remove-setting! 'bg-a)

      (go scripted-sequence-done)))

(defstate scripted-sequence-done (scripted-sequence)
  :code
    (behavior ()
      (process-entity-status! self (entity-perm-status complete) #t)
      (loop (suspend))))

(defmethod init-from-entity! ((this scripted-sequence) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this cam-name) (res-lump-struct arg0 'cam-name string))
  (set! (-> this radius) (res-lump-float arg0 'radius :default (meters 5.0)))
  (if (logtest? (-> this entity extra perm status) (entity-perm-status complete))
    (go scripted-sequence-done)
    (go scripted-sequence-wait))
  (none))
```

---

### Example 5: Moving platform along a path (no art needed)

Uses waypoints placed in Blender. The empty moves along the path and loops.

```lisp
(deftype my-mover (process-drawable)
  ((path-pos  float :offset-assert 176)   ;; 0.0 to 1.0 along path
   (speed     float :offset-assert 180))  ;; path units per tick
  :heap-base #x70
  :size-assert #xb4
  (:states my-mover-idle))

(defstate my-mover-idle (my-mover)
  :trans
    (behavior ()
      ;; Advance position
      (+! (-> self path-pos) (-> self speed))
      ;; Wrap around at end
      (when (>= (-> self path-pos) 1.0)
        (set! (-> self path-pos) 0.0))
      ;; Move empty to path position
      (let ((pt (new 'stack-no-clear 'vector)))
        (eval-path-curve! (-> self path) pt (-> self path-pos) 'interp)
        (move-to-point! (-> self root) pt)))
  :code
    (behavior ()
      (loop (suspend)))
  :post transform-post)

(defmethod init-from-entity! ((this my-mover) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  ;; Load path from waypoints (addon exports 'path lump)
  (set! (-> this path) (new 'process 'curve-control this 'path -1000000000.0))
  (set! (-> this path-pos) 0.0)
  ;; speed: fraction of full path per tick. 0.003 ≈ one loop per 5 seconds
  (set! (-> this speed) (res-lump-float arg0 'speed :default 0.003))
  (go my-mover-idle)
  (none))
```

In Blender: place `ACTOR_my-mover`, add waypoints, connect them. Optionally add lump `speed`.

---

## Offset-Assert Quick Reference

All custom process-drawable subtypes start fields at offset **176** (0xB0).

| Field type | Size (bytes) | Next offset |
|---|---|---|
| `float` | 4 | +4 |
| `int32` | 4 | +4 |
| `uint32` | 4 | +4 |
| `symbol` | 4 | +4 |
| `string` | 4 | +4 (pointer) |
| `handle` | 8 | +8 |
| `sound-id` | 4 | +4 |
| `time-frame` | 8 | +8 |
| `vector` (inline) | 16 | +16 |
| `quaternion` (inline) | 16 | +16 |

**`:size-assert`** = last offset + last size, round up to multiple of 4.

**`:heap-base`** for simple subtypes of `process-drawable` = `#x70` (standard).
If you have many large fields (vectors/matrices), increase to `#x80` or `#x90`.

**Quick calculation example:**
```
offset 176: string  → 4 bytes → next: 180
offset 180: float   → 4 bytes → next: 184
offset 184: float   → 4 bytes → next: 188
offset 188: symbol  → 4 bytes → next: 192

:size-assert = 192 → hex 0xC0 → write #xc0
```

**Built-in fields (do NOT redeclare):**
- `root` — trsqv (position/rotation/scale + collision)
- `skel` — joint-control (animation)
- `draw` — draw-control
- `path` — path-control (waypoints)
- `state-time` — time-frame (free to use for timing)
- `sound` — ambient-sound

---

## Limitations

### Art assets must be pre-baked
You cannot load new meshes or textures at runtime. Skeletal animation requires the
art group to be in the level DGO. The `initialize-skeleton` call will `go process-drawable-art-error`
and log the issue if the art isn't found.

### No persistent save state
`entity-perm-status` flags survive within a single play session but not across
game-over / save-load. Jak 1 save slots are hardcoded to the base game's task list.

### Compiler error feedback
Build errors from malformed GOAL code appear in the goalc build log, not in Blender.
Common causes:
- Missing `(none)` return at end of `defmethod`
- `offset-assert` values that don't match actual field layout
- Using a function that isn't loaded in the level's DGO context
- Forgetting `(suspend)` inside a `(loop ...)`

### Collision geometry
Custom collision is baked at export time from Blender mesh geometry.
You cannot modify collision shape dynamically at runtime.

### Events to process-drawable enemies
Only nav-enemies (`babak`, `lurker-crab`, `hopper`, `snow-bunny`, `kermit`, etc.)
respond to `'cue-chase`, `'cue-patrol`, `'go-wait-for-cue`.
Process-drawable enemies (yeti, bully, mother-spider) do not have these handlers.
See `knowledge-base/opengoal/enemy-activation.md` for the full list.

---

## Source References

All information sourced from `goal_src/jak1/` in the jak-project repo.

| Topic | Primary source file |
|---|---|
| Unit macros (meters/degrees/seconds) | `engine/util/types-h.gc` |
| Math functions | `engine/math/math.gc`, `engine/math/vector.gc` |
| Trig functions | `engine/math/trigonometry.gc` |
| Timing macros | `engine/gfx/hw/display-h.gc` |
| process-drawable base type | `engine/game/game-h.gc` |
| `ja` animation macro | `engine/common-obs/process-drawable-h.gc` |
| Entity lookup | `engine/entity/entity.gc` |
| Res-lump API | `engine/entity/entity.gc` |
| Sound API | `engine/sound/gsound.gc`, `engine/sound/gsound-h.gc` |
| Settings system | `engine/game/settings.gc` |
| Path/curve control | `engine/geometry/path.gc` |
| manipy puppet | `engine/common-obs/generic-obs.gc` |
| plat-button (moving platform) | `engine/common-obs/plat-button.gc` |
| baseplat (bounce platform) | `engine/common-obs/baseplat.gc` |
| Entity perm flags | `engine/common-obs/process-drawable-h.gc` |
| Example code | `examples/debug-draw-example.gc` |
