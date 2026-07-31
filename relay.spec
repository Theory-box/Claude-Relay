# PyInstaller spec — one-file Relay executable (Windows-focused).
import os
from PyInstaller.utils.hooks import collect_all
APPDIR = os.path.join("apps", "blend-compat-scanner")

datas = [
    (os.path.join(APPDIR, "ui", "relay-ui.html"),       "blend-compat-scanner/ui"),
    (os.path.join(APPDIR, "blend_compat_scanner.py"),   "blend-compat-scanner"),
    (os.path.join(APPDIR, "compat_db_4.4_to_4.2.json"), "blend-compat-scanner"),
    (os.path.join(APPDIR, "backend"),                    "blend-compat-scanner/backend"),
    (os.path.join(APPDIR, "repair"),                     "blend-compat-scanner/repair"),
    (os.path.join(APPDIR, "tools"),                      "blend-compat-scanner/tools"),
]
binaries = []
hiddenimports = ["engine", "server", "blender_manage"]
for pkg in ("webview",):                       # pull in pywebview's backends + DLLs
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis([os.path.join(APPDIR, "backend", "relay_app.py")],
             pathex=[os.path.join(APPDIR, "backend")],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[], runtime_hooks=[], excludes=[])
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
          name="Relay", debug=False, strip=False, upx=False, console=False)
