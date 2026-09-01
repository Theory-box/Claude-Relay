# OpenGOAL Jak 1 — Audio System Knowledge Base

Researched from `goal_src/jak1/` source. Last updated: April 2026.

---

## How the Sound System Works

### Sound Banks (`:sound-banks`)
- Loaded from `level-load-info` by `update-sound-banks()` in `level.gc`
- Maps to `.sbk` binary files on disk (e.g. `beach` → `beach.sbk`)
- **Maximum 2 simultaneous sound banks** — a 3rd triggers a console error
- The engine loads/unloads banks automatically as levels become active
- `common.sbk` is always loaded at boot (engine sounds, UI, footsteps etc.)

**Valid bank names (one per level):**
`village1`, `beach`, `jungle`, `jungleb`, `misty`, `firecanyon`, `village2`,
`sunken`, `swamp`, `rolling`, `ogre`, `village3`, `snow`, `maincave`,
`darkcave`, `robocave`, `lavatube`, `citadel`, `finalboss`

**Usage in level-load-info:**
```
:sound-banks '(beach)          ; one bank
:sound-banks '(beach village1) ; two banks (max)
```

---

## How Music Works

`:music-bank` on `level-load-info` serves two roles:
1. **Level activation** (`main.gc` line 392) — sets the default music when the level first becomes active
2. **Player death/respawn** (`target-death.gc`) — resets music back to this value after a death

So it *does* drive initial music playback — setting it to e.g. `'village1` will start that music when the level loads.

### The real music chain:
1. A `set-setting! 'music '<bank-symbol> 0.0 0` call sets the active music
2. `settings.gc` detects the change and calls `sound-music-load` with that name
3. The `*flava-table*` maps the music symbol + a `music-flava` enum → a variant index
4. `sound-set-flava` switches between sub-area variations (e.g. combat, boss, NPC proximity)

### Music is triggered by:
- **Ambient entities** with `type = 'music` lump (placed in 3D space)
- **NPC/entity code** setting `sound-flava` on their process (e.g. talking to a sage)
- **Battle controllers** switching to `'danger` music
- **Boss fights** overriding to specific flavas

### Music bank → flava table mapping
```
village1  → sage, assistant, birdlady, farmer, mayor, sculptor, explorer, dock, sage-hut
jungle    → jungle-temple-exit, jungle-lurkerm, jungle-temple-top
firecanyon→ racer
jungleb   → jungleb-eggtop
beach     → birdlady, beach-sentinel, beach-cannon, beach-grotto
misty     → racer, misty-boat, misty-battle
village2  → sage, assistant, warrior, geologist, gambler, levitator
swamp     → flutflut, swamp-launcher, swamp-battle
rolling   → rolling-gorge
ogre      → ogre-middle, ogre-end
village3  → to-maincave, to-snow, sage, assistant, miners
maincave  → robocave, robocave-top, maincave, darkcave
snow      → flutflut, snow-battle, snow-cave, snow-fort, snow-balls
lavatube  → lavatube-middle, lavatube-end, default
citadel   → sage, assistant, sage-yellow, sage-red, sage-blue, citadel-center
finalboss → finalboss-middle, finalboss-end
credits   → default
```

---

## Ambient Entity Types (from `ambient.gc`)

The `entity-ambient` system supports these `type` lump values:

| Type | What it does |
|---|---|
| `'hint` | Dialogue hint popup (text-id lump) |
| `'sound` | Plays a sound effect by `effect-name` when player is in range |
| `'music` | Sets `'music` setting + `flava` when player is in range |
| `'poi` | Point of interest label |
| `'dark` | Dark eco effect |
| `'weather-off` | Disables weather in zone |
| `'ocean-off` | Disables ocean in zone |
| `'ocean-near-off` | Disables near ocean in zone |

### Sound ambient lump format (type `'sound`):

**One-shot / randomised** (positive `cycle-speed`):
```jsonc
"lump": {
  "name": "my-ambient",
  "type": "'sound",
  "effect-name": ["symbol", "thunder"],      // sound name from a loaded bank
  "cycle-speed": ["float", 3.0, 2.0]         // fires every 3-5s (base + rand)
}
```

**Looping** (negative `cycle-speed`):
```jsonc
"lump": {
  "name": "waterfall-loop",
  "type": "'sound",
  "effect-name": ["symbol", "waterfall"],
  "cycle-speed": ["float", -1.0, 0.0]        // negative = continuous loop
}
```

**Multiple random sounds from one emitter** — give `effect-name` multiple values, engine picks randomly:
```jsonc
"effect-name": ["symbol", "bird-1", "bird-2", "bird-3"]
```

`effect-name` uses the `["symbol", ...]` array lump format — **not** a bare string like `"'thunder"`.

### ⚠️ Known Bug: One-shot (`cycle-speed >= 0`) crashes on player proximity

**Root cause confirmed from source** (`ambient.gc` + `res.gc` + `ResLump.cpp`):

The C++ level builder writes all lump tags at `key_frame = -1000000000.0` (`DEFAULT_RES_TIME`).  
In `birth-ambient!`, the one-shot path calls:
```lisp
(lookup-tag-idx this 'effect-name 'exact 0.0)
```
`'exact` mode requires `key_frame == 0.0` exactly. The tag is at `-1e9`. **It never matches.**  
Result: tag index = `-1`, count stays `0`, then `(rand-vu-int-count 0)` = undefined behaviour / crash.

**The looping path does NOT have this bug.** It uses `res-lump-struct` (interp mode) which accepts `-1e9` tags as valid matches.

### ✅ Working: Looping sound emitter

Use a **negative** first value in `cycle-speed`. This routes through `ambient-type-sound-loop` which avoids the broken `lookup-tag-idx 'exact` call entirely:

```jsonc
{
  "trans": [0.0, 5.0, 0.0, 10.0],
  "bsphere": [0.0, 5.0, 0.0, 20.0],
  "lump": {
    "name": "waterfall-loop",
    "type": "'sound",
    "effect-name": ["symbol", "waterfall"],
    "cycle-speed": ["float", -1.0, 0.0]
  }
}
```

**Limitations of the loop path:**
- Single sound name only — multiple symbols are ignored (loop path reads first symbol only)
- Sound loops continuously while player is in bsphere — no randomised timing

### ✅ Alternative: obs.gc `sound-play` via trigger volume

For one-shot sounds, randomised sounds, or anything more complex — use the GOAL trigger pattern in obs.gc. Bypasses the ambient system entirely and has no known bugs:

```lisp
;; In obs.gc trigger process:
(sound-play "thunder")
(sound-play "waterfall" :id (-> self sound-id))  ; for stoppable loops
```

### Music ambient lump format (type `'music`):
```jsonc
"lump": {
  "name": "my-music-zone",
  "type": "'music",
  "music": ["symbol", "village1"],   // music bank to activate
  "flava": ["float", 5.0],           // flava variant index (see flava table above)
  "priority": ["float", 10.0]        // higher priority wins when zones overlap
}
```

The `priority` lump is important when two music zones overlap — the higher value wins. Vanilla game uses values around 10.0 for normal zones, 40.0 for race/boss overrides.

`'danger` is a special music bank name used by battle controllers to trigger a distinct combat track — it works like any other bank name in the `'music` setting.

---

## Known Sound Effect Names (212 total)
Sourced from `sound-play` calls across all 533 `.gc` files.

```
aphid-spike-in, aphid-spike-out, arena-steps, b-eco-pickup, barrel-bounce,
barrel-roll, beam-connect, bfg-fire, bigshark-alert, bigshark-bite,
bigshark-idle, blob-explode, blob-jump, blob-land, blob-out, blue-eco-on,
blue-eco-start, boat-engine, bomb-open, boulder-splash, break-dummy,
bridge-piece-dn, bridge-piece-up, bully-bounce, bumper-pwr-dwn, buzzer-pickup,
cannon-charge, cannon-shot, caught-eel, cell-prize, close-orb-cash,
close-racering, cool-balloon, cool-rolling-st, crate-jump, crystal-explode,
cursor-l-r, cursor-options, cursor-up-down, darkvine-grow, darkvine-kill,
darkvine-move, dcrate-break, death-darkeco, death-drown, death-fall,
death-melt, dirt-crumble, door-lock, door-unlock, eco-plat-hover, eco-torch,
eco-tower-rise, eco-tower-stop, egg-hit, eggs-lands, electric-loop, elev-land,
elev-loop, eng-shut-down, eng-start-up, explod-bomb, explod-eye, explosion,
falling-bones, fish-miss, fish-spawn, flop-land, flut-coo, flut-flap, flut-hit,
g-eco-pickup, gdl-start-up, gears-rumble, get-all-orbs, get-big-fish,
get-blue-eco, get-burned, get-green-eco, get-red-eco, get-shocked,
get-small-fish, get-yellow-eco, gnawer-dies, green-fire, grotto-pole-hit,
head-butt, hit-up, hot-flame, ice-explode, ice-loop, ice-stop, icrate-break,
icrate-nobreak, irisdoor2, jngb-eggtop-seq, jump, jump-long, kermit-loop,
kermit-stretch, land-grass, land-pcmetal, launch-fire, launch-idle,
launch-start, lay-eggs, ldoor-close, ldoor-open, lodge-close, magma-rock,
maindoor, menu-close, menu-stats, mirror-smash, money-pickup, mother-fire,
mother-hit, mother-track, ogre-boulder, ogre-explode, ogre-fires, ogre-grunt1,
ogre-grunt2, ogre-grunt3, ogre-rock, oof, open-orb-cash, pedals, pill-pickup,
plant-leaf, plat-flip, plat-light-off, plat-light-on, prec-button1,
prec-button8, propeller, pu-powercell, puppy-bark, r-eco-pickup, ramboss-charge,
ramboss-fire, ramboss-hit, ramboss-track, rat-eat, rat-gulp, red-explode,
red-fire, robo-warning, robotcage-off, rock-break, rock-in-lava, sack-incoming,
sack-land, sagecage-off, sagecage-open, scrate-break, scrate-nobreak,
seagull-takeoff, select-menu, select-option, set-ram, silo-button, site-moves,
slam-crash, slide-loop, slider2001, smack-surface, snow-spat-long,
snow-spat-short, snowball-land, snowball-roll, start-options, starts-options,
stopwatch, sunk-top-falls, sunk-top-lands, sunk-top-rises, swim-stroke,
telescope, thunder, trampoline, uppercut, v2ogre-boulder, vent-switch,
wall-plat, warning, warpgate-act, warpgate-butt, warpgate-tele, water-drop,
water-explosion, water-off, water-on, wcrate-break, web-tramp, welding-loop,
worm-rise1, y-eco-pickup, yellow-buzz, yellow-explode, yellow-fire,
yellow-fizzle, zoom-boost, zoomer-crash-2, zoomer-explode, zoomer-jump,
zoomer-loop, zoomer-melt, zoomer-rev1, zoomer-rev2, zoomer-start, zoomer-stop
```

---

## Trigger Volume Music Switching via GOAL (obs.gc)

For precise rectangular trigger zones (vs sphere-only ambients), write a process in your `{level}-obs.gc` that polls Jak's position and calls `set-setting!`. This is the same AABB polling pattern used for camera triggers.

```lisp
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
                 (set-setting! 'sound-flava #f 40.0 (music-flava darkcave)))
                ((and (not in-cave) inside-cave)
                 (set! inside-cave #f)
                 (remove-setting! 'sound-flava)))))
          (suspend))))
    :to *entity-pool*)
  (none))
```

### Useful `set-setting!` calls for music:

```lisp
;; Switch the entire music bank
(set-setting! 'music 'maincave 0.0 0)

;; Switch to a flava variant (priority 40.0 overrides normal zones)
(set-setting! 'sound-flava #f 40.0 (music-flava rolling-gorge))

;; Temporarily silence music (e.g. cutscene)
(set-setting! 'music-volume 'abs 0.0 0)

;; Revert any of the above
(remove-setting! 'sound-flava)
(remove-setting! 'music)
(remove-setting! 'music-volume)
```

Real game examples using this pattern:
- `rolling-obs.gc` — gorge race switches to `rolling-gorge` flava on race start, removes on exit
- `battlecontroller.gc` — sets `'music` to `'danger` when battle begins, removes when enemies cleared
- `citadel-sages.gc` — sets `sound-flava` per sage colour (red/blue/yellow)

---

## Which Bank Does a Sound Come From?

The 212 names sourced from `sound-play` calls span multiple banks. For sounds to play they need their bank loaded. See `sbk-sound-contents.md` for the full per-bank breakdown (1,048 sounds total).

**Quick rule:** `common.sbk` (461 sounds, always loaded) covers all footsteps, eco pickups, UI, Jak's voice, most enemy sounds, and general SFX. Level banks add area-specific ambience on top.

Sounds safe to use in any custom level (always in `common`): `waterfall`, `water-drop`, `explosion`, `cell-prize`, `money-pickup`, `buzzer-pickup`, `jump`, `land-grass`, `land-pcmetal`, `eco-plat-hover`, `warpgate-tele`, `door-lock`, `door-unlock`, `select-menu`, `cursor-up-down`.

---

## Blender Addon — Current State (confirmed working April 2026)

### ✅ Working
- **Sound emitters** — place via Audio panel → Pick sound → Add Emitter at Cursor
  - Exports as `type='sound` ambient with `effect-name=["symbol","name"]` and `cycle-speed=["float",-1.0,0.0]`
  - Looping mode (`cycle-speed < 0`) confirmed working in-game
- **Sound bank dropdowns** — Bank 1 + Bank 2, max 2 loaded simultaneously
  - Exports as `:sound-banks '(bank1 bank2)` — GOAL list-of-symbols syntax
  - Correct syntax is `'(beach village1)` NOT `'('beach 'village1)` (common bug)
- **Music bank dropdown** — exports as `:music-bank 'village1`
  - Sets music on level load AND resets after player death
- **Sound picker** — searchable popup over all 1048 sounds from actual .SBK files
- **Live sound count** — panel shows common + level bank sounds available

### ❌ Known broken: one-shot sound ambients
- `cycle-speed >= 0` (one-shot/interval) crashes game on bsphere entry
- Root cause: `birth-ambient!` calls `lookup-tag-idx 'exact 0.0` but C++ builder
  writes all tags at `DEFAULT_RES_TIME = -1e9` — exact match never fires,
  count stays 0, `rand-vu-int-count(0)` crashes
- **Workaround**: use loop mode, or use obs.gc `sound-play` trigger

### Notes
- `ambient-sounds` list in level-load-info is unused by all vanilla levels — ignore it
- `effect-name` lump must use `["symbol", ...]` array format, not a bare string
- Sound names must exist in a loaded bank — `common` bank always loaded (461 sounds)

---

## Blender Addon — Music Zone System (confirmed working April 2026)

### How to trigger music in a custom level

`:music-bank` in `level-load-info` alone does NOT start music. It only resets
music after player death. Music requires a `type='music` ambient entity — when
the player enters its bsphere the engine calls `set-setting! 'music '<bank>`.

**Standard setup:** one large music zone covering the whole level.

### Placing a music zone (Blender addon)

1. **Spawn > 🎵 Music Zones** — set bank, flava (optional), priority, radius
2. Click **Add Music Zone at Cursor** — places a gold `AMBIENT_mus001` sphere
3. Select the empty → **Selected Object > Music Zone** — edit any field:
   - Click **Bank** button → searchable popup of all 19 banks
   - Click **Flava** button → searchable popup filtered to that bank's variants
   - **Priority** / **Radius** — direct number inputs
4. Export & build — the zone appears in the level JSONC `ambients` array

### Exported JSONC format (confirmed working)

```jsonc
{
  "trans":   [x, y, z, radius],
  "bsphere": [x, y, z, radius],
  "lump": {
    "name":        "mus001",
    "type":        "'music",
    "music":       ["symbol", "village1"],
    "flava":       ["float", 0.0],
    "priority":    ["float", 10.0],
    "effect-name": ["symbol", "village1"]
  }
}
```

`music` is a ResSymbol — the GOAL symbol `'village1` passed to `set-setting!`.
`flava` is a ResFloat — the integer index into `*flava-table*` for that bank (0 = default).
`effect-name` is included defensively (listed in the lump quick-ref for music ambients).
`priority` — vanilla normal zones use 10.0, boss/race overrides use 40.0.
