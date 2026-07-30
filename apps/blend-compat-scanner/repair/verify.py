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


def check_blackbody():
    bad = 0
    for T in (1500, 4000, 6500, 10000):
        obj, ng, gin, gout = _fresh_gn()
        bb = ng.nodes.new("ShaderNodeBlackbody"); bb.inputs["Temperature"].default_value = T
        sto = ng.nodes.new("GeometryNodeStoreNamedAttribute")
        sto.data_type = "FLOAT_COLOR"; sto.domain = "POINT"
        sto.inputs["Name"].default_value = "c"
        ng.links.new(gin.outputs[0], sto.inputs["Geometry"])
        ng.links.new(bb.outputs["Color"], [s for s in sto.inputs if s.type == "RGBA"][0])
        ng.links.new(sto.outputs["Geometry"], gout.inputs[0])

        def col():
            d = bpy.context.evaluated_depsgraph_get()
            return [round(x, 5) for x in obj.evaluated_get(d).to_mesh().attributes["c"].data[0].color]

        before = col()
        fixers.fix_blackbody(ng, bb)
        after = col()
        gone = not any(n.bl_idname == "ShaderNodeBlackbody" for n in ng.nodes)
        if before != after or not gone:
            bad += 1
            print(f"   FAIL Blackbody {T}K: {before} != {after} (gone={gone})")
    RESULTS.append(("Blackbody bake-to-colour (evaluated colour identical across temps)", bad == 0))


def check_matrix_determinant():
    import random
    bad = 0
    for _ in range(5):
        mat = [[round(random.uniform(-3, 3), 2) for _ in range(4)] for _ in range(4)]
        obj, ng, gin, gout = _fresh_gn()
        cm = ng.nodes.new("FunctionNodeCombineMatrix")
        for c in range(4):
            for r in range(4):
                cm.inputs[f"Column {c + 1} Row {r + 1}"].default_value = mat[r][c]
        det = ng.nodes.new("FunctionNodeMatrixDeterminant")
        ng.links.new(cm.outputs[0], det.inputs["Matrix"])
        sto = ng.nodes.new("GeometryNodeStoreNamedAttribute")
        sto.data_type = "FLOAT"; sto.domain = "POINT"; sto.inputs["Name"].default_value = "d"
        ng.links.new(gin.outputs[0], sto.inputs["Geometry"])
        vin = [s for s in sto.inputs if s.type == "VALUE" and s.name != "Name"][0]
        ng.links.new(det.outputs[0], vin)
        ng.links.new(sto.outputs["Geometry"], gout.inputs[0])

        def val():
            d = bpy.context.evaluated_depsgraph_get()
            return obj.evaluated_get(d).to_mesh().attributes["d"].data[0].value

        before = val()                      # Blender's own determinant
        fixers.fix_matrix_determinant(ng, det)
        after = val()                       # reconstructed
        if abs(before - after) > 1e-3:
            bad += 1
            print(f"   FAIL det {mat}: {before} != {after}")
    RESULTS.append(("MatrixDeterminant reconstruct (matches native det, random 4x4)", bad == 0))


def main():
    check_integer_math()
    check_safe_drop_passthrough()
    check_blackbody()
    check_matrix_determinant()
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
