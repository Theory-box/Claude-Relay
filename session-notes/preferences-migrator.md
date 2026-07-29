# Preferences Migrator — session notes

**Branch:** `feature/preferences-migrator` (off `main`)
**Blender target:** 4.2 and 4.4 (installs as a legacy add-on in both)

## Goal
Move Blender user preferences between installed versions without manually
digging through `~/Library/Application Support/Blender/<version>/config/`.
Originating case: pull 4.4 preferences into 4.2 on macOS.

## Architecture (v1.0.0)
Single-file legacy add-on (`addons/preferences_migrator/__init__.py`).

1. `bpy.utils.resource_path('USER')` gives the running version's user folder
   (e.g. `.../Blender/4.4`); its parent holds all versions as siblings.
2. Scan siblings matching `^\d+\.\d+$`; keep only those with a
   `config/userpref.blend`. List them (minus the current version) in an
   `EnumProperty` dropdown on the add-on's `AddonPreferences`.
3. On copy: back up the destination `userpref.blend` (and `startup.blend` if
   opted in) to a timestamped `.bak-YYYYmmdd-HHMMSS` in the same config folder,
   then `shutil.copy2` the source file in.
4. No mid-session reload (no stable cross-version operator for it) — the add-on
   reports success and asks the user to RESTART Blender.

## Notes / gotchas
- Enum items are held in a module-global (`_enum_cache`) to dodge Blender's
  known GC-of-Python-enum-strings bug.
- Direction caveat: newer -> older is a preference-format downgrade and may not
  fully apply; same-version and old -> new are the happy paths.
- A source version only appears in the dropdown once it has been launched at
  least once (so a `config/userpref.blend` exists).

## Status
- Syntax-checked (`py_compile`) only — NOT yet run against a live Blender.
- Not merged to `main`. Awaiting user confirmation it works + merge permission.

## TODO / open questions
- Verify `resource_path('USER')` return + install flow on the user's Mac.
- Optional: hot-reload without restart (needs per-version operator research).
