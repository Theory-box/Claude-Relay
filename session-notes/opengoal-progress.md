# OpenGOAL Blender Addon — Session Progress

## Status: WORKING ✅
Play button successfully launches game and spawns player in custom level.

## Official Addon
`addons/opengoal_tools.py` — install this in Blender.
**Important:** After installing, close and reopen Blender to clear module cache.

## Key Bugs Fixed (v9 → v10 → release)

### 1. nREPL binary framing (critical)
- GOALC nREPL uses binary-framed messages: `[u32 length LE][u32 type=10 LE][utf-8 string]`
- Old code sent raw text → "Bad message, aborting the read"
- Fix: `struct.pack("<II", len(encoded), 10)` prepended to every message

### 2. Port conflict with 3Dconnexion SpaceMouse
- `3dxnlserver.exe` permanently holds port 8181 on `127.51.68.120`
- Fix: Port finder scans 8182+ for free port, passes `--port N` to GOALC

### 3. `defined?` not a GOAL function
- Used `(if (defined? '*game-info*) ...)` — GOAL has no `defined?`
- Fix: `(if (nonzero? *game-info*) 'ready 'wait)` — correct GOAL idiom

### 4. Wrong spawn continue-point
- `(get-or-create-continue! *game-info*)` uses current checkpoint (village1)
- Fix: `(get-continue-by-name *game-info* "{name}-start")` with fallback

### 5. Module cache issue
- Renaming the addon file without restarting Blender loads cached old version
- Fix: Always close/reopen Blender after installing a new version

## Architecture: Play Button Flow
1. Kill GK + GOALC
2. Write startup.gc: `(lt)` / sentinel / `(bg '{name}-vis)`
3. Launch GOALC (wait for nREPL on free port 8182+)
4. Launch GK
5. Poll `(if (nonzero? *game-info*) 'ready 'wait)` every 0.5s (120s timeout)
6. When ready: `(start 'play (get-continue-by-name *game-info* "{name}-start"))`

## Continue-Point System
- `SPAWN_` empties in Blender → continue-points in level-info.gc
- First spawn becomes `{levelname}-start`
- `(bg)` calls `set-continue!` to level's first continue-point
- `(start)` kills boot player and spawns fresh at that point

## Confirmed Working
- ✅ Build compiles level
- ✅ Play launches game and spawns in custom level
- ✅ babak, junglesnake, hopper enemies
- ❌ bonelurker — known crash, unsolved
- ❌ navmesh — no engine support yet

---

## 📌 REMINDERS FOR NEXT SESSION
> If the user pursues either of these goals in the session, remove that reminder from this file when done.

1. **Level design analysis** — Continue analyzing Jak 1 levels. See `knowledge-base/opengoal/jak1-level-design.md` for the pipeline and open questions. Suggested next levels: `firecanyon.glb`, `misty.glb`, `snowy.glb`. Goal is to build a comparison dataset across level types.

2. **Enemy spawning (Blender addon)** — Continue getting all Jak 1 enemies working and spawnable via the addon. Known issue: `bonelurker` crashes. Other enemies not yet tested. Goal is full enemy roster support.
