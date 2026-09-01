# vertex_lit_renderer/material_shader.py
"""
Per-material shader builder + cache.

Wraps node_transpiler: turns a material's node graph into a full fragment
shader that computes base colour live, pairs it with the engine's existing
MAIN_VERT (so lighting/shadow/GI are unchanged), compiles it, and caches the
program per material.

Design notes
------------
* The vertex stage is shared (MAIN_VERT) → lighting/shadow/GI identical to the
  legacy path. Only the fragment's *albedo* is replaced: instead of one
  `texture(uAlbedo, vUV)` it calls the transpiled `computeBaseColor(vUV)`.
* Compilation happens at DRAW time (GPU context is live in view_draw). If it
  raises — which can only really be judged on a real GPU — the entry is marked
  `failed` and the engine falls back to the legacy single-texture path for that
  material. So a bad transpile can never black out the viewport.
* Samplers are stored as (uniform_name, image_datablock). The engine resolves
  the GPUTexture per-draw via its own cache, so editing an image updates the
  preview without recompiling the shader.
* Cache is invalidated per-material on Material updates (see engine.view_update)
  so graph edits recompile. (Mapping values are still baked as literals in this
  spike — promoting them to uniforms to avoid recompile-on-edit is a follow-up.)
"""

from __future__ import annotations
import gpu

from .shaders import MAIN_VERT
from .node_transpiler import transpile_material

_FRAG_HEAD = "in vec4 vLight;\nin vec2 vUV;\nout vec4 outColor;\n"
_FRAG_MAIN = (
    "void main() {\n"
    "    vec4 base = computeBaseColor(vUV);\n"
    "    outColor = vec4(vLight.rgb * base.rgb, vLight.a * base.a);\n"
    "}\n"
)

# mat.name -> {shader, samplers:[(uniform,image)], failed:bool, notes:list, error:str}
_prog_cache = {}


def build_material_frag(mat):
    """Return (frag_source:str, transpile_result). No GPU needed."""
    res = transpile_material(mat)
    decls = "".join("uniform sampler2D {};\n".format(s.uniform) for s in res.samplers)
    frag = _FRAG_HEAD + decls + res.glsl + "\n" + _FRAG_MAIN
    return frag, res


def get_program(mat):
    """
    Return the cached program dict for `mat`, compiling on first use.
    dict keys: shader (GPUShader|None), samplers [(uniform, image)],
               failed (bool), notes (list), error (str, if failed).
    """
    if mat is None:
        return None
    name = mat.name
    ent = _prog_cache.get(name)
    if ent is not None:
        return ent

    ent = {"shader": None, "samplers": [], "failed": False, "notes": [], "error": ""}
    try:
        frag, res = build_material_frag(mat)
        # GPU compile — only meaningfully validated on a real GPU.
        ent["shader"] = gpu.types.GPUShader(MAIN_VERT, frag)
        ent["samplers"] = [(s.uniform, s.image) for s in res.samplers]
        ent["notes"] = res.notes
        ent["frag"] = frag  # kept for debugging / headless inspection
    except Exception as e:                    # pragma: no cover (GPU-side)
        ent["failed"] = True
        ent["error"] = str(e)
    _prog_cache[name] = ent
    return ent


def invalidate(name=None):
    """Drop one material's program (name) or the whole cache (None)."""
    if name is None:
        _prog_cache.clear()
    else:
        _prog_cache.pop(name, None)
