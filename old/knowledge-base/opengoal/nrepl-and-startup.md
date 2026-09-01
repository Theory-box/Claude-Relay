# OpenGOAL — nREPL, startup.gc, and Launch Sequencing

**Source files analyzed:**
- `goalc/main.cpp` — nREPL server init, startup file execution
- `common/repl/nrepl/ReplServer.cpp` / `ReplServer.h` / `ReplClient.cpp`
- `common/cross_sockets/XSocketServer.cpp` — bind/listen failure paths
- `common/repl/repl_wrapper.cpp`
- `goalc/compiler/compilation/CompilerControl.cpp` — `run_after_listen` trigger

---

## 1. Wire Protocol (CRITICAL — sending raw text causes "Bad message" errors)

**Message format** (from `ReplClient.cpp`):
```
[u32 length, little-endian][u32 type=10, little-endian][utf-8 string bytes]
```

Message types (`ReplServer.h`): `PING=0, EVAL=10, SHUTDOWN=20`

**Python implementation:**
```python
import struct, socket

def goalc_send(cmd, timeout=5):
    EVAL_TYPE = 10
    try:
        with socket.create_connection(("localhost", GOALC_PORT), timeout=10) as s:
            encoded = cmd.encode("utf-8")
            header = struct.pack("<II", len(encoded), EVAL_TYPE)
            s.sendall(header + encoded)
            chunks = []
            s.settimeout(timeout)
            while True:
                try:
                    c = s.recv(4096)
                    if not c: break
                    chunks.append(c)
                    if b"g >" in c or b"g  >" in c: break
                except socket.timeout: break
            return b"".join(chunks).decode(errors="replace")
    except ConnectionRefusedError: return None
    except Exception as e: return f"ERROR:{e}"
```

---

## 2. Port Conflicts

Default port is **8181**. Known conflict:
- `3dxnlserver.exe` (3Dconnexion SpaceMouse) permanently holds 8181
- Results in **"nREPL: DISABLED"** — all `goalc_send()` silently return `None`

**Fix:** Scan for free port starting at 8182, pass `--port N` to GOALC:
```python
def find_free_nrepl_port(start=8182, end=8192):
    for port in range(start, end):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.1).close()
        except ConnectionRefusedError:
            return port  # free
    return 8183  # fallback
```

---

## 3. startup.gc Sequencing

The sentinel comment splits execution into two sections:
```scheme
(lt)                          ; run_before_listen — fires at GOALC startup
;; og:run-below-on-listen     ; SENTINEL
(bg 'my-level-vis)            ; run_after_listen — fires when (lt) connects to GK
```

- **run_before_listen**: Runs immediately at GOALC startup. Put `(lt)` here.
- **run_after_listen**: Runs once `(lt)` successfully connects to GK.
- **Do NOT put `(bg)` or `(start)` in run_after_listen** — this re-fires every time GK reconnects (which happens repeatedly during normal play), causing `[Warning] REPL Error: Compilation generated code, but wasn't supposed to` spam.

**Correct approach (confirmed working):** startup.gc contains ONLY `(lt)`. Send `(bg)` and `(start)` manually via `goalc_send()` after polling confirms `*game-info*` is live.

---

## 4. Readiness Check — `*game-info*`

GAME.CGO takes ~60s to link. During this time `*game-info*` is undefined.
Calling `(start)` too early causes: `The symbol *game-info* was looked up as a global variable, but it does not exist.`

**Correct readiness poll:**
```python
# WRONG — defined? does not exist in GOAL
"(if (defined? '*game-info*) 'ready 'wait)"

# WRONG — matches console noise like "Listener: ready", "nREPL: Listening" → false positive
if r and "ready" in r:

# CORRECT — match the GOAL symbol return value specifically
"(if (nonzero? *game-info*) 'ready 'wait)"
if r and "'ready" in r:   # note leading quote — matches GOAL symbol 'ready only
```

`*game-info*` is initialized with `(when (or (not *game-info*) (zero? *game-info*)) ...)` in `game-info-h.gc`, so `(nonzero? *game-info*)` returns truthy once GAME.CGO finishes.

---

## 5. Spawning the Player

After `*game-info*` is ready, spawn with an **explicit continue-point name**:
```python
# WRONG — uses current checkpoint (village1), not your level
"(start 'play (get-or-create-continue! *game-info*))"

# CORRECT — uses your level's continue-point with fallback (confirmed working)
f"(start 'play (or (get-continue-by-name *game-info* \"{name}-start\") (get-or-create-continue! *game-info*)))"
```

`get-continue-by-name` is defined in `game-info.gc` line 88. Returns `#f` if not found, hence the `or` fallback.

Continue-point names are set by `(bg 'level-vis)` via `set-continue!` to the level's first entry in `:continues`. The addon names them `{levelname}-start` for the first `SPAWN_` empty.

---

## 6. Full Confirmed Working Play Button Sequence

```
1. kill_gk() + kill_goalc()
2. find free port (8182+)
3. write_startup_gc(["(lt)"])   ← ONLY (lt), nothing in run_after_listen
4. launch_goalc(port=N, wait_for_nrepl=True)
5. launch_gk()
6. Poll every 0.5s: (if (nonzero? *game-info*) 'ready 'wait)
   → check: "'ready" in r  (leading quote required — avoids console noise false-positive)
7. When ready: goalc_send("(bg '{name}-vis)")
8. time.sleep(1.0)
9. goalc_send("(start 'play (or (get-continue-by-name ...) (get-or-create-continue! ...)))")
```

Wait up to 120s (240 × 0.5s) for readiness.

**Why (bg) is NOT in startup.gc:** `run_after_listen` fires every time GK reconnects — which happens repeatedly during normal play. Putting `(bg)` there causes repeated `[Warning] REPL Error: Compilation generated code, but wasn't supposed to` every few seconds after launch.

---

## 7. Module Cache Gotcha (Blender)

When installing an updated addon `.py` file in Blender, always **close and reopen Blender** after installing. Blender caches Python modules by filename — renaming a file without restarting loads the stale cached version from the previous name.
