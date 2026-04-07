# OpenGOAL Blender Addon — Session Progress

## Status: WORKING ✅
Play button successfully launches game and spawns in custom level.

## Official Addon
`addons/opengoal_tools.py` — install this in Blender.
**Important:** After installing, close and reopen Blender to clear module cache.

## Scratch / In-Progress
`scratch/opengoal_tools_camera_test.py` — camera feature branch, not yet merged to main.

## Key Bugs Fixed (v9 → current)

### 1. nREPL binary framing (critical)
- GOALC nREPL uses binary-framed messages: `[u32 length LE][u32 type=10 LE][utf-8 string]`
- Fix: `struct.pack("<II", len(encoded), 10)` prepended to every message

### 2. Port conflict with 3Dconnexion SpaceMouse
- `3dxnlserver.exe` permanently holds port 8181 on `127.51.68.120`
- Fix: Port finder scans 8182+ for free port

### 3. `defined?` not a GOAL function
- Fix: `(if (nonzero? *game-info*) 'ready 'wait)`

### 4. False-positive ready check
- `"ready" in r` matched console noise → triggered spawn too early
- Fix: `"'ready" in r` — matches GOAL symbol return only

### 5. (bg) in run_after_listen causing repeating REPL warnings
- Fix: startup.gc contains ONLY `(lt)`. `(bg)` sent manually after `*game-info*` confirmed ready.

### 6. Wrong spawn continue-point
- Fix: `(get-continue-by-name *game-info* "{name}-start")` with fallback

### 7. Module cache issue
- Fix: Always close/reopen Blender after installing a new version

### 8. bonelurker crash
- bonelurker.gc compiles into MIS.DGO — needs .o injected into custom DGO
- Fix: `"bonelurker": {"o": "bonelurker.o", "o_only": True}` in ETYPE_CODE

### 9. kill_goalc() port hold
- Windows SO_EXCLUSIVEADDRUSE holds port until process fully exits
- Fix: Poll port until connection refused before returning

## Architecture: Play Button Flow
1. Kill GK + GOALC (poll port until free)
2. Write startup.gc: `(lt)` ONLY
3. Launch GOALC (wait for nREPL on free port 8182+)
4. Launch GK
5. Poll `(if (nonzero? *game-info*) 'ready 'wait)` — check `"'ready" in r` (with quote)
6. When ready: `goalc_send("(bg '{name}-vis)")` → sleep 1s → `(start 'play ...)`
7. sleep 0.5s → `({name}_obs_init)` — spawns camera trigger processes

## Camera System (scratch branch — needs testing)

### Root Cause Discovery
`LevelFile.cpp` line 155 has the cameras BSP array write **commented out**:
```cpp
//(cameras  (array entity-camera)  :offset-assert 116)
```
`Entity.cpp` line 5 hardcodes ALL actors as `entity-actor` header regardless of etype.
So `entity-camera` entries never get `birth!` called, never register with `*camera-engine*`,
and `master-check-regions` finds nothing to switch to.

### Solution (no C++ changes needed)
- `cam-state-from-entity` reads lump data only — doesn't care about entity type
- `change-to-entity-by-name` searches the **actors array** directly
- Camera actor sits in actors array with `trans` lump + `quat` field → works perfectly
- Trigger volume = generated GOAL process in obs.gc polling `*target* control trans` AABB
- On enter: `(send-event *camera* 'change-to-entity-by-name "camera-N")`
- On exit: `(send-event *camera* 'clear-entity)`

### Blender Workflow
1. **Add Camera** button in 📷 Camera panel → places ARROWS empty named `CAMERA_0`
2. Rotate empty to aim (-Z axis = look direction)
3. Make a box mesh for the trigger area
4. Shift-click camera + box → **Link Trigger Volume**
5. Box auto-tagged as Trigger Zone (no collision, invisible)
6. Build & Play → obs.gc generated, `{level}_obs_init()` called after spawn

### Export Details
- Camera actor: `entity-camera` etype in actors array with `trans` lump + `quat`
- No volume → no GOAL trigger → always-active (engine verified: no vol/pvol = always on)
- With volume → obs.gc generates `cam-trigger-camera_N` defun + `obs_init` spawner
- Vol lump (`vector-vol`) still exported for completeness / future use
- AABB computed from 8 bounding-box corners of the CAMVOL_ mesh

### Collision/Invisible Fixes
- `export_extras=True` added to GLB export — custom props now reach C++ extractor
- `og_trigger` bool: stamps `set_invisible=1 + set_collision=1 + ignore=1` pre-export
- CAMVOL_ meshes always auto-stamped as triggers (no manual step needed)

## Enemy Spawning Status

### ✅ Confirmed Working
- babak, hopper, junglesnake

### 🔲 To Test Next (in tpage group order)
- **Sunken group**: bully, puffer, double-lurker
- **Misty group**: quicksandlurker, muse, bonelurker, balloonlurker
- **Maincave group**: gnawer, driller-lurker, dark-crystal (baby-spider partial)
- **Ogre group**: plunger-lurker (flying-lurker already works)
- **Robocave group**: cavecrusher

### ❌ Known Issues
- navmesh full pathfinding — no engine support yet

## 📌 NEXT SESSION
1. Test camera scratch build in-game:
   - No-volume camera → always active?
   - Volume camera → switches on enter, clears on exit?
2. If trigger defun crashes: check `(loop (suspend))` survives as process thread body
3. If `change-to-entity-by-name` returns error: check lump name matches exactly
4. Once working, merge camera changes into main `addons/opengoal_tools.py`

## Camera Debug Session (latest)

### What we confirmed from logs
- `my-level-obs` links successfully every time ✓
- `entity-camera` birth loop fixed (etype→camera-tracker) ✓
- `art-group "process" not valid` error fixed (etype→camera-tracker) ✓
- obs.gc is being generated correctly ✓
- **`my_level_obs_init` was never called** — nREPL *target* poll was unreliable

### Root cause of obs_init not running
The `*target*` poll (`(if *target* 'alive 'wait)`) was checking every 0.25s but 
the response matching `"'alive" in r2` may have been failing — the nREPL returns
a prompt string alongside the value, and timing/encoding issues could cause misses.

### Fix applied
- Replaced fragile poll with `time.sleep(2.0)` then direct `goalc_send(f"({init_fn})")`
- The trigger lambda's own `(when *target* ...)` handles the case where it starts 
  before Jak spawns — it just waits in the loop until *target* exists
- Restructured generated GOAL to put trigger body directly inside the 
  `process-spawn-function` lambda (matches all real game examples)
- Added `[obs-init] calling...` / `[obs-init] response:` logging to Blender console

### Generated obs.gc structure (current)
```lisp
(defun my_level_obs_init ()
  (process-spawn-function process
    (lambda ()
      (let ((inside #f))
        (loop
          (when *target*
            (let* ((pos (-> *target* control trans))
                   (in-vol (and <AABB checks>)))
              (cond
                ((and in-vol (not inside))
                 (set! inside #t)
                 (send-event *camera* 'change-to-entity-by-name "camera-0"))
                ((and (not in-vol) inside)
                 (set! inside #f)
                 (send-event *camera* 'clear-entity)))))
          (suspend))))
    :to *entity-pool*)
  (none))
```

### 📌 NEXT SESSION
1. Test with new build — check Blender System Console for `[obs-init] calling...`
2. If obs_init fires but camera doesn't switch: check entity-by-name finds "camera-0"
3. If obs_init still doesn't fire: the 2s sleep after (start) isn't enough — try 4s
   or add a second attempt: retry obs_init once more after another 2s
4. Once working: merge to main addon

## Enemy Data (Images + Definitions)

### Status
- **Images**: 37 JPGs pushed to `knowledge-base/opengoal/enemy-images/` (compressed from wiki renders, 94% smaller)
- **Definitions**: 30/33 enemies scraped to `knowledge-base/opengoal/jak1-enemy-definitions.json`

### Missing definitions (3 enemies — wrong wiki title guessed)
- `billy` (lurker frog) — try: "Lurker frog", "Billy (lurker)", "Bog lurker"
- `baby-spider` — try: "Baby spider (The Precursor Legacy)", "Spider lurker"  
- `mother-spider` — try: "Mother spider (The Precursor Legacy)", "Spider boss"

### How to find correct wiki titles
1. Go to https://jakanddaxter.fandom.com and search the enemy name
2. Note the exact URL slug (e.g. `/wiki/Baby_spider_(lurker)`)
3. Add that title to the `alts:[]` array in `jak1-enemy-definitions-grabber.html` for that enemy
4. Re-run just that enemy (or all) and re-download JSON

### Scraper tools (in scratch/)
- `scratch/jak1-enemy-image-grabber.html` — grabs all enemy images from wiki category, downloads ZIP
- `scratch/jak1-enemy-definitions-grabber.html` — grabs intro text from each enemy article via `parse&prop=wikitext&section=0`, strips wiki markup, downloads JSON + CSV

### API used for definitions
```
https://jakanddaxter.fandom.com/api.php?action=parse&page=<TITLE>&prop=wikitext&section=0&redirects=true&format=json
```
`section=0` = everything before the first heading (the intro you see above Contents).
Response is raw wikitext → strip `{{templates}}`, `[[links]]`, `<ref>` tags client-side.
Uses 5-proxy CORS fallback chain (allorigins → corsproxy.io → codetabs → thingproxy → htmldriven).

### Next steps for addon integration
- Wire image filenames to code names (image filename → `code_name` field in JSON)
- Add enemy picker UI in Blender addon using images + short_desc

## Known Enemy Issues

### Double Lurker — crashes game
`double-lurker` causes a crash when spawned in a custom level. Needs further investigation.
Possible causes: requires linked actor pair (two entities referencing each other), or specific tpage/DGO dependency not met.
TODO: check `double-lurker.gc` for any paired actor setup logic.
