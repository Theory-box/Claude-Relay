# PyInstaller spec — build a one-file Relay executable.
# The Blender-side scripts (scan_ui, convert_*, the scanner + repair modules) and
# the compat DB ship as DATA under "blend-compat-scanner/" so the engine can point
# Blender at them at runtime (they run inside Blender, not in this process).
import os
block_cipher = None
ROOT = os.path.abspath(".")
APPDIR = os.path.join("apps", "blend-compat-scanner")

datas = [
    (os.path.join(APPDIR, "ui", "relay-ui.html"),          "blend-compat-scanner/ui"),
    (os.path.join(APPDIR, "blend_compat_scanner.py"),      "blend-compat-scanner"),
    (os.path.join(APPDIR, "compat_db_4.4_to_4.2.json"),    "blend-compat-scanner"),
    (os.path.join(APPDIR, "backend"),                       "blend-compat-scanner/backend"),
    (os.path.join(APPDIR, "repair"),                        "blend-compat-scanner/repair"),
]

a = Analysis([os.path.join(APPDIR, "backend", "relay_app.py")],
             pathex=[os.path.join(APPDIR, "backend")],
             binaries=[], datas=datas,
             hiddenimports=["engine", "server", "blender_manage", "webview"],
             hookspath=[], runtime_hooks=[], excludes=[], cipher=block_cipher)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
          name="Relay", debug=False, strip=False, upx=True, console=False)
