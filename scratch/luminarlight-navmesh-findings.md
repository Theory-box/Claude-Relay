# LuminarLight Navmesh Research Findings

Source: https://github.com/LuminarLight/LL-OpenGOAL-ModBase

## How they do it — key differences from our approach

### 1. The navmesh data lives in a SEPARATE file, NOT entity.gc

- `entity.gc` has only a stub: `(defun custom-nav-mesh-check-and-setup ((this entity-actor)) (check-custom-navmeshes-of-lltest2 this))`
- `entity.gc` does `(require "pc/ll-modbase/custom-navmesh-data.gc")` at the TOP
- The actual navmesh `(new 'static 'nav-mesh ...)` blocks live in `custom-navmesh-data.gc`
- That separate file is compiled LATER in the chain, when `nav-enemy` type is available
- `entity.gc` compiles before `nav-enemy` is defined — that's why `(the nav-enemy this)` fails

### 2. They use `(set! (-> this nav-mesh) ...)` directly — NOT a cast
- `this` in `custom-navmesh-data.gc` is typed `entity-actor`
- `entity-actor` DOES have a `nav-mesh` field — it's defined in entity-h.gc
- Our assumption that "nav-mesh is only on nav-enemy" was WRONG
- The field IS on entity-actor. The cast was unnecessary and caused the compile error.

### 3. They use `:custom-hacky? #t` on the nav-mesh struct
- This is a LuminarLight-specific flag added to their fork of navigate.gc
- It "neutralizes the function that caused trouble" (entity-nav-login writing to read-only static)
- Vanilla OpenGOAL does NOT have `:custom-hacky? #t` — we cannot use it

### 4. They call `(entity-nav-login this)` at the end of each case branch
- NOT the user-list engine setup we were doing
- This is the proper way to initialize the navmesh connection in their modbase
- In vanilla OpenGOAL, entity-nav-login calls update-route-table → crash on static mesh
- Their `:custom-hacky? #t` flag bypasses that crash

### 5. The `(set! (-> this nav-mesh) ...)` is in the CASE block not after
- Our user-list init code after the case was also wrong
- The whole setup is self-contained per case branch

## What we need to change in our approach

Since we're on vanilla OpenGOAL (no :custom-hacky? flag):

Option A: Use their modbase (requires forking LL-ModBase — not viable for us)

Option B: Keep our approach but:
1. Move navmesh data to a separate file compiled AFTER navigate.gc/nav-enemy
2. Remove the cast `(the nav-enemy this)` — entity-actor HAS nav-mesh field
3. Fix the entity-nav-login vs user-list-engine question for vanilla

### The user-list-engine approach (our current approach) may be correct for vanilla:
- entity-nav-login calls update-route-table which writes to static memory → segfault
- So we correctly avoid entity-nav-login
- But we need to set up user-list some other way
- The correct approach: just set user-list to a new engine before nav-mesh-connect sees it

### Correct vanilla approach:
1. `(set! (-> this nav-mesh) <static nav-mesh>)` — works, field IS on entity-actor
2. Manually allocate user-list: `(set! (-> (-> this nav-mesh) user-list) (new 'loading-level 'engine 'nav-engine 32))`
3. Do NOT call entity-nav-login (crashes on static mesh in vanilla)

## Key structural fix needed
Move navmesh generation code out of entity.gc patch and into a separate
`<levelname>-navmesh.gc` file that is compiled via goal-src after navigate.gc.
entity.gc only needs the stub defun that calls into that file.
