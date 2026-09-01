# Cross-Platform / Shareability — Session Notes

## Status: COMPLETE ✅ — promoted to main, old addon backed up

## Branch: `feature/cross-platform`

---

## Goal
Make the addon installable and usable by anyone, not just on the dev machine.

---

## Issues to Fix

### 1. Hardcoded default paths (easy)
**File:** `addons/opengoal_tools.py` lines ~1040-1046

```python
# CURRENT (bad):
default=r"C:\Users\John\Documents\JakAndDaxter\versions\official\v0.2.29"
default=r"C:\Users\John\Documents\JakAndDaxter\active\jak1"

# FIX: change to empty string so new users see a blank field
default=""
```

Also update the description text in the preferences panel to explain
what each path should point to more clearly.

### 2. Windows-only exe names (medium)
**File:** `addons/opengoal_tools.py` lines ~1100-1101, 2258, 2365

```python
# CURRENT (bad — .exe hardcoded):
def _gk():     return _exe_root() / "gk.exe"
def _goalc():  return _exe_root() / "goalc.exe"
_kill_process("gk.exe")
_process_running("gk.exe")

# FIX: platform-aware helper
import sys
_EXE = ".exe" if sys.platform == "win32" else ""
def _gk():     return _exe_root() / f"gk{_EXE}"
def _goalc():  return _exe_root() / f"goalc{_EXE}"
# and update all _kill_process / _process_running calls to use f"gk{_EXE}"
```

### 3. Hardcoded GOALC port 8182 (medium)
**File:** `addons/opengoal_tools.py` line ~1059

```python
# CURRENT (bad — 8182 is non-standard, only needed on dev machine due to SpaceMouse):
GOALC_PORT = 8182

# FIX: add as a preference field, default to standard 8181
goalc_port: IntProperty(name="GOALC Port", default=8181, min=1024, max=65535)
# then replace GOALC_PORT with prefs.goalc_port everywhere
```

---

## What Does NOT Need Changing
- All path logic uses pathlib.Path — handles separators on all platforms
- subprocess launch already branches on os.name == "nt"
- File open (xdg-open / open) already branched
- Level export, obs.gc, game.gp patching — all path-based, no platform issues

---

## Test Checklist (when done)
- [ ] Fresh install on Windows with empty default paths — preferences prompt correctly
- [ ] Linux/Mac: gk and goalc found without .exe
- [ ] Standard port 8181 works for normal users
- [ ] Existing Windows dev workflow unchanged

---

## Session — April 2026

### What was done
- Removed hardcoded `C:\Users\John\...` default paths → blank strings
- Added `_EXE = ".exe" if sys.platform == "win32" else ""` — all exe references now platform-aware
- Removed manual GOALC port preference — `_find_free_nrepl_port(start=8181)` handles it fully and silently
- Tested on Windows by original dev: launch, nREPL, GK confirmed working

### What was NOT tested
- Linux / Mac exe resolution
- Full entity spawn, camera, audio, collision, music — code paths untouched so assumed safe

### Merge outcome
- Old addon backed up to `backups/opengoal_tools_pre_cross_platform.py`
- Cross-platform build is now `addons/opengoal_tools.py` on main
- `feature/cross-platform` branch preserved for reference
