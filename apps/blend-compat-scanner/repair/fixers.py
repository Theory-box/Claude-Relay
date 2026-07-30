#!/usr/bin/env python3
"""
fixers.py — value-preserving reconstruction of breaking nodes.
=============================================================
All fixers run in the SOURCE version (e.g. 4.4), transforming a node tree so the
saved file survives the older target (e.g. 4.2). They carry input values and
relink, and never touch anything they don't understand.

Each fixer returns one of:
    "fixed"       - reconstructed with verified-equivalent behaviour
    "flagged"     - recognised but not safely reconstructable; left in place
    None          - not handled by this fixer

Verification standard (see repair/verify.py): a fixer is only added here after
its output is confirmed identical to the original by evaluation in the source
version AND the saved file opens in the target with no undefined nodes.
"""

import bpy


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _incoming(nt, node, socket):
    for l in nt.links:
        if l.to_node == node and l.to_socket == socket:
            return l.from_socket
    return None


def _outgoing_targets(nt, node, from_socket=None):
    return [l.to_socket for l in nt.links
            if l.from_node == node and (from_socket is None or l.from_socket == from_socket)]


# --------------------------------------------------------------------------- #
# safe-drop: node has no effect on evaluated output. Remove it, and if it has a
# geometry passthrough, reconnect around it.
# --------------------------------------------------------------------------- #
SAFE_DROP = {
    "GeometryNodeSetGeometryName",
    "GeometryNodeGizmoDial", "GeometryNodeGizmoLinear", "GeometryNodeGizmoTransform",
    "GeometryNodeWarning",
}


def fix_safe_drop(nt, node):
    # reconnect a geometry passthrough if present (e.g. Set Geometry Name)
    geo_in = next((s for s in node.inputs if s.type == "GEOMETRY"), None)
    geo_out = next((s for s in node.outputs if s.type == "GEOMETRY"), None)
    if geo_in is not None and geo_out is not None:
        src = _incoming(nt, node, geo_in)
        if src is not None:
            for tgt in _outgoing_targets(nt, node, geo_out):
                nt.links.new(src, tgt)
    nt.nodes.remove(node)
    return "fixed"


# --------------------------------------------------------------------------- #
# reconstruct: FunctionNodeIntegerMath -> Math node(s). Verified exact-equal for
# all supported ops across signed inputs (repair/verify.py).
# --------------------------------------------------------------------------- #
_IMATH_MAP = {
    "ADD": ("ADD", None), "SUBTRACT": ("SUBTRACT", None), "MULTIPLY": ("MULTIPLY", None),
    "MULTIPLY_ADD": ("MULTIPLY_ADD", None), "ABSOLUTE": ("ABSOLUTE", None),
    "POWER": ("POWER", None), "MINIMUM": ("MINIMUM", None), "MAXIMUM": ("MAXIMUM", None),
    "SIGN": ("SIGN", None), "MODULO": ("MODULO", None), "FLOORED_MODULO": ("FLOORED_MODULO", None),
    "DIVIDE": ("DIVIDE", "TRUNC"), "DIVIDE_ROUND": ("DIVIDE", "ROUND"),
    "DIVIDE_FLOOR": ("DIVIDE", "FLOOR"), "DIVIDE_CEIL": ("DIVIDE", "CEIL"),
    "NEGATE": ("_NEGATE", None),
}
_IMATH_UNSUPPORTED = {"GCD", "LCM"}   # no Math equivalent; would need a subgraph


def fix_integer_math(nt, node):
    op = node.operation
    if op in _IMATH_UNSUPPORTED:
        return "flagged"
    math_op, post = _IMATH_MAP.get(op, (None, None))
    if math_op is None:
        return "flagged"

    ins = []
    for s in node.inputs:
        link = _incoming(nt, node, s)
        ins.append(("link", link) if link is not None else ("val", s.default_value))
    targets = _outgoing_targets(nt, node)

    m = nt.nodes.new("ShaderNodeMath")
    if math_op == "_NEGATE":
        m.operation = "MULTIPLY"
        kind, payload = ins[0]
        if kind == "link":
            nt.links.new(payload, m.inputs[0])
        else:
            m.inputs[0].default_value = float(payload)
        m.inputs[1].default_value = -1.0
    else:
        m.operation = math_op
        for i, (kind, payload) in enumerate(ins):
            if i >= len(m.inputs):
                break
            if kind == "link":
                nt.links.new(payload, m.inputs[i])
            else:
                m.inputs[i].default_value = float(payload)

    final = m
    if post:
        r = nt.nodes.new("ShaderNodeMath")
        r.operation = post
        nt.links.new(m.outputs[0], r.inputs[0])
        final = r
    for t in targets:
        nt.links.new(final.outputs[0], t)
    nt.nodes.remove(node)
    return "fixed"


# --------------------------------------------------------------------------- #
# subtype value-loss: ShaderNodeBlackbody. Its Temperature socket subtype
# (NodeSocketFloatColorTemperature) doesn't exist in the target, so the value
# drops (and a *link* into it crashes the target on load). Fix by baking the
# constant temperature to its evaluated colour in a plain RGB / Color node, which
# survives cleanly. A linked/animated temperature can't bake -> flagged.
# --------------------------------------------------------------------------- #
_bb_cache = {}


def blackbody_color(T):
    key = round(float(T), 3)
    if key in _bb_cache:
        return _bb_cache[key]
    tg = bpy.data.node_groups.new("_bbtmp", "GeometryNodeTree")
    tg.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    tg.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    i = tg.nodes.new("NodeGroupInput"); o = tg.nodes.new("NodeGroupOutput")
    b = tg.nodes.new("ShaderNodeBlackbody"); b.inputs["Temperature"].default_value = T
    s = tg.nodes.new("GeometryNodeStoreNamedAttribute")
    s.data_type = "FLOAT_COLOR"; s.domain = "POINT"; s.inputs["Name"].default_value = "_bb"
    tg.links.new(i.outputs[0], s.inputs["Geometry"])
    tg.links.new(b.outputs["Color"], [x for x in s.inputs if x.type == "RGBA"][0])
    tg.links.new(s.outputs["Geometry"], o.inputs[0])
    bpy.ops.mesh.primitive_cube_add(); tobj = bpy.context.active_object
    tobj.modifiers.new("t", "NODES").node_group = tg
    d = bpy.context.evaluated_depsgraph_get()
    col = [float(x) for x in tobj.evaluated_get(d).to_mesh().attributes["_bb"].data[0].color]
    bpy.data.objects.remove(tobj); bpy.data.node_groups.remove(tg)
    _bb_cache[key] = col
    return col


def fix_blackbody(nt, node):
    temp = node.inputs["Temperature"]
    if temp.is_linked:
        return "flagged"   # dynamic temperature can't bake to a constant colour
    col = blackbody_color(temp.default_value)
    targets = _outgoing_targets(nt, node)
    if nt.type == "GEOMETRY":
        cn = nt.nodes.new("FunctionNodeInputColor"); cn.value = col
    else:
        cn = nt.nodes.new("ShaderNodeRGB"); cn.outputs[0].default_value = col
    for t in targets:
        nt.links.new(cn.outputs[0], t)
    nt.nodes.remove(node)
    return "fixed"


# --------------------------------------------------------------------------- #
# registry: node bl_idname -> fixer
#
# Blackbody is deliberately NOT in the default registry: the preferred fix keeps
# it a real Blackbody node (repair/keep_blackbody_run.py, two-stage) rather than
# baking it to a colour, since users who work in temperature want the node.
# fix_blackbody (bake -> RGB/Color) remains available as a one-command alternative
# for those who don't need to keep the node.
# --------------------------------------------------------------------------- #
FIXERS = {
    "FunctionNodeIntegerMath": fix_integer_math,
}
FIXERS.update({nid: fix_safe_drop for nid in SAFE_DROP})

BAKE_ALTERNATIVE = {"ShaderNodeBlackbody": fix_blackbody}   # opt-in
NEEDS_TWO_STAGE = {"ShaderNodeBlackbody"}                   # -> keep_blackbody_run.py


def apply_fixer(nt, node):
    fn = FIXERS.get(node.bl_idname)
    return fn(nt, node) if fn else None
