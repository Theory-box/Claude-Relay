#!/usr/bin/env python3
"""scan_ui.py — run inside the SOURCE Blender. Emits the issue list in the exact
shape the Relay UI consumes, reusing the tested scanner traversal + fixer registry.
  blender-4.4 -b file.blend --python scan_ui.py -- --db compat.json --out issues.json
"""
import bpy, sys, os, json, re

def arg(name, default=None):
    a = sys.argv; a = a[a.index("--")+1:] if "--" in a else []
    return a[a.index(name)+1] if name in a and a.index(name)+1 < len(a) else default

APP = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP)
sys.path.insert(0, os.path.join(APP, "repair"))
import blend_compat_scanner as sc
import fixers

def sock_hint(t):
    return {"GEOMETRY":"--sock-geo","VALUE":"--sock-val","INT":"--sock-val",
            "RGBA":"--sock-col","VECTOR":"--sock-vec"}.get(t, "--sock-val")

def main():
    db = json.load(open(arg("--db")))
    missing, changed = db.get("missing",{}), db.get("changed",{})
    prop_changed = db.get("prop_changed",{})
    new_sockets = set(db.get("socket_types_new",[]))
    auto = set(fixers.FIXERS.keys())
    keep = set(fixers.NEEDS_TWO_STAGE)
    safe_drop = set(fixers.SAFE_DROP)

    issues = []
    def add(id, sev, typ, loc, action, desc, risk, how, sock="--sock-val"):
        issues.append({"id":id,"sev":sev,"type":typ,"loc":loc,"action":action,
                       "desc":desc,"risk":risk,"how":how,"sock":sock})

    for n, where in sc.collect_nodes():
        bl = n.bl_idname
        vals = dict(sc.node_values(n))
        risk = next((f"{k} = {v}" for k,v in vals.items()), "—")
        sock = sock_hint(n.outputs[0].type) if n.outputs else "--sock-val"
        iid = f"{where}::{n.name}"

        if bl in missing:
            info = missing[bl]
            if bl in safe_drop:
                add(iid,"safe",bl,where,"fix","Missing in the target, but has no effect on the evaluated result.","cosmetic","Removed; passthrough reconnected.",sock)
            elif bl in auto:
                add(iid,"break",bl,where,"fix","This node doesn't exist in the target and becomes an Undefined node.",risk,"Reconstructed from equivalent target nodes (verified).",sock)
            else:
                g = "No safe automatic reconstruction."
                if getattr(n,"object",None): g=f"References object '{n.object.name}' — recreate as an Object group input."
                elif getattr(n,"collection",None): g=f"References collection '{n.collection.name}'."
                elif n.inputs.get("Path") and not n.inputs["Path"].is_linked: g=f"Imports '{n.inputs['Path'].default_value}' — re-import in the target."
                add(iid,"break",bl,where,"manual","Missing in the target and can't be safely reconstructed.",risk,g,sock)

        elif bl in changed:
            delta = changed[bl].get("delta",{})
            lost = [e for e in delta.get("in_subtype_changed",[]) if e[2] in new_sockets]
            if lost and bl in keep:
                sname = lost[0][0]
                rv = vals.get(sname, "—")
                add(iid,"break",bl,where,"fix",f"The {sname} socket uses a subtype the target lacks, so its value is dropped.",f"{sname} = {rv}","Rebuilt as a native target node with the same value (node kept).",sock)
            elif delta:
                add(iid,"shift",bl,where,"acknowledge","Exists in both versions but a socket changed; the added value reverts to the target default.",risk,"Reverts to target behaviour (minor).",sock)

        elif bl in prop_changed:
            pinfo = prop_changed[bl]
            hit=None
            for p in pinfo.get("added",[]):
                if hasattr(n,p):
                    try:
                        if getattr(n,p)!=n.bl_rna.properties[p].default: hit=(p,getattr(n,p))
                    except Exception: pass
            for p,vals2 in pinfo.get("enum_values_added",{}).items():
                if hasattr(n,p) and getattr(n,p) in vals2: hit=(p,getattr(n,p))
            if hit:
                add(iid,"shift",bl,where,"acknowledge",f"Uses a 4.x-only property/value ('{hit[0]}') the target can't represent.",f"{hit[0]} = {hit[1]}","Reverts to target default.",sock)

    # settings
    for h in sc.check_settings(db):
        add("setting::"+h["setting"],"shift","Scene · "+h["setting"].split(".")[0],h["location"],"acknowledge",
            "This setting has no equivalent in the target and reverts to default.",f"{h['setting'].split('.')[-1]} = {h['value']}","Reverts on open.","--sock-val")
    # non-node
    for w in db.get("non_node_warnings",[]):
        add("nonnode::"+w["id"], "break" if w["severity"]=="critical" else "shift", w["id"].replace("_"," ").title(),
            "whole file","manual",w["detail"],"non-node · "+w["severity"],"Handle before downgrading.","--sock-geo")

    # manual issues living inside a GN modifier can be resolved by applying it
    for it in issues:
        if it["action"]=="manual":
            m=re.match(r"Object '(.+)' > GN modifier '(.+)'", it["loc"])
            if m:
                it["obj"], it["mod"], it["can_apply"] = m.group(1), m.group(2), True
    out = arg("--out")
    payload = {"source": bpy.app.version_string, "file": bpy.data.filepath, "issues": issues}
    if out: json.dump(payload, open(out,"w"), indent=1)
    print("SCAN_OK "+str(len(issues))+" issues")

main()
