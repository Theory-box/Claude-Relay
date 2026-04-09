# OpenGOAL Platform System — Complete Reference

> Extracted from jak-project source. Goal: implement platform creation/control in the Blender addon.

---

## 1. Inheritance Hierarchy

```
process
  └── process-drawable
        ├── baseplat                     ← base for all path/physics platforms
        │     ├── plat                   ← standard moving platform (path + sync)
        │     │     ├── plat-eco         ← blue-eco activated variant
        │     │     │     └── plat-eco-finalboss
        │     │     ├── side-to-side-plat
        │     │     ├── flutflut-plat (+ small/med/large)
        │     │     ├── citb-plat
        │     │     ├── citb-stopbox
        │     │     └── citb-launcher
        │     ├── orbit-plat             ← rotating platform pair (sunken)
        │     ├── square-platform        ← trigger-raised sunken platform
        │     ├── wedge-plat             ← sunken wedge
        │     ├── snow-spatula
        │     └── floating-launcher
        ├── plat-button                  ← elevator/button-press platform
        │     ├── jungle-elevator
        │     ├── sunken-elevator
        │     └── citb-exit-plat
        └── rigid-body-platform          ← physics-simulated floating platform
              ├── balloonlurker
              ├── bone-platform
              ├── tar-plat
              ├── tra-pontoon
              ├── fishermans-boat
              ├── pontoon
              ├── qbert-plat
              ├── ogre-plat / ogre-step / ogre-isle
              └── citb-chain-plat
```

---

## 2. Core Types

### `baseplat` — `engine/common-obs/baseplat.gc`

```lisp
(deftype baseplat (process-drawable)
  ((root      collide-shape-moving :override)
   (smush     smush-control :inline)   ; bounce/smush animation
   (basetrans vector :inline)          ; resting/base position
   (bouncing  symbol)))                ; #t when platform is bouncing
```

**Key behaviors:**
- `plat-trans` — moves platform to `basetrans` or handles bounce; calls `rider-trans`
- `plat-post` — calls `baseplat-method-20` (particle spawning) + `rider-post`
- `plat-event` — handles `'bonk` → triggers smush/bounce
- `plat-code` — basic sleep/wake loop

**Methods to override:**
| Method | Purpose |
|---|---|
| `baseplat-method-20` | Spawn particles at `root trans` |
| `baseplat-method-21` | Init: set `basetrans` from `root trans`, clear bouncing |
| `baseplat-method-22` | Activate bounce (smush amplitude -1.0, 60 rise, 150 fall) |
| `baseplat-method-24` | Set up collision shape (MUST override) |
| `baseplat-method-25` | Create/return particle launch group |
| `baseplat-method-26` | Post-init hook (called before first `go`) |
| `get-unlit-skel`     | Return skeleton group for level-specific visuals |

---

### `plat` — `engine/common-obs/plat.gc`

Extends `baseplat` with path following and sync.

```lisp
(deftype plat (baseplat)
  ((path-pos float)            ; 0.0–1.0 position along path
   (sync     sync-info-eased :inline)
   (sound-id sound-id)))
```

**States:**
- `plat-startup` — checks for path/sync, routes to idle or path-active
- `plat-idle` — stationary (sleeps when not bouncing)
- `plat-path-active` — follows path curve using sync; plays `eco-plat-hover` sound within 80m

**Path movement in `plat-path-active` trans:**
```lisp
;; two modes based on fact-options wrap-phase:
(get-current-phase (-> self sync))          ; wraps 0→1→0→1  (one-way loop)
(get-current-phase-with-mirror (-> self sync)) ; mirrors 0→1→0  (ping-pong)
(eval-path-curve! (-> self path) (-> self basetrans) (-> self path-pos) 'interp)
```

**`init-from-entity!` summary for `plat`:**
```lisp
(logior! (-> this mask) (process-mask platform))  ; REQUIRED
(baseplat-method-24 this)                          ; setup collision
(process-drawable-from-entity! this arg0)
(initialize-skeleton this (get-unlit-skel this) '())
(update-transforms! (-> this root))
(baseplat-method-21 this)                          ; init basetrans
(baseplat-method-25 this)                          ; init particles
(load-params! (-> this sync) this (the-as uint 0) 0.0 0.15 0.15)  ; sync from res
(set! (-> this fact) (new 'process 'fact-info ...))
(set! (-> this path) (new 'process 'curve-control this 'path -1000000000.0))
(logior! (-> this path flags) (path-control-flag display draw-line draw-point draw-text))
(set! (-> this sound-id) (new-sound-id))
;; then go plat-startup
```

**Skeleton groups available:**
- `*plat-sg*` — standard (LOD0=20m, LOD1=40m, LOD2=∞); bounds spherem 0 -0.5 0 3
- `*plat-jungleb-sg*` — jungle B variant (no LODs)
- `*plat-sunken-sg*` — sunken variant; bounds spherem 0 -0.5 0 3.2
- Get-unlit-skel picks these based on current level name

---

### `plat-eco` — `engine/common-obs/plat-eco.gc`

Blue-eco activated platform. Idle until player carries eco or rides it.

```lisp
(deftype plat-eco (plat)
  ((notice-dist      float)       ; res-lump 'notice-dist, default -1 = always active
   (sync-offset-dest float)
   (sync-offset-faux float)
   (sync-linear-val  float)
   (target           handle)
   (unlit-look       lod-set :inline)
   (lit-look         lod-set :inline)))
```

**States:**
- `plat-idle` — unlit look; watches for player eco or riding
- `notice-blue` — ECO proximity animation/smush + glow effect
- `plat-path-active` — lit look; smooth sync offset transition

**Messages handled in idle:**
- `'wake` → immediately go path-active
- `'eco-blue` → go notice-blue state
- `'ridden` / `'edge-grabbed` (with blue eco) → `send-to-all link 'wake` + go path-active

**Init differences from `plat`:**
- Uses `actor-link-info` so linked actors get `'wake`
- Loads sync with default period 3000 instead of 0
- Has separate unlit/lit skeleton groups

---

### `plat-button` — `engine/common-obs/plat-button.gc`

Elevator-style platform. Moves along a path when Jak stands on/touches it.

```lisp
(deftype plat-button (process-drawable)
  ((root                    collide-shape-moving :override)
   (go-back-if-lost-player? symbol)
   (grab-player?            symbol)
   (should-grab-player?     symbol)
   (path-pos                float)
   (bidirectional?          symbol)   ; res 'bidirectional — can go up and down
   (allow-auto-kill         symbol)
   (sound-id                sound-id)
   (trans-off               vector :inline)  ; res 'trans-offset — positional offset
   (spawn-pos               vector :inline)))
```

**States:**
- `plat-button-idle` — waits for `'touch` event on top prims
- `plat-button-pressed` — animates press, routes to move-downward
- `plat-button-move-downward` — smoothly seeks `path-pos` toward 1.0; plays `elev-loop`
- `plat-button-move-upward` — smoothly seeks `path-pos` toward 0.0
- `plat-button-at-end` — landed; plays `elev-land`, returns to idle when player leaves
- `plat-button-teleport-to-other-end` — instant jump (bidirectional reset)

**Path movement formula:**
```lisp
(seek-with-smooth (-> self path-pos) 1.0 (* 0.1 (seconds-per-frame)) 0.25 0.001)
(eval-path-curve! (-> self path) gp-0 f0-4 'interp)
(vector+! gp-0 gp-0 (-> self trans-off))
(move-to-point! (-> self root) gp-0)
```

**Camera integration:** reads `'camera-name` res lump; sends `'change-to-entity-by-name` to `*camera*`.

**Collision — uses prim-group with two meshes:**
```lisp
;; group (index 0): collide-as ground-object, rider-plat-sticky
;; mesh 0 (transform-index 4): top platform surface — what Jak stands on
;; mesh 1 (transform-index 3): base structure
```

**Key res lumps:** `'bidirectional`, `'trans-offset`, `'path`, `'camera-name`

---

### `rigid-body-platform` — `engine/common-obs/rigid-body.gc`

Physics-simulated floating platform (boats, debris, water platforms).

```lisp
(deftype rigid-body-platform-constants (structure)
  ((drag-factor           float)    ; water drag
   (buoyancy-factor       float)    ; upward force
   (max-buoyancy-depth    meters)   ; max submersion for full buoyancy
   (gravity-factor        float)
   (gravity               meters)
   (player-weight         meters)   ; force applied when player stands
   (player-bonk-factor    float)    ; force multiplier for jump-bonk
   (player-dive-factor    float)    ; force for dive/flop
   (player-force-distance meters)
   (player-force-clamp    meters)
   (player-force-timeout  time-frame)
   (explosion-force       meters)
   (linear-damping        float)
   (angular-damping       float)
   (control-point-count   int32)    ; buoyancy sample points (usually 4)
   (mass                  float)
   (inertial-tensor-x/y/z meters)
   (cm-joint-x/y/z        meters)   ; center of mass offset
   (idle-distance         meters)   ; distance to wake from idle
   (platform              symbol)   ; #t = carry player, #f = just physics
   (sound-name            string))) ; played on player impact
```

**Default constants (`*rigid-body-platform-constants*`):**
```
drag=0.8, buoyancy=1.5, max-depth=1.5m, gravity=10m, player-weight=6.6m
bonk=1.0, dive=1.0, force-dist=1000m, force-clamp=1M m, timeout=0.1s
explosion=1000m, lin-damp=1.0, ang-damp=1.0, count=1, mass=2.0
tensor=3/2/3m, idle-dist=50m, platform=#t, sound=#f
```

**States:**
- `rigid-body-platform-idle` — low-power, wakes when player within `idle-distance`
- `rigid-body-platform-float` — active physics; calls `rigid-body-platform-post` each frame

**Physics update per frame:**
```lisp
;; detect-riders! (if platform=#t)
;; accumulate player contact forces
;; simulate: apply buoyancy, gravity, drag per control point
;; integrate rigid body (position + rotation)
;; quaternion-copy to root-overlay
;; rider-post (if platform) or transform-post
```

**Events handled:** `'bonk`, `'attack` (flop/explode), `'impulse`, `'edge-grabbed`, `'ridden`

**Water integration:** links to `water-actor` entity for ripple height via `entity-actor-lookup`.

---

## 3. Collision Setup Pattern

All platforms use this pattern in `baseplat-method-24` / init:

```lisp
(let ((s5-0 (new 'process 'collide-shape-moving this (collide-list-enum hit-by-player))))
  (set! (-> s5-0 dynam) (copy *standard-dynamics* 'process))
  (set! (-> s5-0 reaction) default-collision-reaction)
  (set! (-> s5-0 no-reaction) (the-as (...) nothing))
  (alloc-riders s5-0 1)              ; allocate 1 rider slot (Jak)
  (let ((s4-0 (new 'process 'collide-shape-prim-mesh s5-0 (the-as uint 0) (the-as uint 0))))
    (set! (-> s4-0 prim-core collide-as) (collide-kind ground-object))
    (set! (-> s4-0 collide-with) (collide-kind target))
    (set! (-> s4-0 prim-core action) (collide-action solid rider-plat-sticky))  ; KEY
    (set! (-> s4-0 prim-core offense) (collide-offense indestructible))
    (set! (-> s4-0 transform-index) 0)
    (set-vector! (-> s4-0 local-sphere) 0.0 0.0 0.0 13107.2)  ; radius in units
    (set-root-prim! s5-0 s4-0))
  (set! (-> s5-0 nav-radius) (* 0.75 (-> s5-0 root-prim local-sphere w)))
  (backup-collide-with-as s5-0)
  (set! (-> this root) s5-0))
```

**Critical flags:**
- `(collide-action solid rider-plat-sticky)` — makes Jak "stick" to surface when on it
- `(collide-list-enum hit-by-player)` — standard for player-interactive objects
- `alloc-riders s5-0 1` — without this, Jak won't be carried by the platform

**Local sphere radii used in-game:**
| Platform | Radius (units) | Radius (meters) |
|---|---|---|
| `plat` | 13107.2 | ~3.2 |
| `plat-eco` | 13926.4 | ~3.4 |
| `plat-button` (group) | 27033.6 | ~6.6 |
| `orbit-plat` | 13926.4 | ~3.4 |
| `square-platform` | 32768.0 | 8.0 |
| `side-to-side-plat` | 57344.0 | ~14 |
| `rigid-body-platform` | 20480.0 | 5.0 |

---

## 4. Sync System (Path Timing)

Platforms read timing from the `'sync` res lump: `[period_seconds, phase, out_ease, in_ease]`

### `sync-info-eased` fields:
```lisp
(deftype sync-info-eased (sync-info)
  ((tlo  float)   ; easing-out endpoint (fraction of period)
   (thi  float)   ; easing-in start point
   (ylo  float)   ; y value at tlo
   (yend float)   ; y value at thi
   (m2   float))) ; slope for in-ease
```

### Loading:
```lisp
;; from res lump 'sync: [period_s, phase, out_ease, in_ease]
;; period stored as seconds * 300 internally
(load-params! (-> this sync) this
              (the-as uint 0)    ; default period (0 = no movement)
              0.0                ; default phase offset
              0.15               ; default ease-out fraction
              0.15)              ; default ease-in fraction
```

### Getting current position (0.0–1.0):
```lisp
;; one-way (wrap): 0→1→0→1... (use with fact-options wrap-phase)
(get-current-phase (-> self sync))

;; ping-pong (mirror): 0→1→0→1... but eased
(get-current-phase-with-mirror (-> self sync))
```

### Phase controls:
- `phase` (0.0–1.0): offset into the cycle at spawn — staggers multiple platforms
- `out_ease` (0.0–1.0, default 0.15): fraction of period spent easing out from start
- `in_ease` (0.0–1.0, default 0.15): fraction of period spent easing into end

---

## 5. Res Lump Properties

These properties are read by `init-from-entity!` from the entity's res lump.

| Lump Key | Type | Used By | Notes |
|---|---|---|---|
| `'sync` | float[2–4] | `plat`, `plat-eco` | `[period_s, phase, out_ease, in_ease]` |
| `'path` | curve | all path platforms | Path waypoints; `curve-control` reads this |
| `'notice-dist` | float | `plat-eco` | Distance player noticed at; -1 = always active |
| `'bidirectional` | uint128 | `plat-button` | Non-zero = can go both ways |
| `'trans-offset` | vector | `plat-button` | Additional position offset |
| `'camera-name` | string/struct | `plat-button` | Camera entity to trigger on move |
| `'scale` | float | many | Uniform scale multiplier |
| `'timeout` | float | `orbit-plat`, `square-platform-master` | Seconds before reset/expire |
| `'alt-actor` | entity-actor | many | Linked actor (water, paired platform) |
| `'state-actor` | entity-actor | `eco-door` | Controls locked state |
| `'flags` | int32 | `eco-door` | Bitfield: auto-close, one-way, etc. |
| `'distance` | float[2] | `square-platform` | `[down_offset, up_offset]` from spawn pos |
| `'water-actor` | entity-actor | `rigid-body-platform` | Water volume for buoyancy |

---

## 6. Process Mask

All platforms MUST set:
```lisp
(logior! (-> this mask) (process-mask platform))
```
This tells the engine Jak can ride this process. Without it, `detect-riders!` won't track the player.

Some platforms conditionally clear it:
```lisp
(logclear! (-> this mask) (process-mask platform))  ; jungle vine - disable while swinging
```

---

## 7. Rider System

### How it works:
1. Platform calls `(detect-riders! (-> this root-overlay))` each frame (via `rigid-body-platform-post`) OR the engine handles it through `rider-post`.
2. `rider-trans` moves the platform to its target position.
3. `rider-post` updates all riders (Jak) to follow the platform's motion delta.

### Standard usage in state:
```lisp
:trans (behavior () (plat-trans))   ; moves platform, handles riders
:post  (behavior () (plat-post))    ; particles + rider-post
```

Or directly:
```lisp
:trans rider-trans
:post  rider-post
```

### Manual detect for `rigid-body-platform`:
```lisp
(if (-> self info platform) (detect-riders! (-> self root-overlay)))
;; ... physics update ...
(if (-> self info platform) (rider-post) (transform-post))
```

---

## 8. Notable Platform Variants

### `orbit-plat` (sunken level)
- Paired platforms that orbit a center point
- Player stepping on one signals the other via `entity-actor-lookup 'alt-actor`
- Uses `nav-control` to navigate around obstacles
- Key states: `orbit-plat-idle`, `orbit-plat-rotating`, `orbit-plat-riding`, `orbit-plat-reset`
- Reads `'timeout` (seconds before reset) and `'scale` from res

### `square-platform` (sunken level)
- Triggered by `square-platform-master` sending `'trigger` / `'untrigger`
- Rises/lowers between `down-pos` and `up-pos` (from res `'distance` [down, up] offsets)
- States: `lowered → rising → raised → lowering → lowered`
- Uses `seek-with-smooth` for smooth motion (rate = 1/(0.75 * fps))
- Linked master cycles through platforms with bitmask `plat-mask`

### `plat-flip` (jungleb level)
- Flipping/spinning platform with time limit
- Subtype of nothing special - direct `process-drawable`
- `(logior! (-> this mask) (process-mask platform))` still required

### `wedge-plat` (sunken level)
- Managed by `wedge-plat-master`; individual wedge segments
- Uses `baseplat` directly; master orchestrates motion

### `side-to-side-plat` (sunken level)
- Minimal subtype of `plat` — just overrides `get-unlit-skel` and `baseplat-method-24`
- Larger collision sphere (57344 units ≈ 14m) for wide platform

---

## 9. Common Patterns for Custom Platforms

### Minimal static platform (custom mesh, no movement):
```lisp
(deftype my-platform (baseplat) ())

(defmethod baseplat-method-24 ((this my-platform))
  (let ((s5-0 (new 'process 'collide-shape-moving this (collide-list-enum hit-by-player))))
    (set! (-> s5-0 dynam) (copy *standard-dynamics* 'process))
    (set! (-> s5-0 reaction) default-collision-reaction)
    (set! (-> s5-0 no-reaction) (the-as (...) nothing))
    (alloc-riders s5-0 1)
    (let ((s4-0 (new 'process 'collide-shape-prim-mesh s5-0 (the-as uint 0) (the-as uint 0))))
      (set! (-> s4-0 prim-core collide-as) (collide-kind ground-object))
      (set! (-> s4-0 collide-with) (collide-kind target))
      (set! (-> s4-0 prim-core action) (collide-action solid rider-plat-sticky))
      (set! (-> s4-0 prim-core offense) (collide-offense indestructible))
      (set! (-> s4-0 transform-index) 0)
      (set-vector! (-> s4-0 local-sphere) 0.0 0.0 0.0 13107.2)
      (set-root-prim! s5-0 s4-0))
    (set! (-> s5-0 nav-radius) (* 0.75 (-> s5-0 root-prim local-sphere w)))
    (backup-collide-with-as s5-0)
    (set! (-> this root) s5-0))
  0 (none))

(defmethod init-from-entity! ((this my-platform) (arg0 entity-actor))
  (logior! (-> this mask) (process-mask platform))
  (baseplat-method-24 this)
  (process-drawable-from-entity! this arg0)
  (initialize-skeleton this *my-platform-sg* '())
  (update-transforms! (-> this root))
  (baseplat-method-21 this)
  (go (method-of-object this plat-idle))
  (none))
```

### Moving platform (path-following, same as standard `plat`):
- Provide `'path` res lump (waypoints)
- Provide `'sync` res lump: `[period_seconds, phase_offset]`
- Extend `plat` and override `get-unlit-skel` / `baseplat-method-24`
- No path → goes idle; no sync period → goes idle; both present → goes path-active

### Triggerable platform (rises on event):
- Extend `baseplat`
- Write custom states with enter/exit + `'trigger`/`'untrigger` event handling
- Update `(-> self basetrans)` in trans, call `(plat-trans)` for rider tracking
- Always end state transitions with `(plat-post)` or `(rider-post)`

---

## 10. File Locations

| File | Contents |
|---|---|
| `engine/common-obs/baseplat.gc` | `baseplat`, `eco-door` base types and core behaviors |
| `engine/common-obs/plat.gc` | `plat` type, skeleton groups, standard init |
| `engine/common-obs/plat-eco.gc` | `plat-eco` — blue-eco activated platform |
| `engine/common-obs/plat-button.gc` | `plat-button` — elevator/button platform |
| `engine/common-obs/rigid-body.gc` | `rigid-body-platform` + `rigid-body-platform-constants` |
| `engine/collide/collide-shape-rider.gc` | Rider detection, `alloc-riders`, `detect-riders!` |
| `engine/util/sync-info.gc` | `load-params!`, `setup-params!`, `get-current-phase*` |
| `engine/util/sync-info-h.gc` | Type headers for sync-info variants |
| `levels/sunken/orbit-plat.gc` | Paired orbiting platforms |
| `levels/sunken/square-platform.gc` | Trigger-raised platform + master controller |
| `levels/sunken/wedge-plats.gc` | Wedge segments + master |
| `levels/sunken/sunken-obs.gc` | `side-to-side-plat` |
| `levels/jungleb/plat-flip.gc` | Flipping platform |
| `levels/snow/snow-flutflut-obs.gc` | `flutflut-plat` (small/med/large) |
| `levels/citadel/citb-plat.gc` | Citadel-specific variants including chain-plat |

---

## 11. Addon Implementation Notes

### What to export from Blender for a basic moving platform:

1. **Mesh** — the platform geometry (standard GLB export)
2. **Position/rotation** — spawn point
3. **Path** — list of waypoints as a curve/path object → `'path` res lump
4. **Sync params** — period (seconds), phase (0–1), ease-out (0–1), ease-in (0–1) → `'sync` res lump
5. **Scale** — optional uniform scale → `'scale` res lump

### JSONC lump type tags (confirmed from `goalc/build_level/common/Entity.cpp`):

| Tag | GOAL type | Notes |
|---|---|---|
| `"float"` | `ResFloat` — `vector<float>` | Multiple values allowed: `["float", 4.0, 0.0, 0.15, 0.15]` |
| `"meters"` | `ResFloat` — values × `METER_LENGTH` | Single or multi: `["meters", 20.0]` |
| `"degrees"` | `ResFloat` — values × `DEGREES_LENGTH` | |
| `"vector4m"` | `ResVector` — values × `METER_LENGTH` | Used for path points and spheres |
| `"uint32"` | `ResUInt32` | Integer flags: `["uint32", 1]` |

### Sync res lump format:
```python
# JSONC format for 'sync lump — confirmed working:
# ["float", period_seconds, phase, ease_out, ease_in]
# All 4 floats collected into ResFloat vector<float>
# load-params! in GOAL reads: [0]=period_s, [1]=phase, [2]=out_ease, [3]=in_ease
# If only 2 provided: engine uses 0.15/0.15 defaults for easing
#
# Example: 4s period, no phase offset, default easing:
# "sync": ["float", 4.0, 0.0, 0.15, 0.15]
```

### Movement modes:
- **Ping-pong** (default): platform goes A→B→A→B, eased. Uses `get-current-phase-with-mirror`
- **Loop** (wrap-phase): platform goes A→B→A→B but wraps without mirror. Uses `get-current-phase`. Set via `(fact-options wrap-phase)` on the fact-info.

### Collision sphere sizing rule:
Set `local-sphere` radius ≈ largest horizontal extent of the platform mesh.
- Small platform (~3m radius): 13107.2 units
- Medium platform (~5m radius): 20480.0 units
- Large platform (~14m radius): 57344.0 units
- Formula: `radius_meters * 4096.0 = units`

### process-mask platform — NEVER skip this:
```lisp
(logior! (-> this mask) (process-mask platform))
```
Without this line, Jak will not be carried by the platform.

### alloc-riders — number of slots:
Almost always `1` (only Jak rides). Some platforms use more (multi-character support).

---

## 12. Implemented JSONC Lump Reference (Blender Addon)

Per-actor lump output from the addon at export time. Stored as Blender custom properties on the ACTOR_ empty.

### `plat` / `side-to-side-plat`
```json
"lump": {
  "sync":  ["float", 4.0, 0.0, 0.15, 0.15],
  "path":  ["vector4m", [x,y,z,1], [x,y,z,1], ...],
  "fact-options": ["uint32", 1]   // only if og_sync_wrap=1 (loop mode)
}
```
Custom properties: `og_sync_period` (4.0s), `og_sync_phase` (0.0), `og_sync_ease_out` (0.15), `og_sync_ease_in` (0.15), `og_sync_wrap` (0)

### `plat-eco`
```json
"lump": {
  "sync":         ["float", 4.0, 0.0, 0.15, 0.15],
  "path":         ["vector4m", [x,y,z,1], ...],
  "notice-dist":  ["meters", -1.0],
  "fact-options": ["uint32", 1]   // only if og_sync_wrap=1
}
```
Custom properties: same as plat + `og_notice_dist` (-1.0 = always active, >0 = needs blue eco within Xm)

### `plat-button`
```json
"lump": {
  "path": ["vector4m", [start_x,y,z,1], [end_x,y,z,1]]
}
```
Needs ≥2 waypoints (start position, end position). No sync needed — movement triggered by player contact.


---

## 13. In-Game Test Results (2026-04-09)

Tested in a custom level with one of each platform type spawned standalone.

### Working ✓
- **`plat`** — moves along path with sync, collision correct
- **`plat-eco`** — idles until blue eco, then activates and moves. notice-dist works.
- **`plat-button`** — moves when Jak stands on top

### Broken / Unusable Standalone ✗

**`balance-plat`** (swamp-obs.gc)
- Uses `hit-by-others` collision list instead of `hit-by-player` — Jak passes through it
- Driven by `send-to-all-after/before 'grow` messages via `actor-link-info` chain
- Designed as a linked chain of platforms that communicate — standalone one never receives `'grow`
- Physics exist in code but require a chain partner to function
- **Not fixable from addon side — game design limitation**

**`wall-plat`** (sunken/wall-plat.gc)
- Spawns in `wall-plat-retracted` state, which calls `clear-collide-with-as` at startup
- Collision intentionally disabled until a `'trigger` message extends it
- Requires a separate triggering entity to send `'trigger` — no trigger = stays retracted and passthrough
- **Not fixable from addon side — needs a trigger sender entity**

**`teetertotter`** (misty/misty-teetertotter.gc)
- Has collision (prim-group with sphere + mesh at transform-index 5 and 7)
- Only activates when `target-on-end-of-teetertotter?` passes — checks Jak's position vs animated joints
- Misty-specific, designed for a scripted sequence with specific level geometry
- No-collision in practice because animated joints start in non-collidable positions
- **Level-specific, not suitable for general standalone use**

**`plat-flip`** (jungleb/plat-flip.gc)
- Collision exists (prim-mesh at transform-index 3, solid rider-plat-sticky)
- Spawns in `plat-flip-idle` and reads `'delay` res lump for timing (defaults: 2s down, 0.2s up)
- The "flipping up and down" behaviour IS correct — that is its idle state
- No-collision observation likely because collision mesh starts at an animated position
- JungleB-specific, designed for a timed platforming challenge with specific geometry
- **Works as designed, but not suitable for general platforming**

### Not Yet Tested
- `side-to-side-plat` — sunken level specific, sync-based
- `revcycle` — rotating platform
- `wedge-plat` — sunken level, managed by wedge-plat-master
- `launcher` — floating launcher
- `warpgate` — warp gate
- `plat-button` path travel distance / bidirectional behaviour
- wrap-phase (one-way loop) vs ping-pong on `plat`
- phase staggering across multiple `plat` instances

### Action Items (future)
- Consider adding `standalone_ok: False` flag to ENTITY_DEFS for the broken types
- Add warning info box in Platform panel when a non-standalone-safe type is selected
- Possibly remove broken types from spawn dropdown (or keep with warning)
- `balance-plat` could theoretically work if two are actor-linked — worth testing
- `wall-plat` could work if a trigger volume or script sends `'trigger` — future trigger integration
