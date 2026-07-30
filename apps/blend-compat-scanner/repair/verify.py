#!/usr/bin/env python3
"""
verify.py — regression harness for repair fixers. Run in the SOURCE version.
===========================================================================
Every fixer must pass here before it is trusted: the reconstructed graph must
produce output identical to the original when evaluated. Run:

  blender-4.4 -b --python verify.py

Prints PASS/FAIL per check and a final summary; exits non-zero on any failure.
"""

import bpy
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fixers  # noqa: E402

RESULTS = []


def _fresh_gn():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.mesh.primitive_cube_add()
    obj = bpy.context.active_object
    mod = obj.modifiers.new("GN", "NODES")
    ng = bpy.data.node_groups.new("g", "GeometryNodeTree")
    mod.node_group = ng
    ng.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    ng.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    gin = ng.nodes.new("NodeGroupInput")
    gout = ng.nodes.new("NodeGroupOutput")
    return obj, ng, gin, gout


def _store_int(ng, gin, src_out, gout):
    sto = ng.nodes.new("GeometryNodeStoreNamedAttribute")
    sto.data_type = "INT"; sto.domain = "POINT"
    sto.inputs["Name"].default_value = "r"
    ng.links.new(gin.outputs[0], sto.inputs["Geometry"])
    for s in sto.inputs:
        if s.type == "INT" and s.name != "Name":
            ng.links.new(src_out, s); break
    ng.links.new(sto.outputs["Geometry"], gout.inputs[0])


def _int_val(obj):
    d = bpy.context.evaluated_depsgraph_get()
    return obj.evaluated_get(d).to_mesh().attributes["r"].data[0].value


def check_integer_math():
    ops = list(fixers._IMATH_MAP.keys())
    pairs = [(7, 3, 2), (-7, 3, 2), (7, -3, 2), (-7, -3, 2), (10, 5, 1), (2, 10, 3)]
    bad = 0
    for op in ops:
        for a, b, c in pairs:
            obj, ng, gin, gout = _fresh_gn()
            im = ng.nodes.new("FunctionNodeIntegerMath"); im.operation = op
            im.inputs[0].default_value = a; im.inputs[1].default_value = b
            if len(im.inputs) > 2:
                im.inputs[2].default_value = c
            _store_int(ng, gin, im.outputs[0], gout)
            before = _int_val(obj)
            fixers.fix_integer_math(ng, im)
            after = _int_val(obj)
            if before != after:
                bad += 1
                print(f"   FAIL IntegerMath {op} ({a},{b},{c}): {before} != {after}")
    RESULTS.append(("IntegerMath exact-equal (all supported ops x signed inputs)", bad == 0))


def check_safe_drop_passthrough():
    obj, ng, gin, gout = _fresh_gn()
    sub = ng.nodes.new("GeometryNodeSubdivisionSurface")
    sgn = ng.nodes.new("GeometryNodeSetGeometryName")
    sgn.inputs["Name"].default_value = "foo"
    ng.links.new(gin.outputs[0], sub.inputs[0])
    ng.links.new(sub.outputs[0], sgn.inputs["Geometry"])
    ng.links.new(sgn.outputs["Geometry"], gout.inputs[0])

    def positions():
        d = bpy.context.evaluated_depsgraph_get()
        me = obj.evaluated_get(d).to_mesh()
        return [tuple(round(x, 6) for x in v.co) for v in me.vertices]

    before = positions()
    fixers.fix_safe_drop(ng, sgn)
    after = positions()
    gone = not any(n.bl_idname == "GeometryNodeSetGeometryName" for n in ng.nodes)
    RESULTS.append(("SetGeometryName safe-drop (geometry identical + removed)",
                    before == after and gone))


def main():
    check_integer_math()
    check_safe_drop_passthrough()
    print("\n" + "=" * 60)
    ok = True
    for name, passed in RESULTS:
        print(f"  {'PASS' if passed else 'FAIL'}  {name}")
        ok = ok and passed
    print("=" * 60)
    print(" ALL PASS" if ok else " SOME FAILURES")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
