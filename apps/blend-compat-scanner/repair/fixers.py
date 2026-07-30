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
# registry: node bl_idname -> fixer
# --------------------------------------------------------------------------- #
FIXERS = {"FunctionNodeIntegerMath": fix_integer_math}
FIXERS.update({nid: fix_safe_drop for nid in SAFE_DROP})


def apply_fixer(nt, node):
    fn = FIXERS.get(node.bl_idname)
    return fn(nt, node) if fn else None
