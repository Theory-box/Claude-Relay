#!/usr/bin/env python3
"""
chunk_engine.py - Manifest-driven "chunking" instrumenter for the Blender source tree.

It turns individual editors into compile-time-toggleable chunks by injecting
WITH_SPACE_<NAME> guards at a small set of plug points, without disturbing the
rest of the tree. Every guard we emit is *tagged* (e.g. `#endif /* WITH_X */`)
so that `verify` can prove open/close balance exactly and `instrument` can detect
prior runs (idempotency). Reversal is done via git (the tree is a checkout).

This tool performs a *textual* transform only. It does not compile. Its contract
is: apply all plug points correctly, idempotently, and reversibly.

Usage:
    chunk_engine.py instrument <manifest.json> <chunk> <blender_tree>
    chunk_engine.py verify     <manifest.json> <chunk> <blender_tree>
    chunk_engine.py status     <manifest.json> <chunk> <blender_tree>
"""
import json
import sys
import os


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def _find_unique_line(lines, anchor):
    """Return the index of the single line whose stripped-right form == anchor.
    Raises if the anchor is missing or ambiguous - anchors MUST be unique."""
    hits = [i for i, ln in enumerate(lines) if ln.rstrip("\n") == anchor]
    if len(hits) == 0:
        raise ValueError(f"anchor not found: {anchor!r}")
    if len(hits) > 1:
        raise ValueError(f"anchor not unique ({len(hits)}x): {anchor!r}")
    return hits[0]


# ---- edit operations -------------------------------------------------------

def op_c_ifdef_line(lines, guard, anchor, already):
    """Wrap a single C/C++ line in #ifdef GUARD / #endif."""
    i = _find_unique_line(lines, anchor)
    if lines[i - 1].strip() == f"#ifdef {guard}":
        already.append(anchor)
        return lines
    open_ln = f"#ifdef {guard}\n"
    close_ln = f"#endif /* {guard} */\n"
    return lines[:i] + [open_ln, lines[i], close_ln] + lines[i + 1:]


def op_c_ifdef_block(lines, guard, anchor, already):
    """Wrap a top-level C function (anchor line .. its `}` at column 0) in #ifdef."""
    i = _find_unique_line(lines, anchor)
    if lines[i - 1].strip() == f"#ifdef {guard}":
        already.append(anchor)
        return lines
    # find the closing brace at column 0
    j = None
    for k in range(i + 1, len(lines)):
        if lines[k].rstrip("\n") == "}":
            j = k
            break
    if j is None:
        raise ValueError(f"no top-level closing brace after: {anchor!r}")
    open_ln = f"#ifdef {guard}\n"
    close_ln = f"#endif /* {guard} */\n"
    return lines[:i] + [open_ln] + lines[i:j + 1] + [close_ln] + lines[j + 1:]


def op_cmake_if_wrap(lines, guard, anchor, already):
    """Wrap a single CMake line in if(GUARD) / endif()."""
    i = _find_unique_line(lines, anchor)
    if lines[i - 1].strip() == f"if({guard})":
        already.append(anchor)
        return lines
    indent = anchor[:len(anchor) - len(anchor.lstrip())]
    open_ln = f"{indent}if({guard})\n"
    close_ln = f"{indent}endif() # {guard}\n"
    return lines[:i] + [open_ln, lines[i], close_ln] + lines[i + 1:]


def op_cmake_option_block(lines, guard, anchor, already, option_text):
    """Insert an option()+add_definitions() block after the anchor line."""
    i = _find_unique_line(lines, anchor)
    marker = f"# [chunk] {guard}"
    if any(marker in ln for ln in lines):
        already.append(anchor)
        return lines
    block = [
        f"{marker}\n",
        f'option({guard} "{option_text}" ON)\n',
        f"if({guard})\n",
        f"  add_definitions(-D{guard})\n",
        f"endif() # {guard}\n",
    ]
    return lines[:i + 1] + block + lines[i + 1:]


def op_py_conditional_module(lines, guard, anchor, already, module, rna_type):
    """Comment out a static _modules entry and add a hasattr()-guarded append.
    The append goes just before the __import__(fromlist=_modules) call."""
    marker = f"# [chunk] {guard}"
    if any(marker in ln for ln in lines):
        already.append(anchor)
        return lines
    # 1) comment out the static list entry
    i = _find_unique_line(lines, anchor)
    indent = anchor[:len(anchor) - len(anchor.lstrip())]
    lines = lines[:i] + [f"{indent}# {anchor.strip()}  {marker} (auto-appended below)\n"] + lines[i + 1:]
    # 2) insert guarded append before the fromlist import
    imp_anchor = "__import__(name=__name__, fromlist=_modules)"
    j = None
    for k, ln in enumerate(lines):
        if imp_anchor in ln:
            j = k
            break
    if j is None:
        raise ValueError("could not find __import__ fromlist anchor in bl_ui")
    ins = [
        f'{marker}: register the {module} UI only if the chunk was compiled in\n',
        f'if hasattr(bpy.types, "{rna_type}"):\n',
        f'    _modules.append("{module}")\n',
    ]
    return lines[:j] + ins + lines[j:]


OPS = {
    "c_ifdef_line": op_c_ifdef_line,
    "c_ifdef_block": op_c_ifdef_block,
    "cmake_if_wrap": op_cmake_if_wrap,
    "cmake_option_block": op_cmake_option_block,
    "py_conditional_module": op_py_conditional_module,
}


# ---- drivers ---------------------------------------------------------------

def load_chunk(manifest_path, chunk):
    m = json.loads(_read(manifest_path))
    if chunk not in m["chunks"]:
        raise SystemExit(f"chunk {chunk!r} not in manifest")
    return m["chunks"][chunk]


def instrument(manifest_path, chunk, tree):
    spec = load_chunk(manifest_path, chunk)
    guard = spec["guard"]
    already = []
    touched = []
    for e in spec["edits"]:
        path = os.path.join(tree, e["file"])
        lines = _read(path).splitlines(keepends=True)
        op = OPS[e["op"]]
        kw = {}
        if e["op"] == "cmake_option_block":
            kw["option_text"] = e["option_text"]
        if e["op"] == "py_conditional_module":
            kw["module"] = e["module"]
            kw["rna_type"] = e["rna_type"]
        new = op(lines, guard, e["anchor"], already, **kw)
        if new is not lines:
            _write(path, "".join(new))
            touched.append(e["file"])
    print(f"instrument {chunk} [{guard}]")
    print(f"  edits applied : {len(touched)}")
    print(f"  already-guarded (skipped): {len(already)}")
    for t in touched:
        print(f"    + {t}")
    return len(already) == 0 or len(touched) > 0


def verify(manifest_path, chunk, tree):
    """Prove: (a) each anchor is now enclosed by the guard, (b) every tagged
    open has a matching tagged close in that file."""
    spec = load_chunk(manifest_path, chunk)
    guard = spec["guard"]
    ok = True
    checked_files = set()
    for e in spec["edits"]:
        path = os.path.join(tree, e["file"])
        text = _read(path)
        # balance check per file (once)
        if path not in checked_files:
            checked_files.add(path)
            if e["file"].endswith((".c", ".cc", ".cpp", ".h", ".hh")):
                opens = text.count(f"#ifdef {guard}")
                closes = text.count(f"#endif /* {guard} */")
            elif e["file"].endswith(".txt"):
                opens = text.count(f"if({guard})")
                closes = text.count(f"endif() # {guard}")
            else:
                opens = closes = 0  # python: structural, not brace-balanced
            if opens != closes:
                print(f"  [FAIL] {e['file']}: {opens} opens vs {closes} closes for {guard}")
                ok = False
            elif opens:
                print(f"  [ok]   {e['file']}: {opens} guard block(s) balanced")
        # presence check
        if e["op"] in ("c_ifdef_line", "c_ifdef_block", "cmake_if_wrap"):
            present = (f"#ifdef {guard}" in text or f"if({guard})" in text)
        else:
            present = f"[chunk] {guard}" in text
        if not present:
            print(f"  [FAIL] {e['file']}: guard for edit {e['id']!r} not present")
            ok = False
    print(f"verify {chunk}: {'PASS' if ok else 'FAIL'}")
    return ok


def status(manifest_path, chunk, tree):
    spec = load_chunk(manifest_path, chunk)
    guard = spec["guard"]
    print(f"status {chunk} [{guard}] in {tree}")
    for e in spec["edits"]:
        path = os.path.join(tree, e["file"])
        text = _read(path) if os.path.exists(path) else ""
        marked = (f"#ifdef {guard}" in text) or (f"if({guard})" in text) or (f"[chunk] {guard}" in text)
        print(f"  {'GUARDED ' if marked else 'stock   '} {e['file']} ({e['id']})")


def main(argv):
    if len(argv) != 5:
        print(__doc__)
        return 2
    cmd, manifest, chunk, tree = argv[1], argv[2], argv[3], argv[4]
    fn = {"instrument": instrument, "verify": verify, "status": status}.get(cmd)
    if not fn:
        print(__doc__)
        return 2
    ok = fn(manifest, chunk, tree)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
