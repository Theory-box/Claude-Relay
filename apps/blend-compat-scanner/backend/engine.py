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
sys.path.insert(0, os.path.join(APP, "tools"))

def _mm(v):  # "4.2.23 LTS" -> "4.2"
    parts = v.replace("LTS", "").strip().split(".")
    return ".".join(parts[:2])

def _dbs_dir():
    import blender_manage
    d = os.path.join(os.path.dirname(blender_manage.relay_home()), "dbs")
    os.makedirs(d, exist_ok=True)
    return d

def get_db(source_version, target_version):
    """Resolve the compat DB for this version pair, generating it on demand.
    This is what makes the tool general: any source->target pair works, because the
    map is probed from the two Blender builds themselves rather than hardcoded."""
    src, tgt = _mm(source_version), _mm(target_version)
    name = f"compat_db_{src}_to_{tgt}.json"
    bundled = os.path.join(APP, name)                 # ships with the app (e.g. 4.4->4.2)
    if os.path.exists(bundled):
        return bundled
    cached = os.path.join(_dbs_dir(), name)           # previously generated
    if os.path.exists(cached):
        return cached
    import blender_manage, gen_compat_db               # generate fresh from both builds
    src_bl = blender_manage.ensure(src, CFG)
    tgt_bl = blender_manage.ensure(tgt, CFG)
    gen_compat_db.generate(src_bl, tgt_bl, src, tgt, cached)
    return cached

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

def scan(path, target_version="4.2"):
    ver = detect_version(path)
    if not ver: raise RuntimeError("not a .blend file (no version header)")
    src = _blender_for(ver)
    db = get_db(ver, target_version)          # resolves/generates the map for this pair
    out = tempfile.mktemp(suffix=".json")
    try:
        r = _run(src, path, "scan_ui.py", ["--db", db, "--out", out])
        if "SCAN_OK" not in r.stdout: raise RuntimeError(r.stderr[-600:] or "scan failed")
        data = json.load(open(out))
        data["detected"] = ver
        data["target"] = target_version
        data["blenders"] = blenders()
        return data
    finally:
        if os.path.exists(out): os.unlink(out)

def convert(path, selected_ids, source_version, target_version, out_path, apply_modifiers=None, remove_modifiers=None, purge_unused=False):
    src = _blender_for(source_version)
    tgt = _blender_for(target_version)     # auto-downloads target build if missing
    db = get_db(source_version, target_version)
    work = tempfile.mkdtemp(prefix="relay_")
    src_copy = os.path.join(work, "source.blend")
    shutil.copy2(path, src_copy)                 # ORIGINAL is only ever READ, never opened for writing
    sel = os.path.join(work, "sel.json"); man = os.path.join(work, "m.json")
    apl = os.path.join(work, "apply.json"); rmv = os.path.join(work, "remove.json"); inter = os.path.join(work, "inter.blend")
    json.dump(selected_ids, open(sel, "w"))
    json.dump(apply_modifiers or [], open(apl, "w"))
    json.dump(remove_modifiers or [], open(rmv, "w"))
    try:
        r1 = _run(src, src_copy, "convert_source.py", ["--select", sel, "--apply", apl, "--remove", rmv, "--db", db, "--manifest", man, "--purge", "1" if purge_unused else "0", "--out", inter])
        if "SRC_OK" not in r1.stdout: raise RuntimeError(r1.stderr[-600:] or "source stage failed")
        r2 = _run(tgt, inter, "convert_target.py", ["--select", sel, "--db", db, "--manifest", man, "--out", out_path])
        if "TGT_OK" not in r2.stdout: raise RuntimeError(r2.stderr[-600:] or "target stage failed")
        return {"out": out_path,
                "source_fixed": int(r1.stdout.split("fixed=")[1].split()[0]),
                "kept": int(r1.stdout.split("keep_recorded=")[1].split()[0]),
                "applied": int(r1.stdout.split("applied=")[1].split()[0]),
                "removed": int(r1.stdout.split("removed=")[1].split()[0]),
                "purged": int(r1.stdout.split("purged=")[1].split()[0]),
                "rebuilt": int(r2.stdout.split("rebuilt=")[1].split()[0])}
    finally:
        shutil.rmtree(work, ignore_errors=True)
