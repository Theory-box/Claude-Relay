# vertex_lit_renderer/material_shader.py
"""
Per-material shader builder + cache (structure- and mode-aware).

Wraps node_transpiler: turns a material's node graph into a fragment that
computes base colour live, pairs it with the mode-appropriate vertex shader
(Gouraud passes vLight; Phong passes world pos/normal and lights per-fragment),
compiles, and caches per (material, shading_mode).

Recompile policy: keyed by node_transpiler.topo_signature(mat) AND shading mode.
Value edits (Mapping scale, mix factor, colours…) are uniforms -> no recompile.
Structure edits or a mode switch -> recompile. Compile happens at draw time; on
failure the engine falls back to the legacy texture path for that material.
"""

from __future__ import annotations
import gpu

from . import shaders as _sh
from . import node_transpiler as _nt

# (mat.name, mode) -> {shader, samplers, params, failed, notes, sig, frag, error}
_prog_cache = {}
_dirty_mats = set()


def _heads(mode):
    if mode == "PIXEL":
        return _sh.PHONG_VERT, _sh.MAT_FRAG_HEAD_PIXEL, _sh.MAT_FRAG_MAIN_PIXEL, _sh.LIGHT_CHUNK
    return _sh.MAIN_VERT, _sh.MAT_FRAG_HEAD_VERTEX, _sh.MAT_FRAG_MAIN_VERTEX, ""


def build_material_frag(mat, mode="VERTEX"):
    """Return (vertex_src, frag_src, transpile_result). No GPU needed."""
    res = _nt.transpile_material(mat)
    vert, head, main, light = _heads(mode)
    sampler_decls = "".join("uniform sampler2D {};\n".format(s.uniform) for s in res.samplers)
    param_decls = "".join(d + "\n" for d in res.param_decls)
    frag = (head + sampler_decls + param_decls + light + _nt.HELPERS + "\n"
            + res.glsl + "\n" + main)
    return vert, frag, res


def mark_dirty(name):
    _dirty_mats.add(name)


def invalidate(name=None):
    if name is None:
        _prog_cache.clear(); _dirty_mats.clear()
    else:
        for k in [k for k in _prog_cache if k[0] == name]:
            _prog_cache.pop(k, None)
        _dirty_mats.discard(name)


def _compile(mat, mode):
    ent = {"shader": None, "samplers": [], "params": [], "failed": False,
           "notes": [], "sig": _nt.topo_signature(mat), "error": "", "mode": mode}
    try:
        vert, frag, res = build_material_frag(mat, mode)
        ent["notes"] = res.notes
        # Diagnostic: how much of the graph the transpiler resolved. 0 samplers on
        # a material you expect to be textured => the image isn't in the Base Color
        # path the transpiler follows (it may be flat, or wired through other inputs).
        print("[VertexLit] live '{}' ({}): {} sampler(s), {} param(s){}".format(
            mat.name, mode, len(res.samplers), len(res.params),
            "  notes=" + str(res.notes) if res.notes else ""))
        # Never render magenta: if the base-colour path hit a node we don't
        # transpile yet, don't use the live shader for this material — let the
        # engine fall back to the (working) base-texture path. Enabling live
        # nodes can only improve materials we fully understand, never break others.
        if any(str(n).startswith("unsupported node") for n in res.notes):
            ent["failed"] = True
            ent["error"] = "unsupported node(s) -> base-texture fallback"
            return ent
        ent["shader"] = gpu.types.GPUShader(vert, frag)
        ent["samplers"] = [(s.uniform, s.image) for s in res.samplers]
        ent["params"] = res.params
        ent["frag"] = frag
    except Exception as e:                      # pragma: no cover (GPU-side)
        ent["failed"] = True
        ent["error"] = str(e)
    if ent["failed"]:
        # Surfaced in the system console so a fallback/compile issue is diagnosable.
        print("[VertexLit] material '{}' ({}): {}".format(mat.name, mode, ent["error"]))
    return ent


def get_program(mat, mode="VERTEX"):
    if mat is None:
        return None
    key = (mat.name, mode)
    ent = _prog_cache.get(key)
    dirty = mat.name in _dirty_mats

    if ent is not None and not dirty:
        return ent

    if ent is not None and not ent["failed"] and ent["shader"] is not None:
        if ent["sig"] == _nt.topo_signature(mat):
            # value-only change: reuse this mode's program; clear dirty only when
            # every cached mode for this material has been revalidated is overkill,
            # so just clear here — other modes recompile lazily on next use.
            _dirty_mats.discard(mat.name)
            return ent

    ent = _compile(mat, mode)
    _prog_cache[key] = ent
    _dirty_mats.discard(mat.name)
    return ent
