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

---

## ✅ CONFIRMED WORKING — April 7 2026

Sound emitters work in-game. Tested with `waterfall` sound, `village1` bank.

### Root bugs fixed this session
1. **JSONC crash**: `type='ambient-sound` → `'sound`, `sound-name` → `effect-name`, bare string → `["symbol",name]`
2. **Sound bank GOAL syntax**: was `'('beach)` → fixed to `'(beach)`
3. **Icon**: `SEQUENCE_COLOR_04` → `PLAY`
4. **Autoload button**: removed from Build & Play panel

### Merged to main ✅
Commit: `8e2eb13` on main

### Next session starting point
- feature/audio branch still exists for future audio work
- One-shot ambients still broken (engine bug) — obs.gc trigger is the workaround
- Music ambient zones (`type='music`) not yet exposed in Blender UI — could add
- Could add a mode toggle (loop/one-shot) to emitter UI once engine bug is patched

---

## Future Improvements (low priority — current system works well)

### Volume control
- `ambient-type-sound-loop` hardcodes volume to 1024 (100%)
- Fix: expose `og_sound_volume` slider (0-100%) on emitter empty
- Write as `(the int (* vol 10.24))` into sound spec in `collect_ambients`
- Estimated effort: 1 iteration

### Pitch / speed control  
- Needs `effect-param` lump (binary `sound-play-parms` struct)
- More involved to write from Python
- Estimated effort: 2-3 iterations

### Falloff distance
- bsphere radius currently controls activation distance only
- `fo-min` / `fo-max` in sound spec control volume fade with distance
- Could expose as separate "inner radius" / "outer radius" on emitter
- Estimated effort: 1-2 iterations

### One-shot sounds (engine bug — needs upstream fix)
- `cycle-speed >= 0` crashes due to `lookup-tag-idx 'exact 0.0` vs tags at `-1e9`
- Fix requires PR to OpenGOAL: patch `ResLump.cpp` to write sound tags at `0.0`
  OR patch `birth-ambient!` in `ambient.gc` to use `'interp` instead of `'exact`
- Worth reporting upstream

### Note on all 1048 sounds
All sounds work as looping emitters regardless of whether they were "one-shot"
in the original game. Short sounds (explosions, jumps etc.) just loop continuously.
This is fine — use with appropriate radius so it doesn't sound ridiculous.

---

## Music Ambient Zone System (April 13 2026)

### Root cause of music not playing
`:music-bank` in `level-load-info` does NOT trigger music on level load.
It only resets music after player death. Music requires an active `set-setting! 'music`
call, which is done by a `type='music` ambient entity when the player enters its bsphere.
Vanilla levels all have a large music zone covering the entire level.

### What was built — branch: feature/music-ambient

**New panel:** `Spawn > 🎵 Music Zones` (mirrors Sound Emitters panel)
- Music Bank dropdown (all 19 banks)
- Flava dropdown — **dynamically filtered** to selected bank's variants only
- Priority float (10.0 default; vanilla boss/race zones use 40.0)
- Zone Radius (40m default — large, should cover whole level)
- "Add Music Zone at Cursor" button
- List of placed zones shown below

**New operator:** `OG_OT_AddMusicZone` (`og.add_music_zone`)
- Spawns `AMBIENT_mus001` empty (gold colour, distinct from cyan sound emitters)
- Stores `og_music_bank`, `og_music_flava`, `og_music_priority`, `og_music_radius` as custom props
- Placed into Sound Emitters collection (same as sound empties)

**Export:** `collect_ambients()` now handles `og_music_bank` empties:
```json
{
  "trans": [x, y, z, radius],
  "bsphere": [x, y, z, radius],
  "lump": {
    "name": "mus001",
    "type": "'music",
    "music": ["symbol", "village1"],
    "flava": ["float", 0.0],
    "priority": ["float", 10.0]
  }
}
```
Flava index looked up from `MUSIC_FLAVA_TABLE` at export time (engine takes float index).

**New data:** `MUSIC_FLAVA_TABLE` dict in `data.py` — all 19 banks → flava variant lists.

### Files changed
- `data.py` — `MUSIC_FLAVA_TABLE`, `_music_flava_items_cb`
- `properties.py` — `og_music_amb_bank/flava/priority/radius` scene props
- `operators.py` — `OG_OT_AddMusicZone`
- `panels.py` — `OG_PT_SpawnMusicZones`
- `export.py` — `collect_ambients()` music zone branch
- `__init__.py` — registrations

### How to use
1. Install from `feature/music-ambient`
2. Set your level's Music Bank in the Audio panel (e.g. `village1`)
3. Go to Spawn > 🎵 Music Zones
4. Set Music Bank to `village1`, Flava to `default`, Radius large enough to cover level
5. Click "Add Music Zone at Cursor" — place it roughly in the centre of your level
6. Export & compile — music should now play on entry

### Next steps
- [ ] Test in-game
- [ ] Consider adding "Select Zone" button in list (click to select the empty)
- [ ] If approved: merge feature/music-ambient to main

---

## Pre-test Audit Session (April 13 2026)

### Two-pass audit — 20 issues checked, 3 fixed

**Pass 1 — doc conflict resolved:**
lump-system.md had `music → ResFloat ["float", value]` which contradicted
audio-system.md `music → ["symbol", "village1"]`. The float version is a doc error —
`set-setting! 'music` takes a symbol, so the ResSymbol format is logically correct.
Fixed lump-system.md. Confidence: 85% symbol format is right.

**Pass 2 — 3 fixes applied:**

1. `effect-name` added to music zone export — listed in lump quick-ref as required
   for 'music type. Was absent from initial export. Added defensively as `["symbol", bank]`.
   Worst case if not needed: silently ignored. No crash risk.

2. `og_music_amb_bank` now has an `update` callback that resets `og_music_amb_flava`
   to `"default"` when the bank changes. Prevents stale flava string being held
   internally when the user switches banks in the panel.

3. lump-system.md `music` entry corrected from ResFloat to ResSymbol.

**All 20 checks passed with no remaining bugs:**
- trans/bsphere radius units: meters, matches working sound emitter path ✓
- `none` bank filter: not exported ✓  
- empty string bank: not exported ✓
- unknown bank/flava: safe fallback to index 0 ✓
- name slicing `[8:]`: produces correct short name ✓
- sound/music prop collision: impossible (different custom prop keys) ✓
- validate_ambients: passes (trans/bsphere both have 4 elements) ✓
- write_jsonc: passes ambients straight to json.dumps, no transformation ✓
- All 19 LEVEL_BANKS entries have MUSIC_FLAVA_TABLE coverage ✓
- Coexistence with sound emitters + hint ambients ✓
- EnumProperty callback: None-safe with getattr fallback ✓

**One remaining uncertainty (won't know until in-game test):**
music lump type: ["symbol", "village1"] vs ["float", float_index]
If music doesn't play after zone placement, try swapping to:
  "music": ["float", <index_of_bank_in_LEVEL_BANKS>]
where index = LEVEL_BANKS.index(bank) - 1 (skipping 'none' at 0)

**Branch state:** feature/music-ambient, 4 commits since branch from main.
Ready to test.

### Commits in this branch
- feat: add music ambient zone system
- notes: music ambient zone session notes  
- fix: music ambient export + doc correction (effect-name + lump-system.md)
- fix: reset og_music_amb_flava to default when bank changes

---

## Selected Object Panel Fix (April 14 2026)

### Issues from screenshots
1. `AMBIENT_mus002` was showing the **Sound Emitter** inspector (wrong panel)
   with `Sound: ?` — because OG_PT_AmbientEmitter polled for all `AMBIENT_*`
2. Selected Object panel fields were all read-only labels, not editable

### Fixes
- `OG_PT_AmbientEmitter.poll` now excludes `AMBIENT_mus*`
- New `OG_PT_MusicZone` panel polls for `AMBIENT_mus*` specifically
- `_draw_selected_music_zone()` uses `_prop_row()` for live editable fields:
  - og_music_bank (text field — user types bank name)
  - og_music_flava (text field + warning if invalid for bank + valid flavas hint)
  - og_music_priority (float)
  - og_music_radius (float)
- `_draw_selected_emitter` also updated: radius is now editable via _prop_row

### Branch state
feature/music-ambient — 6 commits ahead of main. Ready to test.

### What to test
1. Place a Music Zone (Spawn > Music Zones > Add Music Zone at Cursor)
2. Select the placed AMBIENT_mus* empty
3. Selected Object panel should show "Music Zone" sub-panel (not Sound Emitter)
4. Edit bank/flava/priority/radius inline — values should persist
5. Export & compile — check generated JSONC has correct music ambient entry
6. Play level — music should start when entering the zone bsphere

### If music still doesn't play
See audit notes — one remaining uncertainty:
`"music": ["symbol", "village1"]` may need to be `["float", <bank_index>]`
Bank indices (0=none, 1=beach, ..., 17=village1) from LEVEL_BANKS.

---

## ✅ MERGED TO MAIN — April 14 2026

Music zone system confirmed working in-game.
All functionality audited, docs updated, branch merged and deleted.

### Summary of everything added in feature/music-ambient

**Core fix:** music now plays on level load via `type='music` ambient zone.
`:music-bank` alone was never enough — this was the root cause.

**New panel:** Spawn > 🎵 Music Zones
**New selected-object panel:** Music Zone (bank/flava pickers + priority/radius)
**New operators:** add_music_zone, set_music_zone_bank, set_music_zone_flava
**Export:** collect_ambients handles AMBIENT_mus* → type='music lump
**Data:** MUSIC_FLAVA_TABLE (19 banks → flava variants), _music_flava_items_cb

### Files changed from main
- data.py — MUSIC_FLAVA_TABLE, _music_flava_items_cb
- properties.py — og_music_amb_bank/flava/priority/radius scene props
- operators.py — AddMusicZone, SetMusicZoneBank, SetMusicZoneFlava
- panels.py — OG_PT_SpawnMusicZones, OG_PT_MusicZone, fixed AmbientEmitter poll
- export.py — music zone branch in collect_ambients
- __init__.py — registrations
