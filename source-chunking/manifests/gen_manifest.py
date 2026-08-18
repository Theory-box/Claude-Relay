#!/usr/bin/env python3
"""
gen_manifest.py - Build manifests/blender-4.4.json from compact per-chunk specs.

Every editor chunk follows the same 8-edit recipe; only a handful of anchors vary.
So we keep compact specs here and expand them to the full manifest the engine reads.
Adding a new editor = adding a spec entry, not hand-writing eight edits.

Anchors are exact substrings from the Blender v4.4.0 source tree.
"""
import json
import os

# name -> spec. 'reg' is the space-type registration line (one line, wrapped by #ifdef).
# 'rna_defs' lists every rna_def_space_<...> function to guard (block-wrapped).
# 'struct' is the RNA struct name used by the Python hasattr() self-adaptation.
# 'readiness': 'ready' = drops with just these edits; 'needs-consumer-gating' = has
#   external API callers that must also be handled before an OFF build will LINK.
SPECS = {
    "console": {
        "reg": "  ED_spacetype_console();",
        "rna_dispatch": "  rna_def_space_console(brna);",
        "rna_defs": ["static void rna_def_space_console(BlenderRNA *brna)"],
        "struct": "SpaceConsole",
        "readiness": "ready",
        "consumers": [],
    },
    "spreadsheet": {
        "reg": "  spreadsheet::register_spacetype();",
        "rna_dispatch": "  rna_def_space_spreadsheet(brna);",
        "rna_defs": ["static void rna_def_space_spreadsheet(BlenderRNA *brna)"],
        "struct": "SpaceSpreadsheet",
        "readiness": "ready",
        "consumers": [],
    },
    "outliner": {
        "reg": "  ED_spacetype_outliner();",
        "rna_dispatch": "  rna_def_space_outliner(brna);",
        "rna_defs": ["static void rna_def_space_outliner(BlenderRNA *brna)"],
        "struct": "SpaceOutliner",
        "readiness": "ready",
        "consumers": [],
    },
    "text": {
        "reg": "  ED_spacetype_text();",
        "rna_dispatch": "  rna_def_space_text(brna);",
        "rna_defs": ["static void rna_def_space_text(BlenderRNA *brna)"],
        "struct": "SpaceTextEditor",
        "readiness": "needs-consumer-gating",
        "consumers": [
            "editors/undo/undo_system_types.cc: ED_text_undosys_type registration",
            "editors/space_outliner/outliner_select.cc: ED_text_activate_in_screen (jump-to-text)",
            "makesrna/intern/rna_text_api.cc + rna_space_api.cc: Text datablock ED_text_* API",
        ],
    },
    "info": {
        "reg": "  ED_spacetype_info();",
        "rna_dispatch": "  rna_def_space_info(brna);",
        "rna_defs": ["static void rna_def_space_info(BlenderRNA *brna)"],
        "struct": "SpaceInfo",
        "readiness": "needs-consumer-gating",
        "consumers": [
            "space_info/ holds shared scene-statistics utils, NOT just the editor UI:",
            "  interface_template_status.cc: ED_info_statusbar_string_ex (status bar)",
            "  space_view3d/view3d_draw.cc: ED_info_draw_stats (viewport overlay)",
            "  windowmanager/wm_event_system.cc: ED_info_stats_clear",
            "  rna_screen.cc / rna_scene.cc: ED_info_statistics_string",
            "=> extract the stats utils out of space_info/ before this can drop cleanly",
        ],
    },
}


def guard_of(name):
    return f"WITH_SPACE_{name.upper()}"


def edits_for(name, spec):
    g = guard_of(name)
    module = f"space_{name}"
    edits = [
        {  # 1. top-level option (declaration only)
            "id": "cmake_option",
            "file": "CMakeLists.txt",
            "op": "insert_block",
            "anchor": 'option(WITH_HEADLESS "Build without graphical support (renderfarm, server mode only)" OFF)',
            "position": "after",
            "marker": f"# [chunk] {g}",
            "text": [f"# [chunk] {g}",
                     f'option({g} "Include the {module} editor" ON)'],
        },
        {  # 2. editors/ per-dir define (reaches spacetypes.cc)
            "id": "editors_define",
            "file": "source/blender/editors/CMakeLists.txt",
            "op": "insert_block",
            "anchor": "  add_subdirectory(animation)",
            "position": "before",
            "marker": f"# [chunk-def] {g}",
            "text": [f"  # [chunk-def] {g}", f"  if({g})",
                     f"    add_definitions(-D{g})", f"  endif() # {g}", ""],
        },
        {  # 3. makesrna/ per-dir define (reaches the RNA generator)
            "id": "makesrna_define",
            "file": "source/blender/makesrna/intern/CMakeLists.txt",
            "op": "insert_block",
            "anchor": "if(WITH_PYTHON)",
            "position": "before",
            "marker": f"# [chunk-def] {g}",
            "text": [f"# [chunk-def] {g}", f"if({g})",
                     f"  add_definitions(-D{g})", f"endif() # {g}", ""],
        },
        {  # 4. editors/ subdir gate
            "id": "cmake_subdir",
            "file": "source/blender/editors/CMakeLists.txt",
            "op": "cmake_if_wrap",
            "anchor": f"  add_subdirectory({module})",
        },
        {  # 5. space-type registration gate
            "id": "spacetype_register",
            "file": "source/blender/editors/space_api/spacetypes.cc",
            "op": "c_ifdef_line",
            "anchor": spec["reg"],
        },
        {  # 6. RNA dispatch gate
            "id": "rna_dispatch",
            "file": "source/blender/makesrna/intern/rna_space.cc",
            "op": "c_ifdef_line",
            "anchor": spec["rna_dispatch"],
        },
    ]
    # 7. RNA definition gate(s) - one per rna_def_space_* function
    for i, sig in enumerate(spec["rna_defs"]):
        edits.append({
            "id": f"rna_definition_{i}",
            "file": "source/blender/makesrna/intern/rna_space.cc",
            "op": "c_ifdef_block",
            "anchor": sig,
        })
    # 8. Python UI self-adaptation
    edits.append({
        "id": "python_ui",
        "file": "scripts/startup/bl_ui/__init__.py",
        "op": "py_conditional_module",
        "anchor": f'    "{module}",',
        "module": module,
        "rna_type": spec["struct"],
    })
    return edits


def build():
    chunks = {}
    for name, spec in SPECS.items():
        chunks[f"space_{name}"] = {
            "guard": guard_of(name),
            "description": f"{name} editor",
            "rna_type": spec["struct"],
            "readiness": spec["readiness"],
            "consumers": spec["consumers"],
            "edits": edits_for(name, spec),
        }
    return {
        "blender_version": "4.4",
        "notes": ("Chunk plug-point map. Each editor becomes a WITH_SPACE_<NAME> option "
                  "(default ON). The define is declared per-directory in editors/ and "
                  "makesrna/intern/ (mirrors Blender's own WITH_* re-declaration) so it "
                  "reaches both the editors library and the makesrna generator. Python UI "
                  "self-adapts via hasattr(bpy.types, ...). readiness: 'ready' drops with "
                  "just these edits; 'needs-consumer-gating' has external API callers "
                  "(see consumers) that must be handled before an OFF build will link."),
        "chunks": chunks,
    }


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(__file__), "blender-4.4.json")
    with open(out, "w") as f:
        json.dump(build(), f, indent=2)
        f.write("\n")
    m = build()
    ready = [k for k, v in m["chunks"].items() if v["readiness"] == "ready"]
    gated = [k for k, v in m["chunks"].items() if v["readiness"] != "ready"]
    print(f"wrote {out}")
    print(f"  {len(m['chunks'])} chunks: {len(ready)} ready {ready}, "
          f"{len(gated)} needs-consumer-gating {gated}")
