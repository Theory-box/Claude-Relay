#!/usr/bin/env python3
"""engine.py — orchestrates headless Blender for the merge analyzer. No bpy here.

Reads the .blend version straight from the header (no Blender needed), resolves a
matching Blender via blender_manage, and runs short-lived headless subprocesses for
name extraction and for executing a merge/delete plan. The scripts that must run
INSIDE Blender are embedded below as strings and written to a temp file at runtime,
so the app ships without loose Blender-script files.
"""
import subprocess, json, tempfile, os, sys, gzip

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import blender_manage

CFG = os.path.join(HERE, "blenders.json")   # optional dev override

# ---------------------------------------------------------------- version header
def detect_version(path):
    with open(path, "rb") as f:
        head = f.read(32)
    if head[:2] == b"\x1f\x8b":
        with gzip.open(path, "rb") as f:
            head = f.read(32)
    elif head[:4] == b"\x28\xb5\x2f\xfd":
        try:
            import zstandard as zstd
            with open(path, "rb") as f:
                head = zstd.ZstdDecompressor().stream_reader(f).read(32)
        except Exception:
            return None
    if head[:7] != b"BLENDER":
        return None
    v = head[9:12].decode("ascii", "ignore")
    try:
        return f"{int(v[0])}.{int(v[1:])}"
    except Exception:
        return None

def blenders():
    return blender_manage.discover(CFG)

def _mm(v):
    return ".".join(v.replace("LTS", "").strip().split(".")[:2])

def _blender_for(version):
    return blender_manage.ensure(_mm(version), CFG)

def _run(blender, blendfile, script_src, extra, background=True):
    """Write script_src to a temp .py and run it inside Blender."""
    sf = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    sf.write(script_src); sf.close()
    args = [blender]
    if background:
        args.append("-b")
    args += [blendfile, "--python", sf.name, "--"] + extra
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=3600)
    finally:
        os.unlink(sf.name)

# ---------------------------------------------------------------- name extraction
DUMP_SRC = r'''
import bpy, sys, os, json
def arg(n,d=None):
    a=sys.argv; a=a[a.index("--")+1:] if "--" in a else []
    return a[a.index(n)+1] if n in a and a.index(n)+1<len(a) else d
out=arg("--out")
mesh_cache={}
def stats(data):
    if data is None: return ("","")
    k=data.as_pointer()
    if k not in mesh_cache:
        mesh_cache[k]=(len(data.vertices) if hasattr(data,"vertices") else "",
                       len(data.polygons) if hasattr(data,"polygons") else "")
    return mesh_cache[k]
objs=[]
for o in bpy.data.objects:
    if o.type!="MESH": continue
    v,p=stats(o.data)
    objs.append({"name":o.name,"data_name":o.data.name if o.data else "",
                 "data_users":o.data.users if o.data else 1,"verts":v,"polys":p})
json.dump({"objects":objs},open(out,"w"))
print("DUMP_OK count=%d" % len(objs))
'''

def extract_names(path, version=None):
    ver = version or detect_version(path)
    if not ver:
        raise RuntimeError("not a .blend file (no version header)")
    blender = _blender_for(ver)
    out = tempfile.mktemp(suffix=".json")
    try:
        r = _run(blender, path, DUMP_SRC, ["--out", out])
        if "DUMP_OK" not in r.stdout:
            raise RuntimeError(r.stderr[-800:] or "extraction failed")
        data = json.load(open(out))
        data["detected"] = ver
        return data
    finally:
        if os.path.exists(out):
            os.unlink(out)

# ---------------------------------------------------------------- execute plan
# plan.json: {"merges":[{"label":..,"names":[objname,...]}, ...],
#             "deletes":[{"label":..,"names":[...]}, ...]}
MERGE_SRC = r'''
import bpy, sys, os, json
def arg(n,d=None):
    a=sys.argv; a=a[a.index("--")+1:] if "--" in a else []
    return a[a.index(n)+1] if n in a and a.index(n)+1<len(a) else d
plan=json.load(open(arg("--plan"))); out=arg("--out")
overwrite=arg("--overwrite","0")=="1"
BATCH=int(arg("--batch","5000"))

def obj(name): return bpy.data.objects.get(name)

merged_objs=0; merged_groups=0; deleted=0; errors=[]

# ---- deletes first (removes objects entirely) ----
for grp in plan.get("deletes",[]):
    for nm in grp["names"]:
        o=obj(nm)
        if o:
            bpy.data.objects.remove(o, do_unlink=True); deleted+=1

# ---- merges: make-single-user then join, in batches ----
def join_batch(names, target_name):
    objs=[obj(n) for n in names]; objs=[o for o in objs if o and o.type=="MESH"]
    if len(objs)<1: return None
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        o.select_set(True)
    bpy.context.view_layer.objects.active=objs[0]
    # break instancing so joined geometry is real & independent
    bpy.ops.object.make_single_user(object=True, obdata=True)
    if len(objs)>1:
        bpy.ops.object.join()
    result=bpy.context.view_layer.objects.active
    result.name=target_name
    return result

for grp in plan.get("merges",[]):
    names=[n for n in grp["names"] if obj(n)]
    if not names: continue
    target=grp.get("label","merged")
    # batch large groups to stay well within operator limits
    if len(names)>BATCH:
        partials=[]
        for i in range(0,len(names),BATCH):
            r=join_batch(names[i:i+BATCH], f"{target}__part{i//BATCH}")
            if r: partials.append(r.name)
        # final join of the partials
        if partials:
            res=join_batch(partials, target)
    else:
        res=join_batch(names, target)
    merged_groups+=1
    merged_objs+=len(names)

# save
target_path = os.path.abspath(out)
bpy.ops.wm.save_as_mainfile(filepath=target_path)
print("MERGE_OK merged_groups=%d merged_objs=%d deleted=%d remaining=%d out=%s" % (
    merged_groups, merged_objs, deleted,
    len([o for o in bpy.data.objects if o.type=="MESH"]), target_path))
'''

def execute_plan(path, plan, version=None, out_path=None, overwrite=False,
                 open_after=False):
    ver = version or detect_version(path)
    blender = _blender_for(ver)
    if not out_path:
        base, ext = os.path.splitext(path)
        out_path = path if overwrite else base + "_merged.blend"
    plan_file = tempfile.mktemp(suffix=".json")
    json.dump(plan, open(plan_file, "w"))
    try:
        # always operate on the original as READ-only; Blender loads it and saves to out
        r = _run(blender, path, MERGE_SRC,
                 ["--plan", plan_file, "--out", out_path,
                  "--overwrite", "1" if overwrite else "0"])
        if "MERGE_OK" not in r.stdout:
            raise RuntimeError(r.stderr[-1000:] or "merge failed")
        line = [l for l in r.stdout.splitlines() if l.startswith("MERGE_OK")][0]
        stats = dict(kv.split("=") for kv in line.split()[1:] if "=" in kv)
        if open_after:
            # fire-and-forget GUI open of the result for inspection
            subprocess.Popen([blender, out_path])
        return {"out": out_path, **stats}
    finally:
        if os.path.exists(plan_file):
            os.unlink(plan_file)

if __name__ == "__main__":
    # tiny CLI for headless testing:  engine.py extract file.blend  |  engine.py plan file.blend plan.json
    import json as _j
    cmd = sys.argv[1]
    if cmd == "extract":
        print(_j.dumps(extract_names(sys.argv[2])["objects"][:3], indent=2))
    elif cmd == "version":
        print(detect_version(sys.argv[2]))
