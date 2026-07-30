#!/usr/bin/env python3
"""
blend_compat_scanner.py
=======================
Scan a .blend file's node trees and report every node that will break (or has
already broken) when the file is taken to an older Blender version.

Two modes, auto-detected from what it finds:

  PREDICT  - run this inside the SOURCE version (e.g. 4.4) with a compat DB.
             For each node it looks up the real bl_idname in the DB and reports
             missing/changed nodes with a suggested action, BEFORE downgrading.

  DETECT   - run this inside the TARGET version (e.g. 4.2) on a file that has
             already been opened there. Unknown node types collapse to
             bl_idname == 'NodeUndefined' (name preserved). No DB required -
             this is the "just tell me what is broken in this file right now"
             view.

Both modes share one traversal that walks: geometry-nodes modifiers, materials,
worlds, the scene compositor, and every nested node group (cycle-safe).

Usage (headless):
  blender -b file.blend --python blend_compat_scanner.py -- \
          [--target 4.2] [--db compat_db_4.4_to_4.2.json] [--json out.json]

Nothing here edits or deletes anything. It only reports. Irreversible cases
(e.g. the For-Each zone) are flagged, never auto-removed - the user decides.
"""

import bpy
import sys
import os
import json


# --------------------------------------------------------------------------- #
# arg parsing (everything after the standalone "--" belongs to us)
# --------------------------------------------------------------------------- #
def parse_args():
    argv = sys.argv
    argv = argv[argv.index("--") + 1:] if "--" in argv else []
    opts = {"target": None, "db": None, "json": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--target", "--db", "--json") and i + 1 < len(argv):
            opts[a[2:]] = argv[i + 1]
            i += 2
        else:
            i += 1
    # sensible default: a DB sitting next to this script
    if opts["db"] is None:
        here = os.path.dirname(os.path.abspath(__file__))
        for f in sorted(os.listdir(here)):
            if f.startswith("compat_db_") and f.endswith(".json"):
                opts["db"] = os.path.join(here, f)
                break
    return opts


def load_db(path):
    if path and os.path.exists(path):
        try:
            return json.load(open(path))
        except Exception as e:
            print(f"[warn] could not read DB {path}: {e}")
    return None


# --------------------------------------------------------------------------- #
# traversal - yields (node, location_string) for every node in the file
# --------------------------------------------------------------------------- #
def _walk_tree(tree, where, seen, out):
    if tree is None or tree.name in seen:
        return
    seen.add(tree.name)
    for n in tree.nodes:
        out.append((n, where))
        sub = getattr(n, "node_tree", None)   # GROUP nodes reference a sub-tree
        if sub is not None:
            _walk_tree(sub, f"{where} > Group '{sub.name}'", seen, out)


def collect_nodes():
    """Return [(node, location_string), ...] across the whole file."""
    out = []
    seen = set()
    for obj in bpy.data.objects:
        for mod in obj.modifiers:
            if mod.type == 'NODES' and mod.node_group:
                _walk_tree(mod.node_group,
                           f"Object '{obj.name}' > GN modifier '{mod.name}'",
                           seen, out)
    for mat in bpy.data.materials:
        if mat.use_nodes and mat.node_tree:
            _walk_tree(mat.node_tree, f"Material '{mat.name}'", seen, out)
    for w in bpy.data.worlds:
        if w.use_nodes and w.node_tree:
            _walk_tree(w.node_tree, f"World '{w.name}'", seen, out)
    for sc in bpy.data.scenes:
        if sc.use_nodes and sc.node_tree:
            _walk_tree(sc.node_tree, f"Scene '{sc.name}' > Compositor", seen, out)
    # any standalone node groups not reached above (unlinked assets etc.)
    for g in bpy.data.node_groups:
        _walk_tree(g, f"Node group '{g.name}' (unlinked)", seen, out)
    return out


# --------------------------------------------------------------------------- #
# non-node settings check (predict mode only; props only exist in the source
# version, so this is naturally skipped when running in the older target)
# --------------------------------------------------------------------------- #
SETTINGS_ACCESSORS = {
    "SceneEEVEE":     lambda: [(f"Scene '{s.name}' > EEVEE", s.eevee)
                               for s in bpy.data.scenes if hasattr(s, "eevee")],
    "RenderSettings": lambda: [(f"Scene '{s.name}' > Render", s.render)
                               for s in bpy.data.scenes],
    "World":          lambda: [(f"World '{w.name}'", w) for w in bpy.data.worlds],
    "Material":       lambda: [(f"Material '{m.name}'", m) for m in bpy.data.materials],
    "Object":         lambda: [(f"Object '{o.name}'", o) for o in bpy.data.objects],
    "Curves":         lambda: [(f"Curves '{c.name}'", c)
                               for c in getattr(bpy.data, "hair_curves", [])],
    "Mesh":           lambda: [(f"Mesh '{me.name}'", me) for me in bpy.data.meshes],
    "SunLight":       lambda: [(f"Light '{l.name}'", l) for l in bpy.data.lights if l.type == "SUN"],
    "PointLight":     lambda: [(f"Light '{l.name}'", l) for l in bpy.data.lights if l.type == "POINT"],
    "AreaLight":      lambda: [(f"Light '{l.name}'", l) for l in bpy.data.lights if l.type == "AREA"],
}


def check_settings(db):
    """Flag lost settings only where they are actually set away from default."""
    out = []
    for struct, props in (db or {}).get("settings_lost", {}).items():
        acc = SETTINGS_ACCESSORS.get(struct)
        if not acc:
            continue
        try:
            items = acc()
        except Exception:
            continue
        for loc, obj in items:
            for p in props:
                if not hasattr(obj, p):
                    continue
                try:
                    val = getattr(obj, p)
                    default = obj.bl_rna.properties[p].default
                except Exception:
                    continue
                if val != default:
                    out.append({"location": loc, "setting": f"{struct}.{p}",
                                "value": str(val)})
    return out


# --------------------------------------------------------------------------- #
# analysis
# --------------------------------------------------------------------------- #
def analyse(nodes, db):
    missing_db = (db or {}).get("missing", {})
    changed_db = (db or {}).get("changed", {})
    hits = {"undefined": [], "predicted_missing": [], "predicted_changed": []}

    for n, where in nodes:
        bl = n.bl_idname

        # DETECT: already broken in the running (older) version
        if bl == "NodeUndefined":
            hits["undefined"].append({
                "name": n.name, "location": where,
                "note": "Unknown node type - was valid in a newer version. "
                        "Original type not recoverable from this file.",
            })
            continue

        # PREDICT: real type known, cross-reference the DB
        if bl in missing_db:
            info = missing_db[bl]
            hits["predicted_missing"].append({
                "name": n.name, "type": bl, "location": where,
                "class": info.get("class"), "action": info.get("action"),
                "note": info.get("note", ""),
            })
        elif bl in changed_db:
            hits["predicted_changed"].append({
                "name": n.name, "type": bl, "location": where,
                "delta": changed_db[bl].get("delta", {}),
                "note": "Socket set differs in target version; links to "
                        "added/removed sockets will drop or revert to default.",
            })
    return hits


# --------------------------------------------------------------------------- #
# reporting
# --------------------------------------------------------------------------- #
def report(hits, settings_hits, db, opts):
    running = bpy.app.version_string
    src = (db or {}).get("source", "?")
    tgt = opts["target"] or (db or {}).get("target", "?")

    line = "=" * 68
    print("\n" + line)
    print(f" BLEND COMPATIBILITY SCAN")
    print(f"   file          : {bpy.data.filepath or '(unsaved)'}")
    print(f"   running in    : Blender {running}")
    print(f"   checking for  : {src} -> {tgt}")
    print(line)

    u = hits["undefined"]
    pm = hits["predicted_missing"]
    pc = hits["predicted_changed"]

    if u:
        print(f"\n ALREADY BROKEN — {len(u)} unknown node(s) in this file:")
        for h in u:
            print(f"   x  '{h['name']}'")
            print(f"        at {h['location']}")

    if pm:
        # group by suggested action so the user sees the shape at a glance
        by_action = {}
        for h in pm:
            by_action.setdefault(h["action"], []).append(h)
        print(f"\n WILL BREAK IN TARGET — {len(pm)} node(s) with no target equivalent:")
        for action in sorted(by_action):
            print(f"\n   [{action}]")
            for h in by_action[action]:
                print(f"     - {h['type']}  ('{h['name']}')")
                print(f"         at {h['location']}")
                print(f"         {h['note']}")

    if pc:
        print(f"\n MAY SHIFT — {len(pc)} node(s) whose sockets changed:")
        for h in pc:
            print(f"   ~  {h['type']}  ('{h['name']}')  at {h['location']}")
            for k, v in h["delta"].items():
                print(f"        {k}: {v}")

    if settings_hits:
        print(f"\n SETTINGS LOST — {len(settings_hits)} non-default setting(s) "
              f"with no target equivalent (revert to default):")
        for h in settings_hits:
            print(f"   -  {h['setting']} = {h['value']}")
            print(f"        at {h['location']}")

    for w in (db or {}).get("non_node_warnings", []):
        print(f"\n [!] non-node warning ({w['severity']}): {w['id']}")
        print(f"     {w['detail']}")

    total = len(u) + len(pm) + len(pc) + len(settings_hits)
    print("\n" + line)
    print(f" SUMMARY: {len(u)} already-broken, {len(pm)} will-break, "
          f"{len(pc)} may-shift, {len(settings_hits)} settings-lost  (total {total})")
    print(line + "\n")

    if opts["json"]:
        payload = {"running": running, "source": src, "target": tgt, "hits": hits,
                   "settings_lost": settings_hits,
                   "non_node_warnings": (db or {}).get("non_node_warnings", [])}
        json.dump(payload, open(opts["json"], "w"), indent=2)
        print(f"[json report written to {opts['json']}]")

    return total


def main():
    opts = parse_args()
    db = load_db(opts["db"])
    if db is None:
        print("[info] no compat DB loaded - running in DETECT-only mode "
              "(finds already-broken nodes; cannot predict).")
    nodes = collect_nodes()
    hits = analyse(nodes, db)
    settings_hits = check_settings(db)
    report(hits, settings_hits, db, opts)


if __name__ == "__main__":
    main()
