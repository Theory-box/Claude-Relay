#!/usr/bin/env python3
"""blender_manage.py — discover installed Blenders and fetch missing ones as
portable builds (self-contained folders; no system install). App-managed builds
live under the Relay app-data folder."""
import os, sys, glob, platform, urllib.request, re, tarfile, zipfile, tempfile, subprocess, json
_UA={"User-Agent":"Mozilla/5.0 (Relay blend-compat)"}
def _open(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=_UA), timeout=30)

def relay_home():
    if sys.platform=="win32": base=os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))
    elif sys.platform=="darwin": base=os.path.expanduser("~/Library/Application Support")
    else: base=os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share"))
    d=os.path.join(base,"Relay","blenders"); os.makedirs(d, exist_ok=True); return d

def _exe(folder):
    for c in ("blender","blender.exe","Blender","Contents/MacOS/Blender"):
        p=os.path.join(folder,c)
        if os.path.exists(p): return p
    hits=glob.glob(os.path.join(folder,"**","blender*"), recursive=True)
    return next((h for h in hits if os.access(h,os.X_OK) and os.path.isfile(h)), None)

def _query_version(exe):
    try:
        out=subprocess.run([exe,"-b","--python-expr","import bpy;print('VER',bpy.app.version_string)"],
                           capture_output=True,text=True,timeout=60).stdout
        m=re.search(r"VER ([\d.]+)",out); return m.group(1) if m else None
    except Exception: return None

def discover(dev_config=None):
    """Return {version_string: exe_path} from dev config + real installs + app-managed."""
    found={}
    if dev_config and os.path.exists(dev_config): found.update(json.load(open(dev_config)))
    roots=[]
    if sys.platform=="win32": roots+=glob.glob(r"C:\Program Files\Blender Foundation\Blender*")
    elif sys.platform=="darwin": roots+=glob.glob("/Applications/Blender*.app")
    else: roots+=glob.glob("/usr/share/blender*")+glob.glob("/opt/blender*")+glob.glob(os.path.expanduser("~/blender*"))
    roots+=glob.glob(os.path.join(relay_home(),"*"))
    for r in roots:
        exe=_exe(r) if os.path.isdir(r) else (r if os.path.isfile(r) else None)
        if exe:
            v=_query_version(exe)
            if v: found[v]=exe
    return found

def _plat():
    m=platform.machine().lower()
    if sys.platform=="win32": return "windows-x64","zip"
    if sys.platform=="darwin": return ("macos-arm64" if m in("arm64","aarch64") else "macos-x64"),"dmg"
    return "linux-x64","tar.xz"

def latest_url(mm):
    """Newest download URL for a major.minor like '4.2' on this platform."""
    suffix,ext=_plat()
    idx=_open(f"https://download.blender.org/release/Blender{mm}/").read().decode("utf-8","ignore")
    files=re.findall(rf"blender-{re.escape(mm)}\.\d+-{suffix}\.{re.escape(ext)}", idx)
    if not files: return None
    latest=sorted(set(files), key=lambda f: [int(x) for x in re.findall(r"\d+",f)[:3]])[-1]
    return f"https://download.blender.org/release/Blender{mm}/{latest}", latest

def ensure(mm, dev_config=None):
    """Return an exe for major.minor `mm`, downloading a portable build if missing."""
    for v,exe in discover(dev_config).items():
        if v.startswith(mm): return exe
    url,fname=latest_url(mm)
    if not url: raise RuntimeError(f"no Blender {mm} build for this platform")
    dest=os.path.join(relay_home(), fname.rsplit(".",2)[0]); tmp=tempfile.mktemp()
    with _open(url) as r, open(tmp,"wb") as f:
        while True:
            chunk=r.read(1<<20)
            if not chunk: break
            f.write(chunk)
    if fname.endswith(".zip"):
        with zipfile.ZipFile(tmp) as z: z.extractall(relay_home())
    elif fname.endswith(".tar.xz"):
        with tarfile.open(tmp) as t: t.extractall(relay_home())
    os.unlink(tmp)
    return _exe(dest)

if __name__=="__main__":
    print("relay home:", relay_home())
    print("this platform build target:", _plat())
    print("latest 4.2 url:", latest_url("4.2"))
