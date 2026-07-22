# Particle Effects System — Jak 1 OpenGOAL Custom Levels

A complete reference for how particle effects work in Jak 1, how vanilla places them in levels, and the correct approach for custom level mods.

---

## 1. How Vanilla Places Particle Effects

Every level in Jak 1 that has ambient particle effects (fire, butterflies, waterfalls, fountains, smoke) follows the exact same pattern:

1. A level-specific `.gc` file (e.g. `village1-part.gc`) defines a subtype of `part-spawner`
2. That subtype is a one-liner: `(deftype villagea-part (part-spawner) ())`
3. `defpartgroup` entries in the same file define the visual effects
4. `defpart` entries define the individual particle behaviours
5. Entities of that subtype are placed in the level's binary data with an `art-name` lump pointing to a group name
6. The subtype compiles into the level's DGO alongside everything else

Every single level does this: `villagea-part`, `jungle-part`, `citb-part`, `lavatube-part`, etc. None of them use raw `part-spawner` directly.

**For custom levels:** The addon should generate a `<levelname>-part.gc` file at export time — exactly like the `-obs.gc` stub — containing the subtype definition and any user-defined particle groups. This is the correct, zero-workaround approach.

---

## 2. The part-spawner Entity

`part-spawner` lives in `ENGINE.CGO` (always loaded). It has `init-from-entity!` so it can be placed directly in a JSONC actor list. Its `init-from-entity!` reads one lump:

| Lump | Type | Purpose |
|---|---|---|
| `art-name` | `string` | Name of the `defpartgroup` to spawn (e.g. `"group-village1-pot"`) |

On init, it calls `lookup-part-group-pointer-by-name` which scans `*part-group-id-table*` for a group with that name. If found it starts spawning. If not found it calls `process-drawable-art-error` and dies silently.

`*part-group-id-table*` only contains groups whose DGO has been loaded and executed. This means the `art-name` must match a group defined in a file compiled into your level's DGO — or in ENGINE.CGO/GAME.CGO.

**JSONC placement:**
```json
{
  "trans": [gx, gy, gz],
  "etype": "mymap-part",
  "game_task": "(game-task none)",
  "quat": [0, 0, 0, 1],
  "bsphere": [gx, gy, gz, 30.0],
  "lump": {
    "name": "mymap-part-1",
    "art-name": ["string", "group-mymap-campfire"]
  }
}
```

---

## 3. Particle ID Spaces

Particle IDs must be globally unique across all loaded DGOs. IDs are static — hardcoded at compile time.

### `*part-id-table*` — Individual particle launchers (`defpart`)
- Table size: **3584 slots**
- Vanilla uses up to ID **~2968**
- **Safe range for custom levels: 2969–3583** (~615 free slots)

### `*part-group-id-table*` — Particle groups (`defpartgroup`)
- Table size: **1024 slots**
- Vanilla uses IDs 1–708 (675 groups total, no gaps large enough to use)
- **Safe range for custom levels: 709–1023** (315 free slots)

For an addon managing multiple custom levels, assign ID ranges per level or use a global counter. Collisions between two simultaneously-loaded custom levels cause one to overwrite the other silently.

**Recommended allocation strategy:**
- Reserve IDs 709–800 for Level 1 (up to ~90 particle groups, ~90 defpart entries per slot)
- Reserve IDs 801–900 for Level 2
- Etc.

Since only one custom level is loaded at a time in the current setup, any IDs in the safe ranges will work without conflict.

---

## 4. Always-Available Textures

The `effects` tpage is defined in `engine/data/textures.gc` (ENGINE.CGO) and is always loaded. All textures below are safe to use in any custom level particle effect:

| Texture name | Index | Best for |
|---|---|---|
| `bigpuff` | 0 | Smoke, clouds, fog puffs |
| `e-white` | 1 | Glows, flashes |
| `flare` | 2 | Light flares, sparks |
| `harddot` | 3 | Hard particle dots, embers |
| `middot` | 4 | Medium dots, fireflies |
| `bigpuff2` | 7 | Larger smoke puffs |
| `lakedrop` | 9 | Water droplets, rain |
| `water-wave` | 10 | Water surface rings |
| `lava-part-01` | 11 | Lava/fire embers |
| `hotdot` | 15 | Fire, embers, hot particles |
| `water-splash` | 16 | Water impact splashes |
| `starflash` | 18 | Stars, sparkles, magic |
| `woodchip` | 23 | Wood debris, splinters |
| `falls-particle` | 24 | Waterfall mist |
| `falls-particle-02` | 25 | Waterfall mist variant |
| `rockbit` | 29 | Rock fragments |
| `water-ring` | 30 | Water ripple rings |
| `lightning` | 31 | Lightning bolts |
| `surfacebubble` | 32 | Underwater bubbles |
| `butterfly-wing` | 34 | Butterfly wings |
| `lightning2` | 35 | Lightning variant |
| `lightning3` | 36 | Lightning variant |
| `bigpuff-half` | 41 | Wispy smoke |
| `starflash2` | 53 | Star/sparkle variant |
| `p-white` | 54 | Pure white particles |

**Syntax:** `:texture (bigpuff effects)` — first name is the texture, second is the tpage.

---

## 5. Particle Definition Syntax

### defpartgroup — Defines a named, placeable effect
```lisp
(defpartgroup group-mymap-campfire
  :id 709                              ; unique ID in 709-1023 range
  :bounds (static-bspherem 0 2 0 4)   ; local bounding sphere (x y z radius in meters)
  :parts
  ((sp-item 2969 :fade-after (meters 40) :falloff-to (meters 60))
   (sp-item 2970 :fade-after (meters 30) :falloff-to (meters 50))))
```

**sp-item flags:**
| Flag | Meaning |
|---|---|
| `:fade-after (meters N)` | Start fading at N meters distance |
| `:falloff-to (meters N)` | Fully invisible at N meters |
| `:period (seconds N)` | Repeat cycle period |
| `:length (seconds N)` | How long to emit per cycle |
| `:hour-mask #b...` | 24-bit bitmask, which in-game hours to be active |
| `:binding N` | Bind this item to particle ID N (child particles) |
| `:flags (bit1 start-dead launch-asap)` | Item flags |

### defpart — Defines a single particle launcher
```lisp
(defpart 2969
  :init-specs
  ((:texture (hotdot effects))      ; texture from effects tpage
   (:num 1.0)                       ; particles per frame (float)
   (:x (meters 0))                  ; x offset from emitter
   (:y (meters 0.5))                ; y offset
   (:scale-x (meters 0.2) (meters 0.1))  ; base size + random range
   (:scale-y :copy scale-x)         ; copy from scale-x
   (:r 255.0) (:g 128.0) (:b 0.0)  ; RGB 0-255
   (:a 200.0)                       ; alpha 0-255
   (:vel-y (meters 0.02) (meters 0.01))  ; upward velocity + random
   (:fade-a -1.0)                   ; alpha fade per frame
   (:accel-y (meters -0.0001))      ; gravity
   (:timer (seconds 0.5))           ; particle lifetime
   (:flags (bit2 bit3))             ; render flags
   (:conerot-x (degrees 0) 4 (degrees 10))  ; emission cone
   (:conerot-y (degrees -180) (degrees 360))
   (:conerot-radius (meters 0) (meters 0.2))))
```

**Key init-spec fields:**
| Field | Notes |
|---|---|
| `:texture (name tpage)` | Texture reference |
| `:num N` | Particles emitted per frame |
| `:x/y/z (meters N)` | Position offset |
| `:scale-x/y (meters N)` | Size (can use `:copy scale-x` for second) |
| `:rot-z (degrees N)` | Initial rotation |
| `:r/g/b N` | Color 0.0–255.0 |
| `:a N` | Alpha 0.0–255.0 |
| `:vel-x/y/z (meters N)` | Velocity |
| `:rotvel-z (degrees N)` | Rotation velocity |
| `:scalevel-x/y (meters N)` | Scale velocity (growth rate) |
| `:fade-r/g/b/a N` | Color/alpha fade per frame |
| `:accel-x/y/z (meters N)` | Acceleration (gravity, wind) |
| `:timer (seconds N)` | Particle lifetime |
| `:flags (...)` | Render/behavior flags |
| `:conerot-x/y (degrees N)` | Emission cone angles |
| `:conerot-radius (meters N)` | Emission radius |

**Two-value fields** — many fields accept `(value random-range)`: e.g. `:scale-x (meters 0.5) (meters 0.25)` means 0.5m ± 0.25m random.

---

## 6. Common Effect Recipes

### Campfire / torch flame
```lisp
(defpartgroup group-mymap-torch
  :id 709
  :bounds (static-bspherem 0 2 0 2)
  :parts ((sp-item 2969 :fade-after (meters 40) :falloff-to (meters 60))
          (sp-item 2970 :fade-after (meters 40) :falloff-to (meters 60))))

(defpart 2969  ; orange flame core
  :init-specs ((:texture (hotdot effects)) (:num 2.0) (:y (meters 0))
               (:scale-x (meters 0.3) (meters 0.15)) (:scale-y :copy scale-x)
               (:r 255.0) (:g 100.0 60.0) (:b 0.0) (:a 200.0)
               (:vel-y (meters 0.02) (meters 0.01)) (:fade-a -2.0)
               (:accel-y (meters -0.0002)) (:timer (seconds 0.3))
               (:flags (bit2 bit3)) (:conerot-x (degrees 80)) (:conerot-y (degrees -180) (degrees 360))
               (:conerot-radius (meters 0) (meters 0.1))))

(defpart 2970  ; smoke
  :init-specs ((:texture (bigpuff effects)) (:num 0.1)
               (:y (meters 1)) (:scale-x (meters 0.4) (meters 0.2))
               (:rot-z (degrees 0) (degrees 360)) (:scale-y :copy scale-x)
               (:r 80.0) (:g 80.0) (:b 80.0) (:a 60.0)
               (:vel-y (meters 0.008) (meters 0.004)) (:rotvel-z (degrees -0.1) (degrees 0.2))
               (:scalevel-x (meters 0.002)) (:scalevel-y :copy scalevel-x)
               (:fade-a -0.15) (:accel-y (meters -0.00005)) (:timer (seconds 3))
               (:flags (bit2 bit3)) (:conerot-x (degrees 90)) (:conerot-y (degrees -180) (degrees 360))
               (:conerot-radius (meters 0) (meters 0.2))))
```

### Water drips / cave drip
```lisp
(defpartgroup group-mymap-drip
  :id 710
  :bounds (static-bspherem 0 0 0 2)
  :parts ((sp-item 2971 :fade-after (meters 20) :falloff-to (meters 30))))

(defpart 2971
  :init-specs ((:texture (lakedrop effects)) (:num 0.05)
               (:scale-x (meters 0.05) (meters 0.02)) (:scale-y (meters 0.15) (meters 0.05))
               (:r 100.0) (:g 150.0) (:b 200.0) (:a 180.0)
               (:vel-y (meters -0.05) (meters -0.02)) (:fade-a -3.0)
               (:accel-y (meters -0.003)) (:timer (seconds 0.8))
               (:flags (bit2)) (:conerot-radius (meters 0) (meters 0.05))))
```

### Magical sparkles / eco glow
```lisp
(defpartgroup group-mymap-magic
  :id 711
  :bounds (static-bspherem 0 1 0 3)
  :parts ((sp-item 2972 :fade-after (meters 30) :falloff-to (meters 50))))

(defpart 2972
  :init-specs ((:texture (starflash effects)) (:num 0.3)
               (:y (meters 0.5) (meters 0.5)) (:scale-x (meters 0.1) (meters 0.08))
               (:rot-z (degrees 0) (degrees 360)) (:scale-y :copy scale-x)
               (:r 0.0 128.0) (:g 200.0 55.0) (:b 255.0) (:a 200.0)
               (:vel-y (meters 0.005) (meters 0.005)) (:rotvel-z (degrees 0.5) (degrees -1.0))
               (:fade-a -1.5) (:timer (seconds 1.5))
               (:flags (bit2 bit3)) (:conerot-x (degrees -180) (degrees 360))
               (:conerot-y (degrees -180) (degrees 360))
               (:conerot-radius (meters 0) (meters 1.0))))
```

---

## 7. The Generated Part File Pattern

The addon's export step should write `<levelname>-part.gc` alongside `<levelname>-obs.gc`. Minimal structure:

```lisp
;;-*-Lisp-*-
(in-package goal)
;; <levelname>-part.gc -- auto-generated by OpenGOAL Level Tools

(require "engine/gfx/sprite/sparticle/sparticle.gc")
(require "engine/common-obs/generic-obs-h.gc")

;; Part spawner subtype for this level
(deftype <levelname>-part (part-spawner) ())

;; --- User-defined particle groups below ---
;; (auto-populated from EFFECT_ empties in the Blender scene)

(defpartgroup group-<levelname>-effect-1
  :id 709
  :bounds (static-bspherem 0 1 0 3)
  :parts ((sp-item 2969 :fade-after (meters 40) :falloff-to (meters 60))))

(defpart 2969
  :init-specs (...))
```

This file needs to be:
- Listed in `.gd` as `<levelname>-part.o`
- Listed in `game.gp` as `(goal-src "levels/<name>/<name>-part.gc" "process-drawable")`

Both of these are already handled by the addon's existing export machinery.

---

## 8. Blender Workflow (Planned)

Place `EFFECT_<uid>` empties in Blender. Each empty gets properties:

| Property | Type | Meaning |
|---|---|---|
| `og_effect_group` | string | Which preset group to use (e.g. `campfire`, `smoke`, `sparkle`, `drip`, `custom`) |
| `og_effect_scale` | float | Scale multiplier for the effect radius |
| `og_effect_color_r/g/b` | float 0–255 | Color tint override |
| `og_effect_custom_group` | string | For `custom` mode: exact group name from the generated part file |

At export:
1. Addon collects all `EFFECT_` empties
2. Generates `<levelname>-part.gc` with the subtype + group definitions for each preset used
3. Adds JSONC actors with `"etype": "<levelname>-part"` and `"art-name"` pointing to the generated group name
4. Adds `<levelname>-part.o` to the DGO `.gd` and `game.gp`

---

## 9. File Integration Checklist

When adding a part file to a custom level:

- [ ] `<levelname>-part.gc` created in `goal_src/jak1/levels/<levelname>/`
- [ ] `<levelname>-part.o` added to `dgos/<nick>.gd`
- [ ] `(goal-src "levels/<levelname>/<levelname>-part.gc" "process-drawable")` added to `game.gp`
- [ ] All `defpartgroup :id` values are in range 709–1023
- [ ] All `defpart` IDs are in range 2969–3583
- [ ] JSONC actors use `"etype": "<levelname>-part"` (not `"part-spawner"`)
- [ ] `"art-name"` lump matches a `defpartgroup` name exactly (case-sensitive)
- [ ] `bsphere` radius on the actor is large enough to keep the entity alive at intended view distance

---

## 10. Confirmed Working (Vanilla Reference)

All of the following are confirmed patterns from the vanilla codebase and represent the target for custom level implementation:

| Level | Subtype | Example group | Notes |
|---|---|---|---|
| Village 1 | `villagea-part` | `group-village1-pot` | Fire pot, torch flames |
| Village 1 | `villagea-part` | `group-village1-fountain` | Fountain water |
| Village 1 | `villagea-part` | `group-village1-butterflies` | Ambient butterfly swarms |
| Jungle | `jungle-part` | (various) | Waterfall effects |
| Maincave | `maincave-part` | (various) | Cave drips |
| Training | `training-part` | `group-training-geyser-2` | Geyser steam |
| Citadel | `citb-part` | `group-citb-coil-glow` | Machine glow |

Custom levels should use this same approach — level-specific subtype, group IDs in the 709–1023 range, defpart IDs in the 2969–3583 range.
