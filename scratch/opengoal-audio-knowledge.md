# OpenGOAL Custom Level Audio — Full Knowledge Base
**Research date:** 2025 | **Source:** jak-project source + test-zone.jsonc dissection

---

## 1. Architecture Overview

Sound in OpenGOAL (Jak 1 PC port) runs on a **layered system**:

```
Level loads → sound banks loaded → music bank loaded → ambient entities spawn
                                        ↓
               Per-frame: ambient spheres checked against player pos
                                        ↓
               Overlap → ambient function called (sound/music/flava/hint/etc.)
```

The engine uses **two runtime slots** for level sound banks (`*sound-bank-1*` and `*sound-bank-2*`), plus one always-loaded `common` bank. When the player moves between levels the engine automatically loads/unloads banks.

---

## 2. Level-Info Sound Fields

Every level has a `level-load-info` entry in `goal_src/jak1/engine/level/level-info.gc`. The audio-relevant fields are:

```lisp
(define my-level
  (new 'static 'level-load-info
    :sound-banks '(my-sfx-bank)   ; list of SFX banks to load (symbol names)
    :music-bank  'village1         ; which music file to load (or #f for none)
    :ambient-sounds '()            ; legacy — leave empty, use jsonc ambients instead
    ...))
```

### sound-banks
- References `.sbk` / `.sbank` files baked into the ISO
- For custom levels, you borrow an existing bank (e.g. `'village1`, `'training`)
- The engine will auto-swap banks as the player moves between levels
- Two slots max — if a third level is entered, oldest bank is dropped

### music-bank
- References a music file (e.g. `'village1`, `'beach`, `'jungle`, `#f` for silent)
- Loaded/unloaded by `sound-music-load` / `sound-music-unload` via `settings.gc`
- **For custom levels:** reuse an existing music bank. Common choices:
  - `'village1` — calm, open world feel
  - `'jungle` — adventurous
  - `'beach` — light
  - `'snow` — atmospheric

---

## 3. Ambient System — The Core of Level Audio

Ambients are **sphere-based triggers** embedded in the level. When the player's position overlaps the `bsphere` of an ambient, its function fires each frame.

### Types of Ambients (the `type` lump field)

| Type | Effect |
|------|--------|
| `'sound` | Plays a one-shot or looping SFX at a world position |
| `'music` | Changes the active music and/or flava (variant) |
| `'hint` | Triggers a text/voice hint |
| `'light` | Adjusts lighting |
| `'dark` | Applies dark eco visual effect |
| `'weather-off` | Suppresses weather FX |
| `'ocean-off` | Suppresses ocean |
| `'poi` | Point of interest marker |

### Defining Ambients in `test-zone.jsonc`

The official format (from `custom_assets/jak1/levels/test-zone/test-zone.jsonc`):

```jsonc
"ambients": [
  {
    "trans": [x, y, z, radius],       // world position + trigger radius (meters)
    "bsphere": [x, y, z, radius],     // bounding sphere (same as trans usually)
    "lump": {
      "name": "my-ambient-name",
      "type": "'sound",               // REQUIRED: the ambient type
      // ... type-specific lumps below
    }
  }
]
```

---

## 4. Sound Emitters (Ambient Type: `'sound`)

### One-shot / randomised sound (positive cycle-speed)

```jsonc
{
  "trans": [x, y, z, 10.0],
  "bsphere": [x, y, z, 15.0],
  "lump": {
    "name": "waterfall-sound",
    "type": "'sound",
    "effect-name": ["symbol", "waterfall"],   // sound name in the bank
    "cycle-speed": ["float", 2.0, 1.0]        // [base-seconds, random-seconds]
  }
}
```
- Fires once every `base + rand(0..random)` seconds
- Player must be within `bsphere.w` radius

### Looping sound (negative cycle-speed)

```jsonc
{
  "trans": [x, y, z, 10.0],
  "bsphere": [x, y, z, 25.0],
  "lump": {
    "name": "cave-drip-loop",
    "type": "'sound",
    "effect-name": ["symbol", "drip-water"],
    "cycle-speed": ["float", -1.0, 0.0]   // negative = looping
  }
}
```

### Falloff (volume by distance)

Controlled by `fo-min` and `fo-max` in the `static-sound-spec`, or via `effect-param` lumps. In GOAL code:
```lisp
(static-sound-spec "waterfall" :fo-min 10 :fo-max 80)
; fo-min = inner radius (full volume), fo-max = outer radius (silent)
```

### Multiple random sounds from one emitter

Give `effect-name` multiple values — the engine picks randomly:
```jsonc
"effect-name": ["symbol", "bird-tweet-1", "bird-tweet-2", "bird-tweet-3"]
```

---

## 5. Music Zones (Ambient Type: `'music`)

This is how you change what music plays when Jak enters an area.

```jsonc
{
  "trans": [x, y, z, 50.0],
  "bsphere": [x, y, z, 50.0],
  "lump": {
    "name": "cave-music-zone",
    "type": "'music",
    "music": ["symbol", "maincave"],    // which music bank to switch to
    "flava": ["float", 3.0],            // music variant index (see music-flava enum)
    "priority": ["float", 10.0]         // higher = wins over overlapping zones
  }
}
```

**How it works internally:**  
`ambient-type-music` sets `(-> *setting-control* default music)` and `sound-flava` directly. The settings update loop then calls `sound-music-load` if the music changed.

**Important:** the `music` symbol must match a loaded music bank name. If the bank isn't loaded, nothing plays.

### Music Flava (Variants)

The flava system lets one music bank have multiple variations that fade between each other. The `music-flava` enum values (from `gsound-h.gc`):

```
racer=1, flutflut=2, to-maincave=3, to-snow=4, sage=5, assistant=6,
birdlady=7, mayor=8, sculptor=9, explorer=10, sage-yellow=11,
sage-red=12, sage-blue=13, miners=14, warrior=15, geologist=16,
gambler=17, sage-hut=18, dock=19, farmer=20, jungleb-eggtop=21,
misty-boat=22, misty-battle=23, beach-sentinel=24, beach-cannon=25,
beach-grotto=26, citadel-center=27, robocave=28, robocave-top=29,
maincave=30, darkcave=31, snow-battle=32, snow-cave=33, snow-fort=34,
snow-balls=35, levitator=36, swamp-launcher=37, swamp-battle=38,
jungle-temple-exit=39, jungle-lurkerm=40, jungle-temple-top=41,
rolling-gorge=42, ogre-middle=43, ogre-end=44, lavatube-middle=45,
lavatube-end=46, finalboss-middle=47, finalboss-end=48, default=49
```

The flava-table maps (music-bank, flava-index) → actual variation number. E.g. for `'jungle`, flava `(jungle-temple-exit 1)` switches to variant 1.

---

## 6. Music Changes via GOAL Code (obs.gc approach)

For **trigger-volume-based** music changes, you write a process in your obs.gc that polls Jak's position and calls `set-setting!`:

```lisp
;; In your level's obs.gc or generated obs.gc

(defun my-level-obs-init ()
  (process-spawn-function process
    (lambda ()
      (let ((inside #f))
        (loop
          (when *target*
            (let* ((pos (-> *target* control trans))
                   ;; AABB check for trigger volume
                   (in-vol (and (< -200.0 (-> pos x)) (< (-> pos x) 200.0)
                                (< -100.0 (-> pos z)) (< (-> pos z) 100.0))))
              (cond
                ((and in-vol (not inside))
                 (set! inside #t)
                 ;; Switch music to cave variant
                 (set-setting! 'sound-flava #f 40.0 (music-flava maincave)))
                ((and (not in-vol) inside)
                 (set! inside #f)
                 ;; Remove override, revert to level default
                 (remove-setting! 'sound-flava)))))
          (suspend))))
    :to *entity-pool*)
  (none))
```

The same pattern is used by real game code:
- `rolling-obs.gc` — gorge race switches to `rolling-gorge` flava
- `battlecontroller.gc` — sets `'music` to `'danger` on battle start
- `citadel-sages.gc` — sets `sound-flava` per sage colour

### Setting variants for music

```lisp
;; Set the music bank (changes what file is loaded)
(set-setting! 'music 'village1 0.0 0)

;; Set the flava (variation within that bank)
(set-setting! 'sound-flava #f 40.0 (music-flava sage))

;; Revert
(remove-setting! 'sound-flava)
(remove-setting! 'music)

;; Temporarily mute music (e.g. during a cutscene)
(set-setting! 'music-volume 'abs 0.0 0)
(remove-setting! 'music-volume)  ; restore
```

---

## 7. In-Code Sound Emitters (ambient-sound objects)

For looping 3D sounds attached to processes (moving platforms, water, machines):

```lisp
;; In init-from-entity! of a process:
(set! (-> this sound)
      (new 'process 'ambient-sound
           (static-sound-spec "waterfall" :fo-max 80)  ; sound name + falloff
           (-> this root trans)))                        ; world position

;; Must call every frame in :trans or :code:
(update! (-> self sound))          ; updates position + plays
(stop! (-> self sound))            ; stops it
(update-trans! (-> self sound) new-pos)  ; move it
(update-vol! (-> self sound) 80)         ; change volume (0-100)
```

### static-sound-spec parameters

```lisp
(static-sound-spec "sound-name"
  :num     1.0    ; instance count (polyphony)
  :group   sfx    ; sound group: sfx, music, dialog, ambient
  :volume  100.0  ; volume 0-100
  :pitch-mod 0    ; pitch offset
  :fo-min  0      ; falloff inner radius (full volume within this)
  :fo-max  80     ; falloff outer radius (silent beyond this)
  :mask ()        ; which params to apply
)
```

---

## 8. One-shot Sound Playback

For event sounds (footsteps, collisions, UI, etc.):

```lisp
;; Simple - plays from process position
(sound-play "door-open")

;; With options
(sound-play "cannon-shot" :vol 200 :pitch 2)

;; At specific world position
(sound-play "explosion" :position (the-as symbol world-pos))

;; With sustained ID (for looping or stopping later)
(sound-play "engine-idle" :id (-> self sound-id))
(sound-stop (-> self sound-id))

;; Play by dynamic name
(sound-play-by-name (string->sound-name "my-sound")
                    (new-sound-id) 1024 0 0 (sound-group sfx) #t)
```

---

## 9. Can We Use Trigger Volumes to Change Music?

**YES — confirmed. Two methods:**

### Method A: Ambient sphere (jsonc — simplest)
Place a `'music` ambient in your jsonc. When Jak enters the bsphere, the music/flava changes. The sphere is always active as long as the level is loaded.

```jsonc
{
  "trans": [-50.0, 5.0, 0.0, 30.0],   // 30m radius sphere
  "bsphere": [-50.0, 5.0, 0.0, 30.0],
  "lump": {
    "name": "cave-entrance-music",
    "type": "'music",
    "music": ["symbol", "maincave"],
    "flava": ["float", 30.0],
    "priority": ["float", 10.0]
  }
}
```

### Method B: GOAL trigger process (obs.gc — more control)
Write a process in your `{level}-obs.gc` that uses an AABB or sphere check and calls `set-setting!`. This lets you:
- Use rectangular trigger volumes (not just spheres)
- Chain conditions (e.g. only trigger after a task is complete)
- Transition between multiple zones
- Stop/restart the sound under GOAL control

Both the Blender addon camera trigger system and the battle controller use this exact pattern.

---

## 10. Sound Bank Names (Borrowable for Custom Levels)

These are the banks in the base game you can reference:

| Bank symbol | Level | Contents |
|-------------|-------|----------|
| `'training` | Training | basic SFX |
| `'village1` | Sandover | village, general outdoor |
| `'beach` | Sentinel Beach | ocean, beach SFX |
| `'jungle` | Forbidden Jungle | jungle, temple |
| `'misty` | Misty Island | boat, fog SFX |
| `'firecanyon` | Fire Canyon | fire, vehicle |
| `'village2` | Rock Village | village 2 SFX |
| `'sunken` | Lost Precursor City | water, bubbles |
| `'swamp` | Boggy Swamp | swamp, frogs |
| `'rolling` | Snowy Mountain (rolling) | rolling race SFX |
| `'ogre` | Lost Precursor / Ogre boss | battle |
| `'village3` | Mountain Pass area | cave, mine |
| `'snow` | Snowy Mountain | snow, ice |
| `'maincave` | Spider Cave | cave drips, darkness |
| `'darkcave` | Dark Cave (sub-level) | very dark cave |
| `'robocave` | Spider Cave B | mechanical cave |
| `'lavatube` | Lava Tube | fire, lava |
| `'citadel` | Gol's Citadel | ominous, mechanical |
| `'finalboss` | Final Boss | combat |

---

## 11. Reverb

```lisp
;; Set reverb type and intensity
(sound-set-reverb reverb-type left-volume right-volume core)
;; e.g. cave-like reverb on core 0:
(sound-set-reverb 5 0.8 0.8 0)
```

The reverb types are IOP-defined integers. Cave-type reverbs are approximately 4-6 based on PS2 SPU2 presets.

---

## 12. Volume Channels

The game has separate volume sliders for:
- `'sfx-volume` — sound effects
- `'music-volume` — background music  
- `'ambient-volume` — ambient sounds
- `'dialog-volume` — voice lines

You can temporarily override these:
```lisp
(set-setting! 'music-volume 'rel 0.5 0)   ; halve music volume
(set-setting! 'music-volume 'abs 0.0 0)   ; silence music
(remove-setting! 'music-volume)            ; restore default
```

---

## 13. Practical Guide — Adding Music to a Custom Level

### Step 1: Set level-info in `level-info.gc`

```lisp
(define my-level
  (new 'static 'level-load-info
    ...
    :sound-banks '(village1)   ; borrow village1 SFX bank
    :music-bank  'village1     ; play village1 music by default
    ...))
```

### Step 2: Add music zones to `my-level.jsonc`

```jsonc
"ambients": [
  {
    "trans": [0.0, 5.0, 0.0, 100.0],
    "bsphere": [0.0, 5.0, 0.0, 100.0],
    "lump": {
      "name": "main-area-music",
      "type": "'music",
      "music": ["symbol", "village1"],
      "flava": ["float", 5.0],
      "priority": ["float", 5.0]
    }
  },
  {
    "trans": [200.0, 0.0, 0.0, 40.0],
    "bsphere": [200.0, 0.0, 0.0, 40.0],
    "lump": {
      "name": "cave-music-zone",
      "type": "'music",
      "music": ["symbol", "maincave"],
      "flava": ["float", 31.0],
      "priority": ["float", 20.0]
    }
  }
]
```

### Step 3: Add ambient sound emitters

```jsonc
{
  "trans": [50.0, 2.0, 30.0, 20.0],
  "bsphere": [50.0, 2.0, 30.0, 20.0],
  "lump": {
    "name": "waterfall-sfx",
    "type": "'sound",
    "effect-name": ["symbol", "waterfall"],
    "cycle-speed": ["float", -1.0, 0.0]
  }
}
```

### Step 4 (optional): GOAL trigger in obs.gc

For precise rectangular trigger zones:

```lisp
;; In your {level}-obs.gc:
(defun my-level-obs-init ()
  (process-spawn-function process
    (lambda ()
      (let ((inside-cave #f))
        (loop
          (when *target*
            (let* ((pos (-> *target* control trans))
                   (in-cave (and (< 150.0 (-> pos x)) (< (-> pos x) 300.0)
                                 (< -50.0 (-> pos z)) (< (-> pos z) 50.0))))
              (cond
                ((and in-cave (not inside-cave))
                 (set! inside-cave #t)
                 (set-setting! 'music 'maincave 0.0 0)
                 (set-setting! 'sound-flava #f 40.0 (music-flava darkcave)))
                ((and (not in-cave) inside-cave)
                 (set! inside-cave #f)
                 (remove-setting! 'sound-flava)
                 (set-setting! 'music 'village1 0.0 0)))))
          (suspend))))
    :to *entity-pool*)
  (none))
```

---

## 14. Custom Sound Files (Future Work)

Currently for custom levels you can only use sounds already in the game's `.sbk` banks. Adding custom audio would require:

1. **Creating a new `.sbk` sound bank** — tool TBD, needs OVERLORD format research
2. **Adding the bank to your level's `.gd` file** — alongside art groups
3. **Referencing via** `:sound-banks '(my-custom-bank)` in level-info
4. **Placing the bank file** in the appropriate ISO location

This is a future research area. For now, all named sounds must be strings that exist in whatever banks you've loaded.

---

## 15. Known Sound Names (Common Banks)

A partial list of sounds from borrowed banks useful for level ambience:

**From `village1` / general:**
- `"waterfall"`, `"water-drop"`, `"fire-pop"`, `"drip-on-wood"`
- `"warpgate-tele"`, `"warpgate-act"`

**From `training`/`village1` (outdoor):**
- `"geyser"`, `"break-dummy"`, `"welding-loop"`

**From `maincave`/`darkcave` (cave):**
- `"crystal-on"`, `"drip-water"`

**From `beach`:**
- `"seagulls-2"`, `"gears-rumble"`

**From `village3`:**
- `"steam-short"`, `"gdl-gen-loop"`, `"gdl-start-up"`

**From `citadel`:**
- `"mushroom-gen"`, `"rotate-plat"`, `"robotcage-lp"`, `"sagecage-gen"`

---

## 16. Key Source Files for Reference

| File | Purpose |
|------|---------|
| `goal_src/jak1/engine/sound/gsound-h.gc` | All types, enums, macros — start here |
| `goal_src/jak1/engine/sound/gsound.gc` | All sound functions + flava table |
| `goal_src/jak1/engine/entity/ambient.gc` | All ambient types including `'music` and `'sound` |
| `goal_src/jak1/engine/level/level-info.gc` | Per-level sound-bank + music-bank declarations |
| `goal_src/jak1/engine/game/settings.gc` | How music/flava settings are processed |
| `goal_src/jak1/levels/rolling/rolling-obs.gc` | Trigger volume flava switch example |
| `goal_src/jak1/levels/common/battlecontroller.gc` | Danger music on battle start/end |
| `custom_assets/jak1/levels/test-zone/test-zone.jsonc` | Official ambient jsonc format with comments |
