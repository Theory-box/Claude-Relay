# Workflow Reference

How Export & Build, Play, and GOALC work together.

---

## The Two Buttons

### Export & Build

Run this every time you make any change in Blender — geometry, actor placement, settings, anything.

What it does, in order:
1. Exports the scene to `<n>.glb`
2. Writes `<n>.jsonc` — actor and ambient placement, art groups, sound banks
3. Writes `<nick>.gd` — DGO definition (enemy `.o` files + art groups)
4. Writes `<n>-obs.gc` — stub GOAL source file
5. Patches `level-info.gc` — registers the level and continue points
6. Patches `game.gp` — adds build, CGO, and goal-src entries
7. Compiles — if GOALC nREPL is connected, sends `(mi)` to it directly; otherwise launches a fresh GOALC instance with `startup.gc`

### Play

Run this after a successful Export & Build. Does **not** recompile.

What it does:
1. Kills any running `gk.exe`
2. If nREPL is live: launches GK, waits 6 seconds, sends `(lt)` then `(bg '<n>-vis)`
3. If no nREPL: writes a `startup.gc` with `(lt)` + `(bg)`, launches GOALC, then GK

> Always run Export & Build before Play if you've made changes. Play only reloads the game — if you skip the build step, your changes won't appear.

---

## GOALC and nREPL

GOALC is the OpenGOAL compiler. It opens a TCP nREPL server on port **8181** when it starts.

The addon connects to this port to send commands. If a connection is found:
- Export & Build sends `(mi)` — incremental compile, fast
- Play sends `(lt)` then `(bg '<n>-vis)` — load game then load level

If no connection is found, the addon writes a `startup.gc` file and launches fresh GOALC and GK processes. This is slower but always works.

**Console management**: Both buttons kill existing GOALC and GK instances before launching new ones. Processes never stack.

---

## REPL Commands (manual use)

If you want to control the game manually from GOALC:

```lisp
(lt)                   ; connect GOALC to the running game
(bg '<n>-vis)          ; load your custom level
(bg 'village1)         ; return to village 1
(mi)                   ; incremental compile (after source changes)
```

> Use `(bg)` not `(bg-custom)` for custom levels. `(bg-custom)` routes through village1 first, which pre-loads BEA.DGO and causes art group crashes. See [Entity Spawning — Art Groups](entity-spawning.md#art-groups) for details.

---

## Common Issues

### Level doesn't appear after clicking Play
- Did you run Export & Build first? Play doesn't recompile.
- Check the Blender console for GOALC errors during the build step.

### GOALC errors during Export & Build
- **"file not found"** — a source file path is wrong. Check level name spelling.
- **"type redefinition"** — a `.gc` file is being compiled twice. Check `game.gp` for duplicate `goal-src` entries.
- **Bonelurker crash** — known issue. Remove bonelurker actors and rebuild.

### Entity not appearing in game
- Check that the art group is in the `.gd` file
- Check that the `.o` file is in the `.gd` file
- Check that the `goal-src` line is in `game.gp`
- Run Export & Build again — the addon regenerates all of these automatically

### Enemy spawns but has no AI / idles forever
- bsphere is too small — enemies require 120m bsphere radius for AI to activate. The addon sets this automatically.
- Enemy code not loaded — check the `.gd` and `game.gp` entries.
- Nav-unsafe enemy without workaround — the addon injects `nav-mesh-sphere` automatically, but check the actor has `og_nav_radius` set in its custom properties.

### Game crashes on level load
- Remove actors one at a time to isolate the cause.
- Known bad actor: **bonelurker** — avoid until the crash is resolved.
- Check the GOALC console for type redefinition errors.
