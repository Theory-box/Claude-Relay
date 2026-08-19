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
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0  # no console popups on Windows

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
    return ".".join(v.replace("LTS", "").strip().split(".")[:2]) if v else ""

def _blender_for(version):
    """Resolve a Blender exe. Prefer the exact selected version key, then a matching
    major.minor, then ANY discovered Blender. Never auto-downloads (that would hang the
    UI); if nothing is installed, raise a clear error instead."""
    found = blender_manage.discover(CFG)
    if version and version in found:
        return found[version]                       # exact key the user picked
    if version:
        mm = _mm(version)
        for v, exe in found.items():
            if v.startswith(mm):
                return exe                          # same major.minor
    if found:
        return next(iter(found.values()))           # any Blender we can see
    raise RuntimeError(
        "No Blender was found on this machine. Install Blender, or make sure it's in a "
        "standard location (Program Files / Applications).")

def _run(blender, blendfile, script_src, extra, background=True):
    """Write script_src to a temp .py and run it inside Blender. blendfile=None starts
    from the default/empty file (used by the fast build-in-fresh-file merge path)."""
    sf = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False)
    sf.write(script_src); sf.close()
    args = [blender]
    if background:
        args.append("-b")
    # clean, deterministic headless run: factory prefs + NO user addons (their load/save
    # handlers must not touch the file), no audio device. --enable-autoexec keeps legit
    # drivers evaluating (factory-startup defaults auto-run OFF, which would freeze driven
    # transforms and shift geometry).
    args += ["--factory-startup", "--enable-autoexec", "-noaudio"]
    if blendfile:
        args.append(blendfile)
    args += ["--python", sf.name, "--"] + extra
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=7200,
                              creationflags=(_NO_WINDOW if background else 0))
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
    hdr = detect_version(path)
    if not hdr:
        raise RuntimeError("This doesn't look like a .blend file (no version header).")
    blender = _blender_for(version or hdr)   # prefer the Blender the user selected
    out = tempfile.mktemp(suffix=".json")
    try:
        r = _run(blender, path, DUMP_SRC, ["--out", out])
        # Verify by the OUTPUT FILE, not stdout: Windows GUI blender.exe stdout is
        # unreliable when its console is hidden, but the file it writes is not.
        if not (os.path.exists(out) and os.path.getsize(out) > 0):
            msg = (r.stderr or r.stdout or "").strip()[-800:]
            raise RuntimeError("Blender couldn't read this file. "
                               "Make sure the selected Blender is the same version as the "
                               "file or newer (an older Blender can't open a newer file).\n" + msg)
        data = json.load(open(out))
        data["detected"] = hdr
        return data
    finally:
        if os.path.exists(out):
            os.unlink(out)

# ---------------------------------------------------------------- execute plan
# The result is built in a FRESH file, appending only what each merge group needs and
# joining it while the scene is still small. Operators like join()/make_single_user
# scale with total scene size, so this is ~50x faster than merging inside a huge file.
# plan.json: {"merges":[{"label":..,"names":[objname,...]}, ...],
#             "deletes":[{"label":..,"names":[...]}, ...]}
MERGE_SRC = r'''
import bpy, sys, os, json, time
def arg(n,d=None):
    a=sys.argv; a=a[a.index("--")+1:] if "--" in a else []
    return a[a.index(n)+1] if n in a and a.index(n)+1<len(a) else d
SRC=arg("--source"); plan=json.load(open(arg("--plan"))); out=arg("--out")
include_untouched = arg("--untouched","1")=="1"
tag_materials = arg("--materials","0")=="1"
BATCH=int(arg("--batch","2000"))
t0=time.time()

bpy.ops.wm.read_factory_settings(use_empty=True)
scene=bpy.context.scene

def obj(n): return bpy.data.objects.get(n)

def append(names):
    """Append the given object names from the source file into the current (empty-ish)
    scene. Returns the linked objects."""
    names=set(names)
    with bpy.data.libraries.load(SRC) as (src, dst):
        dst.objects=[n for n in src.objects if n in names]
    got=[o for o in dst.objects if o is not None]
    for o in got:
        scene.collection.objects.link(o)
    return got

def join_batch(objs, target_name):
    objs=[o for o in objs if o and o.type=="MESH"]
    if not objs: return None
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs: o.select_set(True)
    bpy.context.view_layer.objects.active=objs[0]
    bpy.ops.object.make_single_user(object=True, obdata=True)  # collapse instances
    if tag_materials:
        # per-object backup material named after the object, so the merge can be
        # reversed later with Separate > By Material. Only add when the object has
        # none of its own (don't clobber real materials).
        for o in objs:
            if o.type=="MESH" and len(o.data.materials)==0:
                m=bpy.data.materials.new(o.name)
                o.data.materials.append(m)
    if len(objs)>1:
        bpy.ops.object.join()
    r=bpy.context.view_layer.objects.active
    r.name=target_name
    return r

merged_groups=0; merged_objs=0
# merged results go into an EXCLUDED collection so the working view layer stays tiny —
# join/make_single_user overhead scales with view-layer size, so we keep it small.
_res=bpy.data.collections.new("__merged__"); scene.collection.children.link(_res)
def _set_excl(v):
    for _lc in bpy.context.view_layer.layer_collection.children:
        if _lc.collection==_res: _lc.exclude=v
_set_excl(True)
def stash(o):
    if not o: return
    for c in list(o.users_collection): c.objects.unlink(o)
    _res.objects.link(o)
# ---- merges: CHUNK groups so the huge source is opened ONCE per chunk, not per group ----
# (opening a 500MB+ .blend costs ~2s each; per-group opens dominate big plans.)
CHUNK=int(arg("--chunk","3000"))     # max objects appended per source open
_mg=[g for g in plan.get("merges", []) if g.get("names")]
_gi=0
while _gi < len(_mg):
    chunk=[]; total=0
    while _gi < len(_mg) and (not chunk or total+len(_mg[_gi]["names"])<=CHUNK):
        chunk.append(_mg[_gi]); total+=len(_mg[_gi]["names"]); _gi+=1
    if not chunk:                      # a single group larger than CHUNK -> its own chunk
        chunk=[_mg[_gi]]; _gi+=1
    allnames=set(n for g in chunk for n in g["names"])
    pool=append(allnames)              # ONE library open for the whole chunk
    byname={o.name:o for o in pool}
    for g in chunk:
        objs=[byname[n] for n in g["names"] if n in byname]
        if not objs: continue
        target=g.get("label","merged")
        if len(objs)>BATCH:
            partials=[]
            for i in range(0,len(objs),BATCH):
                r=join_batch(objs[i:i+BATCH], target+"__p"+str(i//BATCH))
                if r: partials.append(r)
            res=join_batch(partials, target) if partials else None
        else:
            res=join_batch(objs, target)
        stash(res)
        merged_groups+=1; merged_objs+=len(objs)
merge_t=time.time()-t0
# bring merged results back into the main collection for a clean single-collection output
_set_excl(False)
for o in list(_res.objects):
    _res.objects.unlink(o); scene.collection.objects.link(o)
bpy.data.collections.remove(_res)

# ---- output ----
deleted_names=set(n for g in plan.get("deletes",[]) for n in g["names"])
merged_names =set(n for g in plan.get("merges",[])  for n in g["names"])
appended_untouched=0
if include_untouched:
    # FULL MODEL. Re-appending ~all 52k objects one at a time is brutally slow (minutes),
    # so instead: save the freshly-built merged results, load the ORIGINAL file (which
    # already contains every object), BATCH-REMOVE the objects we merged or deleted, then
    # drop the merged results back in. batch_remove of tens of thousands is ~seconds.
    import tempfile as _tf
    _tmp=_tf.mktemp(suffix=".blend")
    bpy.ops.wm.save_as_mainfile(filepath=_tmp)               # merged results only, to temp
    result_names=set(o.name for o in bpy.data.objects)
    bpy.ops.wm.open_mainfile(filepath=SRC)                   # load the full original
    _touched=merged_names|deleted_names
    _rm=[o for o in bpy.data.objects if o.name in _touched]
    bpy.data.batch_remove(_rm)                               # drop merged+deleted originals
    appended_untouched=len([o for o in bpy.data.objects if o.type=="MESH"])
    _sc=bpy.context.scene
    with bpy.data.libraries.load(_tmp) as (src, dst):
        dst.objects=[n for n in src.objects if n in result_names]
    for o in dst.objects:
        if o: _sc.collection.objects.link(o)
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
    try: os.unlink(_tmp)
    except Exception: pass
else:
    bpy.ops.wm.save_as_mainfile(filepath=os.path.abspath(out))
_stats = {"merged_groups": merged_groups, "merged_objs": merged_objs,
          "deleted": len(deleted_names), "untouched": appended_untouched,
          "remaining": len([o for o in bpy.data.objects if o.type=="MESH"]),
          "merge_time": round(merge_t,1), "total_time": round(time.time()-t0,1),
          "out": os.path.abspath(out)}
sp = arg("--stats")
if sp:
    json.dump(_stats, open(sp, "w"))
print("MERGE_OK " + json.dumps(_stats))
'''

def execute_plan(path, plan, version=None, out_path=None, overwrite=False,
                 open_after=False, include_untouched=True, tag_materials=True):
    ver = version or detect_version(path)
    blender = _blender_for(ver)
    if not out_path:
        base, ext = os.path.splitext(path)
        out_path = path if overwrite else base + "_merged.blend"
    # never write straight over the source while reading from it; use a temp then move
    write_to = out_path
    if os.path.abspath(out_path) == os.path.abspath(path):
        write_to = tempfile.mktemp(suffix=".blend")
    plan_file = tempfile.mktemp(suffix=".json")
    stats_file = tempfile.mktemp(suffix=".json")
    json.dump(plan, open(plan_file, "w"))
    try:
        r = _run(blender, None, MERGE_SRC,
                 ["--source", os.path.abspath(path), "--plan", plan_file,
                  "--out", write_to, "--stats", stats_file,
                  "--untouched", "1" if include_untouched else "0",
                  "--materials", "1" if tag_materials else "0"])
        # Verify by the STATS FILE (and the produced .blend), not stdout.
        if not os.path.exists(stats_file):
            if os.path.exists(write_to) and os.path.getsize(write_to) > 0:
                stats = {"out": write_to, "note": "completed"}
            else:
                msg = (r.stderr or r.stdout or "").strip()[-1200:]
                raise RuntimeError("Merge did not complete.\n" + msg)
        else:
            stats = json.load(open(stats_file))
        if write_to != out_path:                       # overwrite path: move temp over original
            import shutil
            shutil.move(write_to, out_path)
        stats["out"] = out_path
        if open_after:
            subprocess.Popen([blender, out_path])       # GUI open for inspection (shows a window)
        return stats
    finally:
        for f in (plan_file, stats_file):
            if os.path.exists(f):
                os.unlink(f)

if __name__ == "__main__":
    # tiny CLI for headless testing:  engine.py extract file.blend  |  engine.py plan file.blend plan.json
    import json as _j
    cmd = sys.argv[1]
    if cmd == "extract":
        print(_j.dumps(extract_names(sys.argv[2])["objects"][:3], indent=2))
    elif cmd == "version":
        print(detect_version(sys.argv[2]))
