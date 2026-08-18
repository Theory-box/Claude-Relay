# PyInstaller spec — one-file merge-analyzer executable.
# Paths are anchored to this spec's own directory (SPECPATH) so the build works
# regardless of the current working directory it's invoked from.
import os
from PyInstaller.utils.hooks import collect_all

HERE = SPECPATH  # directory containing this .spec (apps/blend-merge-analyzer)

datas = [
    (os.path.join(HERE, "ui", "merge-analyzer.html"), "blend-merge-analyzer/ui"),
    (os.path.join(HERE, "backend"),                    "blend-merge-analyzer/backend"),
]
binaries = []
hiddenimports = ["engine", "server", "analyze", "blender_manage"]
for pkg in ("webview",):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h

a = Analysis([os.path.join(HERE, "backend", "relay_app.py")],
             pathex=[os.path.join(HERE, "backend")],
             binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             hookspath=[], runtime_hooks=[], excludes=[])
pyz = PYZ(a.pure, a.zipped_data)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
          name="MergeAnalyzer", debug=False, strip=False, upx=False, console=False)
