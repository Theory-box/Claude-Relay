#!/usr/bin/env python3
"""engine.py — orchestrates Blender for Relay. No bpy here. Launches short-lived
headless Blender subprocesses (which exit on their own) and cleans up temp files.
Version-driven: resolves/downloads the Blender builds it needs."""
import subprocess, json, tempfile, os, sys, gzip, shutil
import blender_manage

HERE = os.path.dirname(os.path.abspath(__file__))
# bundle-aware: when frozen by PyInstaller, data ships under _MEIPASS
if getattr(sys, "frozen", False):
    APP = os.path.join(sys._MEIPASS, "blend-compat-scanner")
    HERE = os.path.join(APP, "backend")
else:
    APP = os.path.dirname(HERE)
DB = next((os.path.join(APP, f) for f in sorted(os.listdir(APP))
           if f.startswith("compat_db_") and f.endswith(".json")), None)
CFG = os.path.join(HERE, "blenders.json")   # dev override (ignored if absent)

def _mm(v):  # "4.2.23 LTS" -> "4.2"
    parts = v.replace("LTS", "").strip().split(".")
    return ".".join(parts[:2])

def detect_version(path):
    with open(path, "rb") as f: head = f.read(32)
    if head[:2] == b"\x1f\x8b":
        with gzip.open(path, "rb") as f: head = f.read(32)
    elif head[:4] == b"\x28\xb5\x2f\xfd":
        try:
            import zstandard as zstd
            with open(path, "rb") as f: head = zstd.ZstdDecompressor().stream_reader(f).read(32)
        except Exception: return None
    if head[:7] != b"BLENDER": return None
    v = head[9:12].decode("ascii", "ignore")
    try: return f"{int(v[0])}.{int(v[1:])}"
    except Exception: return None

def blenders():
    return blender_manage.discover(CFG)

def _blender_for(version):     # ensure a build for this version; download if missing
    return blender_manage.ensure(_mm(version), CFG)

def _run(blender, blendfile, script, extra):
    return subprocess.run([blender, "-b", blendfile, "--python", os.path.join(HERE, script), "--"] + extra,
                          capture_output=True, text=True, timeout=900)

def scan(path):
    ver = detect_version(path)
    if not ver: raise RuntimeError("not a .blend file (no version header)")
    src = _blender_for(ver)
    out = tempfile.mktemp(suffix=".json")
    try:
        r = _run(src, path, "scan_ui.py", ["--db", DB, "--out", out])
        if "SCAN_OK" not in r.stdout: raise RuntimeError(r.stderr[-600:] or "scan failed")
        data = json.load(open(out))
        data["detected"] = ver
        data["blenders"] = blenders()
        return data
    finally:
        if os.path.exists(out): os.unlink(out)

def convert(path, selected_ids, source_version, target_version, out_path, apply_modifiers=None):
    src = _blender_for(source_version)
    tgt = _blender_for(target_version)     # auto-downloads target build if missing
    work = tempfile.mkdtemp(prefix="relay_")
    src_copy = os.path.join(work, "source.blend")
    shutil.copy2(path, src_copy)                 # ORIGINAL is only ever READ, never opened for writing
    sel = os.path.join(work, "sel.json"); man = os.path.join(work, "m.json")
    apl = os.path.join(work, "apply.json"); inter = os.path.join(work, "inter.blend")
    json.dump(selected_ids, open(sel, "w"))
    json.dump(apply_modifiers or [], open(apl, "w"))
    try:
        r1 = _run(src, src_copy, "convert_source.py", ["--select", sel, "--apply", apl, "--db", DB, "--manifest", man, "--out", inter])
        if "SRC_OK" not in r1.stdout: raise RuntimeError(r1.stderr[-600:] or "source stage failed")
        r2 = _run(tgt, inter, "convert_target.py", ["--select", sel, "--db", DB, "--manifest", man, "--out", out_path])
        if "TGT_OK" not in r2.stdout: raise RuntimeError(r2.stderr[-600:] or "target stage failed")
        return {"out": out_path,
                "source_fixed": int(r1.stdout.split("fixed=")[1].split()[0]),
                "kept": int(r1.stdout.split("keep_recorded=")[1].split()[0]),
                "applied": int(r1.stdout.split("applied=")[1].split()[0]),
                "rebuilt": int(r2.stdout.split("rebuilt=")[1].split()[0])}
    finally:
        shutil.rmtree(work, ignore_errors=True)
