# vertex_lit_renderer/material_shader.py
"""
Per-material shader builder + cache (structure-aware).

Wraps node_transpiler: turns a material's node graph into a fragment that
computes base colour live, pairs it with the engine's MAIN_VERT (lighting/
shadow/GI unchanged), compiles, and caches per material.

Recompile policy
----------------
The program is keyed by node_transpiler.topo_signature(mat), which ignores
tweakable values (they're uniforms). While the signature is unchanged the
compiled program is REUSED — dragging Mapping Scale, a Mix factor, colours,
Value/RGB, etc. only updates uniforms (engine reads them live each draw), never
recompiles. Structure changes (add/remove/relink a node, change an operation/
blend mode, swap an image, edit a ColorRamp) change the signature and recompile.

Compilation happens at DRAW time (GPU context live in view_draw). On failure —
only truly judgeable on a real GPU — the entry is `failed` and the engine falls
back to the legacy single-texture path for that material, so a bad transpile can
never black out the viewport.
"""

from __future__ import annotations
import gpu

from .shaders import MAIN_VERT
from . import node_transpiler as _nt

_FRAG_HEAD = "in vec4 vLight;\nin vec2 vUV;\nout vec4 outColor;\n"
_FRAG_MAIN = (
    "void main() {\n"
    "    vec4 base = computeBaseColor(vUV);\n"
    "    outColor = vec4(vLight.rgb * base.rgb, vLight.a * base.a);\n"
    "}\n"
)

# mat.name -> {shader, samplers[(uniform,image)], params[Param], failed, notes, sig, frag, error}
_prog_cache = {}
# materials whose graph MIGHT have changed since last compile (set by engine.view_update)
_dirty_mats = set()


def build_material_frag(mat):
    """Return (frag_source, transpile_result). No GPU needed."""
    res = _nt.transpile_material(mat)
    sampler_decls = "".join("uniform sampler2D {};\n".format(s.uniform) for s in res.samplers)
    param_decls = "".join(d + "\n" for d in res.param_decls)
    frag = (_FRAG_HEAD + sampler_decls + param_decls + _nt.HELPERS + "\n"
            + res.glsl + "\n" + _FRAG_MAIN)
    return frag, res


def mark_dirty(name):
    _dirty_mats.add(name)


def invalidate(name=None):
    if name is None:
        _prog_cache.clear(); _dirty_mats.clear()
    else:
        _prog_cache.pop(name, None); _dirty_mats.discard(name)


def _compile(mat):
    ent = {"shader": None, "samplers": [], "params": [], "failed": False,
           "notes": [], "sig": _nt.topo_signature(mat), "error": ""}
    try:
        frag, res = build_material_frag(mat)
        ent["shader"] = gpu.types.GPUShader(MAIN_VERT, frag)
        ent["samplers"] = [(s.uniform, s.image) for s in res.samplers]
        ent["params"] = res.params
        ent["notes"] = res.notes
        ent["frag"] = frag
    except Exception as e:                      # pragma: no cover (GPU-side)
        ent["failed"] = True
        ent["error"] = str(e)
    return ent


def get_program(mat):
    """
    Cached program for `mat`. Recompiles only when the structural signature
    changes; otherwise reuses the compiled shader (value edits are uniforms).
    """
    if mat is None:
        return None
    name = mat.name
    ent = _prog_cache.get(name)
    dirty = name in _dirty_mats

    if ent is not None and not dirty:
        return ent  # fast path: nothing flagged this material

    # Flagged (or first time): check whether STRUCTURE actually changed.
    _dirty_mats.discard(name)
    if ent is not None and not ent["failed"] and ent["shader"] is not None:
        if ent["sig"] == _nt.topo_signature(mat):
            return ent  # only values changed -> reuse compiled program

    ent = _compile(mat)
    _prog_cache[name] = ent
    return ent
