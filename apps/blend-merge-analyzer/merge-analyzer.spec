# PyInstaller spec — one-file merge-analyzer executable.
import os
from PyInstaller.utils.hooks import collect_all
APPDIR = os.path.join("apps", "blend-merge-analyzer")

datas = [
    (os.path.join(APPDIR, "ui", "merge-analyzer.html"), "blend-merge-analyzer/ui"),
    (os.path.join(APPDIR, "backend"),                    "blend-merge-analyzer/backend"),
]
binaries = []
hiddenimports = ["engine", "server", "analyze", "blender_manage"]
for pkg in ("webview",):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis([os.path.join(APPDIR, "backend", "relay_app.py")],
             pathex=[os.path.join(APPDIR, "backend")],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[], runtime_hooks=[], excludes=[])
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
          name="MergeAnalyzer", debug=False, strip=False, upx=False, console=False)
