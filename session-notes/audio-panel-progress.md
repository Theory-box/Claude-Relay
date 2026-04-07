# OpenGOAL Audio Panel — Session Notes
Last updated: April 7, 2026

---

## What We Built

A new `🔊 Audio / Ambience` panel in the Blender addon N-panel with:
- **Sound Banks** — two dropdowns (Bank 1, Bank 2) from all 19 valid Jak 1 level banks
- **Sound picker** — `invoke_search_popup` operator (`OG_OT_PickSound`) with `bl_property = "sfx_sound"` — opens a floating wide search popup identical to the entity picker
- **Add Emitter at Cursor** — spawns an `AMBIENT_snd001` empty with custom props
- **Level export** — writes `:sound-banks` and `:music-bank` to `level-load-info` on export

All of this is in `scratch/opengoal_tools_with_audio.py`.
The main addon `addons/opengoal_tools.py` still has an older version of the audio panel from a mid-session promote.

---

## SBK Data We Have

- `knowledge-base/opengoal/sbk_sounds.json` — 1048 sounds across 24 banks, parsed from actual `.SBK` files
- `knowledge-base/opengoal/sbk-sound-contents.md` — human-readable docs
- `knowledge-base/opengoal/audio-system.md` — full music/sound system docs
- `scratch/parse_sbk.py` — the parser script that extracted the data

Key finding: `common.sbk` (461 sounds) is always loaded. Level banks (max 2) are loaded per level.

---

## The Crash — Ambient Sound JSONC Format

### What we tried (crashes game on proximity)
```json
{
  "trans": [x, y, z, radius],
  "bsphere": [x, y, z, radius],
  "lump": {
    "name": "my-sound",
    "type": "'sound",
    "effect-name": ["symbol", "thunder"],
    "cycle-speed": ["float", 5.0, 2.0]
  }
}
```

### What the game expects (from ambient.gc source)
- `type` must be `'sound` ✓
- Field is `effect-name` not `sound-name` ✓
- `effect-name` must be `["symbol", "soundname"]` ✓
- `cycle-speed` must be `["float", min_secs, random_range_secs]` ✓
- Negative first cycle-speed value = looping (`ambient-type-sound-loop`)

### The actual crash cause (unresolved)
Game crashes with no log output when player enters emitter bsphere radius.
Likely cause: `rand-vu-int-count(0)` crash if `user-float 2` (effect-name count) is 0.

In `birth-ambient!`, the count is set by walking `effect-name` tags via `lookup-tag-idx` with `'exact` mode.
If the tag isn't found, count stays 0. Then in `ambient-type-sound`:
```lisp
(let ((f30-0 (the float (rand-vu-int-count (the-as int (-> s5-0 ambient-data user-float 2))))))
```
`rand-vu-int-count(0)` = undefined behavior / crash.

### Things to try next session
1. Manually test this exact JSONC in `my-level.jsonc` to isolate whether it's our format or something else:
   ```json
   {
     "trans": [0.0, 5.0, 0.0, 10.0],
     "bsphere": [0.0, 5.0, 0.0, 15.0],
     "lump": {
       "name": "test-sound",
       "type": "'sound",
       "effect-name": ["symbol", "thunder"],
       "cycle-speed": ["float", 5.0, 2.0]
     }
   }
   ```
2. Check if anyone in the OpenGOAL Discord has successfully used `'sound` type ambients in a custom level JSONC
3. Look at whether the `lookup-tag-idx` + `'exact` vs `DEFAULT_RES_TIME` mismatch is the real issue
4. Consider the `'sound-loop` type approach (negative cycle-speed) as an alternative
5. Ask on the OpenGOAL Discord — nobody in any public mod repo is using sound ambients via JSONC

### Key source files to re-read
- `goal_src/jak1/engine/entity/ambient.gc` lines 596-640 (`birth-ambient!`)
- `goal_src/jak1/engine/entity/ambient.gc` lines 417-456 (`ambient-type-sound`)
- `goalc/build_level/jak1/Entity.cpp` lines 165-195 (`add_ambients_from_json`)
- `goalc/build_level/common/Entity.cpp` lines 205-215 (symbol lump handler)

---

## Other Issues Fixed This Session

### SEQUENCE_COLOR_04 icon
- Not valid in Blender 4.4
- Fixed: replaced with `"PLAY_SOUND"` in the Build & Play panel
- Still broken in `addons/opengoal_tools.py` (main addon) — needs fixing

### Launch & Auto-Load Level button
- Removed from scratch version per user request
- Still present in main addon

### Blender not picking up addon updates
- User had to remove + reinstall + restart multiple times
- Even after reinstall, old exported JSONC format was used
- Symptom: JSONC had `"cycle-speed": [5.0, 2.0]` (no type string) even after fix was in place
- Cause: either Blender module cache or wrong file being installed

---

## Current File State

| File | State |
|---|---|
| `addons/opengoal_tools.py` | Mid-session promote — has audio panel but old format, SEQUENCE_COLOR_04 bug, autoload button |
| `scratch/opengoal_tools_with_audio.py` | Latest scratch — fixed icons, no autoload, correct JSONC format (but sound still crashes) |

**Recommended next session start:** restore main addon to the pre-audio version OR promote the scratch file after fixing the ambient sound crash.

---

## Sound System Architecture (for reference)

- `:sound-banks` in `level-load-info` → loads `.sbk` files, max 2, handled by `update-sound-banks()` in `level.gc`
- `:music-bank` → only read on player death/respawn to reset music, doesn't play music itself
- Music is actually triggered by `set-setting! 'music '<symbol>` calls
- `*flava-table*` maps music symbols to variant indices (sub-area music changes)
- `common.sbk` always loaded at boot — 461 sounds always available
- Level banks max 2 simultaneously or game gets OOM error

---

## Crash Root Cause — Confirmed from Source (April 7 2026)

### One-shot ambient (`cycle-speed >= 0`) crashes — here's exactly why

Traced through three source files:

**`common/goal_constants.h`:**
```cpp
constexpr float DEFAULT_RES_TIME = -1000000000.0;
```
All lump tags written by the C++ level builder use this timestamp.

**`ambient.gc` `birth-ambient!` one-shot branch:**
```lisp
(let ((s5-1 (-> ((method-of-type res-lump lookup-tag-idx) this 'effect-name 'exact 0.0) lo))
```
Uses `'exact` mode with time `0.0`.

**`res.gc` `lookup-tag-idx` `'exact` logic:**
```lisp
((and (>= time (-> tag-ptr 0 key-frame)) (!= mode 'exact))
 ;; only matches in non-exact mode — 'exact skips this branch
```
Tag is at `-1e9`. Exact match for `0.0` never fires. Returns `-1`.
Count stays `0`. `(rand-vu-int-count 0)` → crash.

### Looping path (`cycle-speed < 0`) does NOT crash

Uses `res-lump-struct` (interp mode) which matches `-1e9` tags fine.
Stores the symbol pointer directly in `user-float 2`, no `rand-vu-int-count` involved.

### Decision matrix

| Approach | Works? | Notes |
|---|---|---|
| `cycle-speed >= 0` (one-shot) | 💥 NO | crashes on bsphere entry |
| `cycle-speed < 0` (loop) | ✅ YES | single sound only, loops while in range |
| Multiple symbols + loop | ⚠️ PARTIAL | only first symbol used |
| obs.gc `sound-play` trigger | ✅ YES | full control, no bugs |

### Next steps
- Implement looping sound emitters in addon using `cycle-speed: ["float", -1.0, 0.0]`
- For one-shots / random sounds: use obs.gc trigger pattern
- Music via `type='music` ambient is unaffected (different code path, no exact lookup)

---

## Branch Strategy (set up April 7 2026)

Audio work lives on: **`feature/audio`**

### How to use
- At session start: `git checkout feature/audio && git pull`
- All audio/sound panel work goes on this branch
- When user approves a build → merge to `main`
- `main` stays always-installable

### Current state of feature/audio
Branched from `main` at commit `c7e0303`.
`addons/opengoal_tools.py` on this branch = the mid-session promote version
(has audio panel but: old JSONC format, SEQUENCE_COLOR_04 icon bug, autoload button).

The fixed version is in `scratch/opengoal_tools_with_audio.py`.

**Recommended first task on this branch:**
Replace `addons/opengoal_tools.py` with the fixed scratch version,
then implement looping sound emitters using confirmed-working `cycle-speed < 0` format.

---

## Audio Panel Implementation Session (April 7 2026)

### Status: feature/audio branch updated ✅

### What was done
All fixes applied directly to `addons/opengoal_tools.py` on `feature/audio`.

**JSONC crash fix:**
- `type`: `'ambient-sound` → `'sound`
- `sound-name` → `effect-name`
- bare string → `["symbol", name]`
- `cycle-speed`: now `["float", -1.0, 0.0]` for loop (engine crash confirmed for one-shot)

**Icon fix:** `SEQUENCE_COLOR_04` → `PLAY`

**Sound data:** Replaced `MUSIC_BANK_ITEMS` with full `LEVEL_BANKS + SBK_SOUNDS + ALL_SFX_ITEMS` (1048 sounds from actual .SBK files)

**Scene props:**
- `sound_bank_1`, `sound_bank_2` (replaces freetext `sound_banks`)
- `sfx_sound` EnumProperty (1048 searchable sounds)
- `music_bank` now uses `LEVEL_BANKS`
- Removed `music_bank_custom`, `sound_banks`

**New operator:** `OG_OT_PickSound` — `invoke_search_popup` over all 1048 sounds

**Panel improvements:**
- Two bank dropdowns + duplicate warning + live sound count
- Pick... button opens searchable sound popup
- Add Emitter places emitter with currently picked sound
- Emitter list shows sound + loop/one-shot mode

### Files changed
- `addons/opengoal_tools.py` on `feature/audio`

### To test
1. Install `addons/opengoal_tools.py` from `feature/audio` branch
2. Audio panel → set Bank 1 to `village1`, Music Bank to `village1`
3. Pick sound → search "waterfall" → select → Add Emitter at Cursor
4. Export & compile → walk into emitter bsphere → should hear waterfall looping
5. Check level-info.gc has `:sound-banks '(village1)` and `:music-bank 'village1`
6. Music should start playing on level load

### Known limitation
One-shot sounds (`og_sound_mode = "one-shot"`) still crash — engine bug in
`ambient-type-sound` using `lookup-tag-idx 'exact 0.0` on tags at `-1e9`.
Only looping sounds work via ambient system. One-shots require obs.gc trigger.

### Next steps
- [ ] Test in-game
- [ ] If music ambient zones wanted: add `'music` type ambient support to panel
- [ ] If merge approved: `git checkout main && git merge feature/audio && git push`
