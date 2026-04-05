# OpenGOAL — nREPL, startup.gc, and Launch Sequencing

**Source files analyzed:**
- `goalc/main.cpp` — nREPL server init, startup file execution
- `common/repl/nrepl/ReplServer.cpp` / `ReplServer.h`
- `common/cross_sockets/XSocketServer.cpp` — bind/listen failure paths
- `common/repl/repl_wrapper.cpp` — `find_repl_username`, `load_repl_config`, `load_user_startup_file`
- `common/repl/config.h` — `Config` struct, default port 8181
- `goalc/compiler/compilation/CompilerControl.cpp` — `run_after_listen` trigger

---

## 1. What nREPL Is

nREPL is a TCP socket server that GOALC opens on port 8181 at startup.  
Any external process (the Blender addon, a script, a terminal client) can send GOAL expressions as text strings to this port and GOALC will evaluate them as if typed at the interactive REPL prompt.

The addon sends all commands — `(lt)`, `(bg)`, `(mi)`, `(start)` — via this socket through `goalc_send()`.

---

## 2. "nREPL: DISABLED" — What It Means and Why It Happens

GOALC prints `nREPL: DISABLED` in red when `init_server()` returns `false`.

`init_server()` fails when `bind()` fails — i.e. **port 8181 is already in use by another process**.

**The most common cause:** a previous GOALC instance is still running. The addon (v9 and earlier) only killed GK before relaunching, leaving the old GOALC alive and holding port 8181. The new GOALC starts, loses the port bind, and shows DISABLED. Every subsequent `goalc_send()` returns `None` silently — nothing is sent to the game.

**Diagnosis:** if you see `nREPL: DISABLED` in the GOALC console, there is a stale GOALC process. Kill all GOALC instances via Task Manager (Windows) or `pkill goalc` before relaunching.

**Fix in addon:** always call `kill_goalc()` before `launch_goalc()`.

---

## 3. goalc_send() Behavior When nREPL Is Disabled

```python
def goalc_send(cmd, timeout=GOALC_TIMEOUT):
    try:
        with socket.create_connection(("localhost", 8181), timeout=10) as s:
            ...
    except ConnectionRefusedError:
        return None   # ← silent failure, no error raised
```

When nREPL is DISABLED, `ConnectionRefusedError` is caught and `None` is returned. The caller gets `None` and typically continues. There is **no visible error** — this is why the bug was hard to diagnose.

**goalc_ok()** — the addon's "is GOALC alive and accepting connections" check:
```python
def goalc_ok():
    return goalc_send("(+ 1 1)", timeout=3) is not None
```
Returns `False` when nREPL is disabled. The addon used this to decide whether to relaunch — but `goalc_ok() == False` could mean either "GOALC not running" OR "GOALC running with DISABLED nREPL". Both need a kill+relaunch.

---

## 4. startup.gc — The Correct Way to Sequence Launch Commands

### Location
`data/goal_src/user/<username>/startup.gc`

Username is determined by:
1. `data/goal_src/user/user.txt` content (if it exists and is valid)
2. Or: the single folder name inside `data/goal_src/user/` (if there's only one)

The addon writes `user.txt` with username `"blender"` and creates the startup.gc at `data/goal_src/user/blender/startup.gc`.

### The Sentinel: `og:run-below-on-listen`

startup.gc is split into two sections by this sentinel comment:

```
(lt)                          ← run_before_listen: runs immediately at GOALC startup
;; og:run-below-on-listen     ← the sentinel line
(bg 'my-level-vis)            ← run_after_listen: runs ONLY after (lt) connects to GK
(start 'play ...)             ← run_after_listen: runs ONLY after (lt) connects to GK
```

**`run_before_listen`** — executed by `repl_startup_func()` right after GOALC boots.  
**`run_after_listen`** — executed inside `compile_repl_listen_to_target()` immediately after `(lt)` successfully connects.

This means `run_after_listen` commands are **triggered by GK being ready**, not by a sleep timer. This is far more reliable than `time.sleep(8.0)` + manual `goalc_send("(lt)")`.

### DO NOT use GOAL runtime functions in startup.gc

`(suspend-for (seconds 3))` does NOT work in startup.gc. It's a GOAL runtime function that only works inside a running GOAL process. In the REPL evaluator context it will error. Use the sentinel instead — `run_after_listen` provides the equivalent "wait until GK is up" guarantee.

---

## 5. The Complete Correct Launch Sequence

### For "Play" (no compile):

```
1. kill_gk()         — ensure GK is dead
2. kill_goalc()      — FREE PORT 8181
3. write_startup_gc([
       "(lt)",
       ";; og:run-below-on-listen",
       f"(bg '{name}-vis)",
       "(start 'play (get-or-create-continue! *game-info*))",
   ])
4. launch_goalc(wait_for_nrepl=True)   — waits for port 8181 to confirm open
5. launch_gk()
   → GK boots → (lt) connects → (bg) loads level → (start) spawns player
```

### For "Export, Build & Play":

```
Phase 1: write level files (JSONC, GD, GC, level-info, game.gp)
Phase 2: compile
  - kill_gk()
  - if not goalc_ok(): kill_goalc() + launch_goalc(wait_for_nrepl=True)
  - goalc_send("(mi)")   ← compile via existing nREPL
Phase 3: launch
  - write_startup_gc([...same as above...])
  - kill_goalc()         ← FREE PORT 8181 (GOALC that just compiled)
  - launch_goalc(wait_for_nrepl=True)   ← fresh GOALC reads new startup.gc
  - launch_gk()
```

The key insight for "Build & Play": GOALC that did the compile must be killed before the new one launches, otherwise port 8181 is taken and the new instance can't open nREPL.

---

## 6. What (bg), (lt), and (start) Actually Do

### `(lt)` — Listen to Target
Defined in `goalc/compiler/compilation/CompilerControl.cpp`.  
Attempts to connect the GOALC listener to the running GK process (GOAL runtime).  
After connecting, automatically runs all `run_after_listen` commands from startup.gc.

### `(bg level-name-symbol)` — Begin Game
Defined in `goal_src/jak1/engine/level/level.gc:941`.  
- Loads the level's DGO  
- Calls `set-continue!` on the first entry in the level's `:continues` list  
- Sets `*load-state*` want/display fields  
- Does **NOT** kill or respawn the player  
- Does **NOT** call `start`

### `(start mode continue-point)` — Spawn Player
Defined in `goal_src/jak1/engine/target/logic-target.gc:1293`.  
- Calls `stop` (kills current player process)  
- Calls `process-spawn target :init init-target` with the continue-point  
- Player spawns at `:trans` of the continue-point, enters `target-continue` state, waits for level `'active`, then enters `target-stance` (gameplay)

**The correct call after `(bg)`:**
```lisp
(start 'play (get-or-create-continue! *game-info*))
```
`get-or-create-continue!` returns `current-continue`, which `(bg)` already set to the level's first continue-point. This kills the boot-sequence player (who is falling in the void) and spawns fresh at your `SPAWN_start` location.

---

## 7. repl-config.json

Optional per-user config at `data/goal_src/user/<username>/repl-config.json`.  
Can override nREPL port:

```json
{
  "nreplPort": 8181
}
```

Default port is 8181, defined in `common/repl/config.h`. No need to set this unless running multiple GOALC instances simultaneously (unusual).

---

## 8. Debugging nREPL Issues Checklist

1. **See "nREPL: DISABLED"?** → Kill all GOALC processes, relaunch.
2. **goalc_send() returning None?** → Either GOALC not running, or nREPL disabled. Check GOALC console.
3. **Commands sent but nothing happens in game?** → `(lt)` may not have connected. Check GOALC console for "Listener connected" message.
4. **startup.gc commands not running?** → Check username resolution. Does `data/goal_src/user/user.txt` contain exactly `blender`? Does the file `data/goal_src/user/blender/startup.gc` exist?
5. **run_after_listen commands not running?** → The sentinel line must contain the exact text `og:run-below-on-listen` (as a comment anywhere on the line). Check the generated startup.gc content.
