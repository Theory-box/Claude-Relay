# texture_diagnostic.py
# ──────────────────────────────────────────────────────────────────────────────
# Run this in Blender: Scripting tab → Open → Run Script
# (Or paste into the text editor and hit Run Script)
#
# Reports everything the texturing panel will need to find, so you can confirm
# paths are correct before any panel code is written.
# ──────────────────────────────────────────────────────────────────────────────

import bpy
from pathlib import Path

out = []

def log(msg=""):
    out.append(msg)
    print(msg)

def section(title):
    log()
    log("=" * 60)
    log(f"  {title}")
    log("=" * 60)

def ok(label, value=""):
    log(f"  ✓  {label}" + (f"  →  {value}" if value else ""))

def warn(label, value=""):
    log(f"  ⚠  {label}" + (f"  →  {value}" if value else ""))

def err(label, value=""):
    log(f"  ✗  {label}" + (f"  →  {value}" if value else ""))

def show_dir(label, path, max_entries=12):
    if path.exists() and path.is_dir():
        entries = sorted(path.iterdir())
        ok(f"{label} exists", str(path))
        log(f"       {len(entries)} item(s):")
        for e in entries[:max_entries]:
            kind = "DIR " if e.is_dir() else "FILE"
            log(f"         [{kind}] {e.name}")
        if len(entries) > max_entries:
            log(f"         ... and {len(entries) - max_entries} more")
    else:
        err(f"{label} NOT FOUND", str(path))


# ── 1. Addon preferences ──────────────────────────────────────────────────────
section("1. Addon Preferences")

prefs_mod = bpy.context.preferences.addons.get("opengoal_tools")
if not prefs_mod:
    err("opengoal_tools addon is not enabled")
    log("\nCannot continue — enable the addon first.")
else:
    ok("Addon is enabled")
    prefs = prefs_mod.preferences
    data_path = getattr(prefs, "data_path", "").strip()
    exe_path  = getattr(prefs, "exe_path",  "").strip()
    log(f"  data_path = '{data_path}'")
    log(f"  exe_path  = '{exe_path}'")

    if not data_path:
        err("data_path is not set in addon preferences")
        log("  → Set it in Edit > Preferences > Add-ons > OpenGOAL Tools")
    else:
        data_root = Path(data_path)
        ok("data_path is set", str(data_root))

        # ── 2. Data root structure ────────────────────────────────────────────
        section("2. Data Root Structure")
        show_dir("data_root", data_root)

        data_dir = data_root / "data"
        show_dir("data_root / data", data_dir)

        # ── 3. Decompiler output root ─────────────────────────────────────────
        section("3. Decompiler Output")

        decomp_root = data_dir / "decompiler_out"
        show_dir("decompiler_out", decomp_root)

        jak1_root = decomp_root / "jak1"
        show_dir("decompiler_out / jak1", jak1_root)

        # ── 4. Texture directory ──────────────────────────────────────────────
        section("4. Texture Directory")

        tex_root = jak1_root / "textures"
        if tex_root.exists():
            tpage_dirs = sorted([d for d in tex_root.iterdir() if d.is_dir()])
            ok("textures/ directory found", str(tex_root))
            log(f"  {len(tpage_dirs)} tpage folder(s) found:")

            total_pngs = 0
            sample_pngs = []
            for d in tpage_dirs:
                pngs = list(d.glob("*.png"))
                total_pngs += len(pngs)
                log(f"    [{len(pngs):4d} PNGs]  {d.name}")
                if pngs and len(sample_pngs) < 3:
                    sample_pngs.append(pngs[0])

            log()
            ok(f"Total PNGs found across all tpages", str(total_pngs))

            if total_pngs == 0:
                warn("No PNG files found in any tpage folder")
                log("  → The decompiler was probably run without save_texture_pngs: true")
                log("  → In your OpenGOAL install, edit:")
                log(f"    {data_dir / 'decompiler' / 'config' / 'jak1' / 'jak1_config.jsonc'}")
                log('  → Find "save_texture_pngs": false and change to true')
                log("  → Then re-run the decompiler/extractor")
            else:
                log()
                log("  Sample PNG paths (confirm these look right):")
                for p in sample_pngs:
                    log(f"    {p}")

        else:
            err("textures/ directory NOT FOUND", str(tex_root))
            log("  → The decompiler has not been run, or decompiler_out is missing")
            log("  → Also check if the path is in a different location:")

            # Try alternate locations
            alts = [
                data_root / "decompiler_out" / "jak1" / "textures",
                data_root / "textures",
                data_root / "jak1" / "textures",
            ]
            for alt in alts:
                if alt.exists():
                    warn("Found textures at alternate path", str(alt))
                else:
                    log(f"    (not at {alt})")

        # ── 5. tex-info.min.json ──────────────────────────────────────────────
        section("5. tex-info.min.json (texture name database)")

        tex_info_paths = [
            data_root / "decompiler" / "config" / "jak1" / "ntsc_v1" / "tex-info.min.json",
            data_dir  / "decompiler" / "config" / "jak1" / "ntsc_v1" / "tex-info.min.json",
        ]
        found_tex_info = None
        for p in tex_info_paths:
            if p.exists():
                found_tex_info = p
                break

        if found_tex_info:
            ok("tex-info.min.json found", str(found_tex_info))
            size_kb = found_tex_info.stat().st_size // 1024
            log(f"  File size: {size_kb} KB")
        else:
            err("tex-info.min.json NOT FOUND")
            log("  Searched:")
            for p in tex_info_paths:
                log(f"    {p}")
            log("  → This file is part of the jak-project source, not the install")
            log("  → It should be at: <data_path>/decompiler/config/jak1/ntsc_v1/tex-info.min.json")

        # ── 6. GLB files (confirm decompiler_out structure matches model preview) ──
        section("6. GLB Files (model preview reference)")

        glb_root = jak1_root / "levels"
        if glb_root.exists():
            level_dirs = sorted([d for d in glb_root.iterdir() if d.is_dir()])
            ok("levels/ (GLB root) found", str(glb_root))
            log(f"  {len(level_dirs)} level folder(s):")
            for d in level_dirs[:10]:
                glbs = list(d.glob("*.glb"))
                log(f"    [{len(glbs):3d} GLBs]  {d.name}")
            if len(level_dirs) > 10:
                log(f"    ... and {len(level_dirs) - 10} more")

            # Check a known GLB to confirm the path pattern the addon uses
            probe = jak1_root / "levels" / "beach" / "babak-lod0.glb"
            if probe.exists():
                ok("Probe GLB (babak-lod0.glb) found — GLB path pattern confirmed")
            else:
                warn("Probe GLB (babak-lod0.glb) not found — model previews may not work")
                log(f"  Expected: {probe}")
        else:
            err("levels/ (GLB root) NOT FOUND", str(glb_root))

        # ── 7. Addon path construction (what the panel will use) ──────────────
        section("7. Addon Texture Path (what the panel will reference)")

        tex_panel_root = data_dir / "decompiler_out" / "jak1" / "textures"
        log(f"  Panel will look for textures at:")
        log(f"    {tex_panel_root}")
        log()
        log(f"  Individual tpage folder pattern:")
        log(f"    {tex_panel_root / '<tpage_name>'}")
        log()
        log(f"  Individual PNG pattern:")
        log(f"    {tex_panel_root / '<tpage_name>' / '<texture_name>.png'}")

        if tex_panel_root.exists():
            ok("This path EXISTS — panel will work")
        else:
            err("This path does NOT exist — panel cannot load textures")

        # ── 8. Summary ────────────────────────────────────────────────────────
        section("8. Summary")

        checks = {
            "Addon enabled":          prefs_mod is not None,
            "data_path set":          bool(data_path),
            "data_root exists":       data_root.exists() if data_path else False,
            "decompiler_out exists":  decomp_root.exists() if data_path else False,
            "textures/ exists":       tex_root.exists() if data_path else False,
            "PNGs present":           total_pngs > 0 if data_path and tex_root.exists() else False,
            "tex-info.min.json":      found_tex_info is not None,
            "GLB probe passes":       (jak1_root / "levels" / "beach" / "babak-lod0.glb").exists() if data_path else False,
        }

        all_ok = all(checks.values())
        for label, passed in checks.items():
            (ok if passed else err)(label)

        log()
        if all_ok:
            log("  ✓  Everything looks good — texturing panel should work.")
        else:
            failed = [k for k, v in checks.items() if not v]
            log(f"  ✗  {len(failed)} issue(s) need fixing before the panel will work.")
            log("     See sections above for details on each failed check.")

# ── Print full output to console as well ─────────────────────────────────────
log()
log("─" * 60)
log("  Full output printed to System Console.")
log("  Window > Toggle System Console if not visible.")
log("─" * 60)
