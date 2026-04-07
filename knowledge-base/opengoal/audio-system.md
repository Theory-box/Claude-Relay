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

`:music-bank` on `level-load-info` does **not** directly play music.
It is only read during **player death/respawn** (`target-death.gc`) to reset music to the level default.

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
```json
"lump": {
  "name": "my-ambient",
  "type": "'sound",
  "effect-name": "'thunder",
  "volume": 1.0,
  "play-mode": "'ambient"
}
```

### Music ambient lump format (type `'music`):
```json
"lump": {
  "name": "my-music-zone",
  "type": "'music",
  "music": 0.0,
  "flava": 1.0
}
```
*(music/flava are stored as floats — actual symbol lookup happens at runtime)*

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

## Implications for the Blender Addon

### What works now:
- `:sound-banks` — loads audio banks, use 1-2 names from the valid list above
- `:music-bank` — sets the respawn-default music (minor but worth setting correctly)
- Sound emitters via `AMBIENT_` empties with `og_sound_name` set to any name from the 212 list above

### What needs more work:
- Music zone triggers (need `type='music` ambient with correct lump format)
- The `effect-name` lump for `type='sound` ambients should use `'symbol` not a plain string
- `ambient-sounds` list in level-load-info is unused by all vanilla levels — likely a PS2-era remnant

### Open questions:
- Do the 212 SFX names require a specific sound bank to be loaded, or are some in `common.sbk`?
- Can `type='sound` ambients loop, or are they one-shot only?
- What is the exact JSONC lump format OpenGOAL's custom level parser expects for `effect-name`?
