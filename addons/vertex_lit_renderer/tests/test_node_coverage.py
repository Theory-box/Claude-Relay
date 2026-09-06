# tests/test_node_coverage.py
"""
Machine-checked transpiler coverage, in the spirit of the blend-compat-scanner:
enumerate EVERY shader node type from the Blender binary itself (not a hand list),
and assert each one is either

  (a) HANDLED   - the transpiler emits real GLSL for it (an `_n_<type>` handler,
                  or one of the structural nodes the walker resolves directly), or
  (b) OUT-OF-SCOPE - listed, with a reason, in KNOWN_NEUTRALISED below. These are
                  nodes that *cannot* become a base-colour function (ray/scene
                  closures, volumes, spectra, output nodes), so they neutralise
                  to a passthrough/white on purpose.

The test FAILS if a node is neither. That is the point: when a future Blender
version adds a node type we've never seen, this turns the silent neutralise into
a red test, so we decide explicitly whether to handle or allow-list it.

Run:  blender --background --factory-startup --python tests/test_node_coverage.py
"""
import bpy, sys, os, importlib.util

_here = os.path.dirname(os.path.realpath(__file__))
_root = os.path.dirname(_here)
sys.path.insert(0, os.path.dirname(_root))
import vertex_lit_renderer as _v
_v.register()
spec = importlib.util.spec_from_file_location(
    "node_transpiler", os.path.join(_root, "node_transpiler.py"))
_nt = importlib.util.module_from_spec(spec); spec.loader.exec_module(_nt)

# Structural / shader nodes the walker resolves without an `_n_` handler.
STRUCTURAL = {
    'GROUP', 'GROUP_INPUT', 'GROUP_OUTPUT', 'REROUTE', 'FRAME',
    'OUTPUT_MATERIAL', 'BSDF_PRINCIPLED', 'EMISSION', 'BSDF_DIFFUSE',
    'MIX_SHADER', 'ADD_SHADER',
}

# Out-of-scope by design. Keyed by bl_idname, grouped by WHY, so this doubles as
# the rationale doc. A node here renders as neutral (passthrough/white) on purpose.
KNOWN_NEUTRALISED = {
    # Ray-traced BSDF closures - we take base colour, not a lit closure.
    'ShaderNodeBsdfAnisotropic', 'ShaderNodeBsdfGlass', 'ShaderNodeBsdfHair',
    'ShaderNodeBsdfHairPrincipled', 'ShaderNodeBsdfMetallic', 'ShaderNodeBsdfRayPortal',
    'ShaderNodeBsdfRefraction', 'ShaderNodeBsdfSheen', 'ShaderNodeBsdfToon',
    'ShaderNodeBsdfTranslucent', 'ShaderNodeBsdfTransparent', 'ShaderNodeEeveeSpecular',
    'ShaderNodeSubsurfaceScattering', 'ShaderNodeHoldout',
    # Volumes - no volume rendering.
    'ShaderNodeVolumeAbsorption', 'ShaderNodeVolumeInfo', 'ShaderNodeVolumePrincipled',
    'ShaderNodeVolumeScatter',
    # Ray / scene-dependent inputs - need tracing or scene context we don't have.
    'ShaderNodeAmbientOcclusion', 'ShaderNodeBevel', 'ShaderNodeCameraData',
    'ShaderNodeFresnel', 'ShaderNodeHairInfo', 'ShaderNodeLayerWeight',
    'ShaderNodeLightFalloff', 'ShaderNodeLightPath', 'ShaderNodeNewGeometry',
    'ShaderNodeObjectInfo', 'ShaderNodeParticleInfo', 'ShaderNodePointInfo',
    'ShaderNodeTangent', 'ShaderNodeWireframe',
    # Normal / displacement - surface-normal effects, out of scope (POM will revisit).
    'ShaderNodeBump', 'ShaderNodeDisplacement', 'ShaderNodeNormal',
    'ShaderNodeNormalMap', 'ShaderNodeVectorDisplacement',
    # Output nodes that aren't the material surface.
    'ShaderNodeOutputAOV', 'ShaderNodeOutputLight', 'ShaderNodeOutputLineStyle',
    'ShaderNodeOutputWorld', 'ShaderNodeBackground',
    # Spectral - need a spectrum->RGB LUT.
    'ShaderNodeBlackbody', 'ShaderNodeWavelength', 'ShaderNodeTexSky', 'ShaderNodeTexIES',
    # Misc / rare / niche.
    'ShaderNodeScript', 'ShaderNodeShaderToRGB', 'ShaderNodeSqueeze',
    'ShaderNodeTexEnvironment', 'ShaderNodeTexGabor', 'ShaderNodeTexPointDensity',
    'ShaderNodeUVAlongStroke', 'ShaderNodeVectorTransform',
}

def _enumerate():
    mat = bpy.data.materials.new('cov'); mat.use_nodes = True; nt = mat.node_tree
    rows = []
    for nm in dir(bpy.types):
        c = getattr(bpy.types, nm, None)
        if not (isinstance(c, type) and issubclass(c, bpy.types.Node)):
            continue
        bid = c.bl_rna.identifier
        if not bid.startswith('ShaderNode'):
            continue
        try:
            n = nt.nodes.new(bid); rows.append((bid, n.type))
        except Exception:
            pass  # abstract base (ShaderNode, ...Custom) - not instantiable
    return sorted(set(rows))

def main():
    t = _nt._Transpiler()
    rows = _enumerate()
    handled, neutralised, unclassified, stale = [], [], [], set(KNOWN_NEUTRALISED)
    for bid, ntype in rows:
        has = getattr(t, '_n_' + ntype.lower(), None) is not None or ntype in STRUCTURAL
        if has:
            handled.append(bid)
            if bid in KNOWN_NEUTRALISED:
                # a node we now handle but still allow-list -> stale entry, warn only
                pass
        elif bid in KNOWN_NEUTRALISED:
            neutralised.append(bid); stale.discard(bid)
        else:
            unclassified.append((bid, ntype)); stale.discard(bid)

    total = len(rows)
    print("=== shader-node coverage (%d types) ===" % total)
    print("  handled:      %d" % len(handled))
    print("  out-of-scope: %d" % len(neutralised))
    fails = []
    if unclassified:
        for bid, ntype in unclassified:
            print("  UNCLASSIFIED: %s (%s) -- handle it, or add to KNOWN_NEUTRALISED" % (bid, ntype))
        fails.append("%d unclassified node(s)" % len(unclassified))
    # allow-list entries that no longer exist in this Blender are harmless; report only.
    stale_here = [b for b in stale if b not in {r[0] for r in rows}]
    if stale_here:
        print("  note: %d allow-list entr(y/ies) absent in this build (ok): %s"
              % (len(stale_here), ", ".join(sorted(stale_here))))

    print("SUMMARY: " + ("FAILED " + ", ".join(fails) if fails else "ALL CHECKS PASSED"))
    _v.unregister()
    if fails:
        raise SystemExit(1)

main()
