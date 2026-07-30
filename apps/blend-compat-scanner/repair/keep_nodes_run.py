#!/usr/bin/env python3
"""
keep_nodes_run.py — one command to preserve subtype value-loss nodes.
====================================================================
Runs both stages of subtype_keep.py: extract at-risk socket values in the source
Blender, rebuild the nodes in the target Blender. Handles every node whose socket
subtype is missing in the target (Blackbody, Volume Principled, ...). Plain Python.

  python3 keep_nodes_run.py \
      --source-blender /path/to/4.4/blender --target-blender /path/to/4.2/blender \
      --in scene.blend --out scene_for_4.2.blend

Output opens in the target with those nodes intact as real native nodes carrying
their original values. Linked/animated at-risk sockets are reported for manual work.
"""

import argparse
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
STAGES = os.path.join(HERE, "subtype_keep.py")


def run(blender, blendfile, extra):
    p = subprocess.run([blender, "-b", blendfile, "--python", STAGES, "--"] + extra,
                       capture_output=True, text=True)
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
    print("stage 1/2 — extract at-risk values (source):")
    run(a.source_blender, a.inp, ["--stage", "extract", "--manifest", manifest])
    print("stage 2/2 — rebuild nodes (target):")
    run(a.target_blender, a.inp, ["--stage", "apply", "--manifest", manifest, "--out", a.out])
    os.unlink(manifest)
    print(f"done -> {a.out}")


if __name__ == "__main__":
    main()
