# Future Research Directions

Leads identified during the April 2026 goal_src deep dive that weren't fully explored.
Ordered roughly by expected payoff vs effort.

---

## High Priority

### 1. one-shot ambient sound patch

The `'exact 0.0` bug in `ambient.gc` (`birth-ambient!` lines ~609 and ~621) is a confirmed two-line fix identical in pattern to the vol-h.gc patch. Fix changes `'exact` to `'base` for `effect-name` and `effect-param` lookups. Same fix applies to `ambient-type-light` (~481), `ambient-type-dark` (~507), `ambient-type-weather-off` (~533) for vol lookups.

**Research needed:** Verify the fix doesn't break vanilla level ambient sounds. Test with one-shot sound emitter in a custom level.

---

### 2. Spline camera (`cam-spline`) implementation

Fully implemented in engine (`cam-states.gc`), completely unknown to the addon. Activated by `campath` + `campath-k` lumps on a camera entity. Would allow scripted camera paths along corridors, cinematic fly-throughs without needing cutscene machinery.

**Research needed:**
- What is the exact JSONC format for `campath` (multi-point vector4m)?
- What is `campath-k` exactly — knot values, uniform spacing, or arc-length parameterized?
- Does it work with the existing camera-trigger AABB system?
- `spline-follow-dist` behaviour — does positive vs negative direction matter?

---

### 3. Launcher fly-time bug fix

Confirmed: `export.py` writes `alt-vector.w = fly_time_seconds * 300` but engine reads it as seconds and multiplies by 300 itself. Fix is one line. Before fixing, test what vanilla launchers actually use for `alt-vector.w` to confirm the correct value scale.

---

### 4. `idle-distance` lump — proper implementation

Currently the addon writes an `idle-distance` lump that nothing reads. To make it actually work, a GOAL method override needs to be injected into `*-obs.gc` that reads `(res-lump-float this 'idle-distance :default (-> *babak-nav-enemy-info* idle-distance))` and stores it. This is a good candidate for a custom GOAL template in the addon's boilerplate generator.

**Research needed:** Which method override hook is cleanest — `nav-enemy-method-48`? Confirm the `enemy-info` struct field offset is stable across all nav-enemy subtypes.

---

### 5. `battlecontroller` addon support

Entirely missing from the addon. Source confirms: spawnable, reads 10+ lumps, supports multi-wave combat arenas. Needs: enemy type array picker, spawn-position waypoints (pathspawn), reward pickup selector, camera-name link, delay/mode config.

**Research needed:**
- Which tpage group does `battlecontroller.o` itself belong to? Does it require a specific DGO context?
- Do `misty-battlecontroller` and `swamp-battlecontroller` work in custom levels or only in their home DGOs?
- Can the base `battlecontroller` type be used directly without a level-specific subtype?

---

## Medium Priority

### 6. `cam-string` mode (rubber-band follow camera)

Activated by `stringMaxLength > 0.0` lump on camera entity. Free third-person follow camera confined to a trigger zone. Reads `stringCliffHeight`, `string-push-z`. Potentially very useful for open-area zones.

**Research needed:** What are sane default values? Does it conflict with the player's camera controls or does it just constrain them?

---

### 7. Missing crate types: `darkeco`, `barrel`, `bucket`, `none`

All confirmed valid values for the `crate-type` lump from `crates.gc`. `none` is particularly interesting — an invisible crate that still drops pickups. `darkeco` deals dark eco damage on break.

**Research needed:** Do `barrel` and `bucket` require their own tpages or are they part of common? Test each type spawns correct visual.

---

### 8. `perm-status` lump for pre-completing entities

`["int32", 64]` on any entity sets bit 6 (`complete`) at spawn time. `["int32", 256]` sets `real-complete`. Allows doors to spawn open, crates to be pre-broken, oracles to show their "done" state — without any game-task wiring.

**Research needed:** Does this work cleanly for all entity types or are there actors that have different behaviour when `complete` is set mid-init? Test on eco-door, sun-iris-door, oracle, crate.

---

### 9. `flags` bitfield on camera entities

Bit `0x8000` on the `flags` lump switches camera tracking mode to use the full rotation matrix instead of the default aim-at-player behavior. Could enable fully scripted camera rotations without the Look-At system.

**Research needed:** What do other flag bits do? Full bitmask documentation doesn't seem to exist yet.

---

## Lower Priority / Long-term

### 10. `snow-bumper` entity

Valid `process-drawable` entity, has a full `init-from-entity!`. No tpage info confirmed. Not in addon. Would require Snow tpages.

**Research needed:** What tpages does it need? Does it function correctly without the snow physics context?

### 11. Part-spawner / particle system

Every vanilla level has a `<level>-part.gc` subtype of `part-spawner`. The addon has zero support for this. Particle IDs must be globally unique (safe range: 2969–3583). Full system documented in `particle-effects-system.md`.

**Research needed:** Can a custom level use `part-spawner` directly with a hardcoded `art-name` pointing to a vanilla `defpartgroup`, without defining its own subtype? If so, this is a shortcut to particle effects without custom GOAL code.

### 12. Level mood/fog/sky configuration

Sky and mood are hardcoded to `village1` for custom levels. `level-load-info` has `mood`, `mood-func`, `sky`, `sun-fade` fields. Changing these requires editing `level-info.gc` and recompiling. 

**Research needed:** Is there a clean way to inject a custom mood function via `obs.gc`? Can `set-setting! 'mood` be called from startup.gc to override the loaded mood at runtime?

### 13. `startup.gc` timing and entity availability

The window in which `startup.gc` runs relative to entity birth is unclear. Entities are birthed over multiple frames after level load. If `startup.gc` runs before entities are alive, `entity-by-name` lookups will return `#f`.

**Research needed:** Map the exact frame sequence: DGO load → login → birth spread → `startup.gc` execution. Is there a safe hook point after all entities are alive?

### 14. Load boundary / level transition triggers

`static-load-boundary` in `load-boundary-data.gc`. Polygonal XZ shapes that fire `load`/`display`/`vis`/`checkpt` commands when player crosses. LuminarLight has working examples. For multi-area mods this is essential but requires editing a global file.

**Research needed:** Is there a way to inject new load boundaries from per-level code without touching `load-boundary-data.gc`? Or can the addon auto-patch that file on export similar to the vol-h.gc patch?

---

## Quick Wins (low effort, high value)

- Document `force-actors? #t` in getting-started guide ← 10 minutes, no code
- Fix launcher fly-time bug in `export.py` ← one line change
- Add `darkeco`/`barrel`/`bucket`/`none` crate types ← 10 lines in data.py
- Add `perm-status` lump to eco-door panel ← quick "Starts Open" improvement
- Expose `notice-dist` on puffer ← single `_prop_row` addition
