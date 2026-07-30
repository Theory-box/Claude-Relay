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

    _refcache={}
    def ref_default(bl, sname):
        if bl not in _refcache:
            _refcache[bl]={}
            try:
                tt='ShaderNodeTree' if bl.startswith('ShaderNode') else ('CompositorNodeTree' if bl.startswith('CompositorNode') else 'GeometryNodeTree')
                sc_=bpy.data.node_groups.new("_relayref", tt)
                rn=sc_.nodes.new(bl)
                for inp in rn.inputs:
                    try:
                        dv=inp.default_value
                        _refcache[bl][inp.name]=tuple(dv) if hasattr(dv,"__len__") else dv
                    except Exception: pass
                bpy.data.node_groups.remove(sc_)
            except Exception: pass
        return _refcache[bl].get(sname)

    issues = []
    def add(id, sev, typ, loc, action, desc, risk, how, sock="--sock-val"):
        it={"id":id,"sev":sev,"type":typ,"loc":loc,"action":action,
            "desc":desc,"risk":risk,"how":how,"sock":sock}
        if id.startswith("image::"): it["fixLabel"]="Pack"; it["optional"]=True
        issues.append(it)

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
            else:
                # only flag an added-socket change when the socket is actually USED
                # (linked or non-default) — otherwise dropping it in 4.2 changes nothing.
                real=[]
                for entry in delta.get("in_added",[]):
                    sname=entry[0]; sk=n.inputs.get(sname)
                    if sk is None: continue
                    if sk.is_linked: real.append((sname,"linked")); continue
                    try: v=sk.default_value
                    except Exception: continue
                    ref=ref_default(bl,sname)
                    cur=tuple(v) if hasattr(v,"__len__") else v
                    def _diff(a,b):
                        if a is None: return False
                        if isinstance(a,tuple): return any(abs(x-y)>1e-5 for x,y in zip(a,b))
                        return abs(a-b)>1e-5 if isinstance(a,(int,float)) else a!=b
                    if _diff(ref,cur):
                        real.append((sname, round(v,3) if isinstance(v,(int,float)) else tuple(round(x,3) for x in v)))
                if real:
                    sname,val=real[0]
                    add(iid,"shift",bl,where,"acknowledge",f"The 4.4 '{sname}' input doesn't exist in 4.2, so its value reverts to the 4.2 default.",f"{sname} = {val}","Reverts to 4.2 default (minor look change).",sock)

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

    # images: unpacked textures + generated blocks won't travel with the file
    for img in bpy.data.images:
        if img.type in ("RENDER_RESULT","COMPOSITING") or img.name in ("Render Result","Viewer Node"):
            continue
        if img.packed_file is not None:
            continue
        if img.source=="FILE" and img.filepath:
            add(f"image::{img.name}", "shift", "Image \u00b7 "+img.name, "external texture", "fix",
                "This texture is linked from disk and isn't packed \u2014 the client won't see it unless you also send the file.",
                f"path: {img.filepath}", "Pack the texture into the .blend.", "--sock-col")
        elif img.source=="GENERATED":
            add(f"imagegen::{img.name}", "shift", "Image \u00b7 "+img.name, "generated image", "manual",
                "Generated inside Blender with no file backing. It can't be packed and its pixels aren't saved in the .blend \u2014 procedural ones regenerate fine, but if an add-on painted or computed this, save it to a file in Blender before sending.",
                f"{img.size[0]}x{img.size[1]}", "Save the image to a file in Blender (it can't be auto-packed).", "--sock-col")
    # settings
    for h in sc.check_settings(db):
        add("setting::"+h["setting"],"shift","Scene · "+h["setting"].split(".")[0],h["location"],"acknowledge",
            "This setting has no equivalent in the target and reverts to default.",f"{h['setting'].split('.')[-1]} = {h['value']}","Reverts on open.","--sock-val")
    # non-node warnings — only when the file ACTUALLY contains the at-risk data
    gp=[o for o in bpy.data.objects if o.type in ("GPENCIL","GREASEPENCIL")]
    if not gp:
        for attr in ("grease_pencils_v3","grease_pencils"):
            gp=gp or list(getattr(bpy.data, attr, []))
    if gp:
        add("nonnode::grease_pencil_v3","break","Grease Pencil v3","whole file","manual",
            "This file has Grease Pencil data in the 4.3+ format, which won't open correctly in 4.2.",
            f"{len(gp)} object(s)/datablock(s)","Handle Grease Pencil before downgrading.","--sock-geo")
    multi=[a for a in bpy.data.actions if len(getattr(a,"slots",[]))>1]
    if multi:
        add("nonnode::slotted_actions","shift","Slotted Actions","whole file","manual",
            "Some actions use 4.4 multi-slot layered actions (one action driving several objects), which 4.2 can't represent \u2014 extra slots may be lost. (Single-slot actions convert fine.)",
            f"{len(multi)} multi-slot action(s)","Split or bake these actions before downgrading.","--sock-geo")

    # manual issues living inside a GN modifier can be resolved by applying it
    for it in issues:
        if it["action"]=="manual":
            m=re.match(r"Object '([^']+)' > GN modifier '([^']+)'", it["loc"])
            if m:
                it["obj"], it["mod"], it["can_apply"] = m.group(1), m.group(2), True
    out = arg("--out")
    payload = {"source": bpy.app.version_string, "file": bpy.data.filepath, "issues": issues}
    if out: json.dump(payload, open(out,"w"), indent=1)
    print("SCAN_OK "+str(len(issues))+" issues")

main()
