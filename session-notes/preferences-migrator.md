# Preferences Migrator — session notes

**Branch:** `feature/preferences-migrator` (off `main`)
**Blender target:** 4.2 and 4.4 (installs as a legacy add-on in both)

## Goal
Move Blender user preferences between installed versions without manually
digging through `~/Library/Application Support/Blender/<version>/config/`.
Originating case: pull 4.4 preferences into 4.2 on macOS.

## v1.0.0 packaged as a Blender 4.2+ EXTENSION (was legacy bl_info)
First cut was a legacy `bl_info` add-on. It worked logically but failed in
practice on the install step: on 4.2+ the main "Install from Disk" expects an
extension (manifest), while `bl_info`-only add-ons need the separate "Install
legacy Add-on" path and land DISABLED. Converted to a proper extension:
- Added `blender_manifest.toml` (schema 1.0.0, type add-on, blender_version_min
  4.2.0). Removed `bl_info`.
- `bl_idname` / preferences lookup now use `__package__` (installed module name
  is `bl_ext.user_default.preferences_migrator`), not `__name__`.
- Result: installs via normal button AND auto-enables on install.

## Architecture (v1.0.0)
Single-folder extension (`addons/preferences_migrator/`: `__init__.py` +
`blender_manifest.toml`).

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

## Status — TESTED against real Blender 4.2.23 LTS + 4.4.3 (Linux)
Harness: `BLENDER_USER_RESOURCES` pointed at a fake `.../Blender/{4.2,4.4}`
tree; marker `ui_scale` set per version to prove real prefs carried over.
- Extension installs via `extensions.package_install_files` in BOTH 4.2 & 4.4
  and AUTO-ENABLES (no separate enable step).
- Dropdown lists the sibling version; operator copies its userpref.blend into
  the running version; copied file byte-identical to source.
- 4.4 -> 4.2 DOWNGRADE: 4.2 loaded the migrated file and applied ui_scale=1.44
  (a 4.4-authored value) with no error.
- Overwrite creates timestamped `userpref.blend.bak-YYYYmmdd-HHMMSS`.
- Note: after migrating, the enabled-addon list also comes from the migrated
  userpref, so the add-on may show disabled on next launch (expected).

## Not verified
- Not run on actual macOS (tested on Linux; path logic is OS-agnostic via
  resource_path('USER'), so expected to behave identically).
- Not merged to `main`. Awaiting user confirmation on their Mac + merge
  permission.

## TODO / open questions
- Optional: hot-reload without restart (needs per-version operator research).
