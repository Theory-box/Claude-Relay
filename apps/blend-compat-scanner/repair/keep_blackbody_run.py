#!/usr/bin/env python3
"""
keep_blackbody_run.py — one command to preserve Blackbody nodes across a downgrade.
=================================================================================
Runs the two stages of blackbody_keep.py for you: extract temperatures in the
source Blender, rebuild the nodes in the target Blender. Plain Python (run OUTSIDE
Blender).

  python3 keep_blackbody_run.py \
      --source-blender /path/to/blender-4.4/blender \
      --target-blender /path/to/blender-4.2/blender \
      --in  scene.blend \
      --out scene_for_4.2.blend

The output is a target-openable file whose Blackbody nodes are real, native nodes
carrying their original temperatures. A linked/animated temperature is reported
and left for manual handling.
"""

import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STAGES = os.path.join(HERE, "blackbody_keep.py")


def run(blender, blendfile, extra):
    cmd = [blender, "-b", blendfile, "--python", STAGES, "--"] + extra
    p = subprocess.run(cmd, capture_output=True, text=True)
    for line in p.stdout.splitlines():
        if line.startswith("[extract]") or line.startswith("[apply]"):
            print(" ", line)
    if p.returncode != 0:
        sys.exit(f"stage failed:\n{p.stderr[-800:]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-blender", required=True)
    ap.add_argument("--target-blender", required=True)
    ap.add_argument("--in", dest="inp", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    manifest = tempfile.mktemp(suffix=".json")
    print("stage 1/2 — extract temperatures (source):")
    run(a.source_blender, a.inp, ["--stage", "extract", "--manifest", manifest])
    print("stage 2/2 — rebuild nodes (target):")
    run(a.target_blender, a.inp, ["--stage", "apply", "--manifest", manifest, "--out", a.out])
    os.unlink(manifest)
    print(f"done -> {a.out}")


if __name__ == "__main__":
    main()
