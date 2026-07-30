#!/usr/bin/env python3
"""engine.py — orchestrates Blender for Relay. No bpy here; launches short-lived
headless Blender subprocesses and cleans up after itself."""
import subprocess, json, tempfile, os, gzip, glob, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
DB = next((os.path.join(APP,f) for f in sorted(os.listdir(APP))
           if f.startswith("compat_db_") and f.endswith(".json")), None)

# ---- source version straight from the .blend header ----
def detect_version(path):
    with open(path,"rb") as f: head=f.read(32)
    if head[:2]==b"\x1f\x8b":
        with gzip.open(path,"rb") as f: head=f.read(32)
    elif head[:4]==b"\x28\xb5\x2f\xfd":
        try:
            import zstandard as zstd
            with open(path,"rb") as f: head=zstd.ZstdDecompressor().stream_reader(f).read(32)
        except Exception: return None
    if head[:7]!=b"BLENDER": return None
    v=head[9:12].decode("ascii","ignore")
    try: return f"{int(v[0])}.{int(v[1:])}"
    except Exception: return None

# ---- find available Blender builds (dev config + real install scan) ----
def find_blenders():
    found={}
    cfg=os.path.join(HERE,"blenders.json")           # dev / app-managed override
    if os.path.exists(cfg): found.update(json.load(open(cfg)))
    pats=["/Applications/Blender*.app/Contents/MacOS/Blender",
          "/usr/bin/blender","/opt/blender*/blender",
          os.path.expanduser("~/blender*/blender"),
          "C:\\Program Files\\Blender Foundation\\Blender*\\blender.exe"]
    for p in pats:
        for hit in glob.glob(p):
            found.setdefault("installed:"+os.path.basename(os.path.dirname(hit)), hit)
    return found

def _run(blender, blendfile, script, extra):
    r=subprocess.run([blender,"-b",blendfile,"--python",os.path.join(HERE,script),"--"]+extra,
                     capture_output=True, text=True, timeout=600)
    return r

# ---- scan: returns UI-format issues ----
def scan(path, src_blender):
    out=tempfile.mktemp(suffix=".json")
    try:
        r=_run(src_blender, path, "scan_ui.py", ["--db",DB,"--out",out])
        if "SCAN_OK" not in r.stdout: raise RuntimeError(r.stderr[-600:] or "scan failed")
        data=json.load(open(out))
        data["blenders"]=find_blenders()
        return data
    finally:
        if os.path.exists(out): os.unlink(out)

# ---- convert: two staged passes, then clean up everything but the final file ----
def convert(path, selected_ids, src_blender, tgt_blender, out_path):
    work=tempfile.mkdtemp(prefix="relay_")
    sel=os.path.join(work,"sel.json"); man=os.path.join(work,"m.json")
    inter=os.path.join(work,"inter.blend")
    json.dump(selected_ids, open(sel,"w"))
    try:
        r1=_run(src_blender, path, "convert_source.py",
                ["--select",sel,"--db",DB,"--manifest",man,"--out",inter])
        if "SRC_OK" not in r1.stdout: raise RuntimeError(r1.stderr[-600:] or "source stage failed")
        r2=_run(tgt_blender, inter, "convert_target.py",
                ["--select",sel,"--db",DB,"--manifest",man,"--out",out_path])
        if "TGT_OK" not in r2.stdout: raise RuntimeError(r2.stderr[-600:] or "target stage failed")
        s=int(r1.stdout.split("fixed=")[1].split()[0]); k=int(r1.stdout.split("keep_recorded=")[1].split()[0])
        return {"out":out_path,"source_fixed":s,"rebuilt":int(r2.stdout.split("rebuilt=")[1].split()[0]),"kept":k}
    finally:
        shutil.rmtree(work, ignore_errors=True)          # no leftovers
