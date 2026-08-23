bl_info = {
    "name": "GI to Lights (experimental)",
    "author": "Theory-box / Claude Relay",
    "version": (0, 2, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > GI Lights",
    "description": ("Experimental: bake a scene's bounce (indirect) lighting into a small set of "
                    "textured area lights via Instant-Radiosity harvesting + clustering. Keep "
                    "direct lighting live; the rig approximates the GI so you can iterate fast."),
    "category": "Lighting",
}

# ---------------------------------------------------------------------------
# Tier 1 pipeline (route 1, harvest - no optimiser yet):
#   HARVEST  - particle-trace bounce light from the real lights, drop a VPL at every hit
#              carrying the bounced radiance tinted by that surface's albedo (Instant Radiosity).
#   CLUSTER  - k-means on position + NORMAL + COLOUR (radiance-weighted) so a cluster is a
#              coherent patch (one wall, one colour) instead of a muddy positional blob. Per
#              cluster we recover its footprint (centre, normal, tangent extents) and splat the
#              member radiances into a small TEXTURE (the "gobo").
#   EMIT     - one camera-invisible emissive area-quad per cluster, sized to the footprint,
#              oriented along the normal, textured with the radiance splat, and calibrated
#              PER CLUSTER from its harvested flux (flux = pi * area * mean-radiance) so the
#              brightness distribution is physical, not one global fudge.
#
# vs v0.1 (naked isotropic point lights): area quads kill the point singularity + give soft
# natural falloff, the texture carries intra-patch variation, normal/colour clustering removes
# the colour drift, and per-cluster calibration fixes local brightness. A single global Strength
# remains for absolute exposure.
# ---------------------------------------------------------------------------

import bpy
import math
import random
import numpy as np
from mathutils import Vector

RIG_COLL = "GI_Rig"
_EPS = 1.0e-4


# ------------------------------- helpers -----------------------------------

def _luminance_np(rgb):
    return 0.2126 * rgb[..., 0] + 0.7152 * rgb[..., 1] + 0.0722 * rgb[..., 2]


def _albedo(obj):
    mat = obj.active_material if obj else None
    if mat is None and obj is not None and len(obj.material_slots):
        for s in obj.material_slots:
            if s.material is not None:
                mat = s.material
                break
    if mat is not None and mat.use_nodes:
        for n in mat.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                c = n.inputs["Base Color"].default_value
                return (c[0], c[1], c[2])
        for n in mat.node_tree.nodes:
            if n.type in {"BSDF_DIFFUSE", "EMISSION"}:
                c = n.inputs[0].default_value
                return (c[0], c[1], c[2])
    if mat is not None:
        c = mat.diffuse_color
        return (c[0], c[1], c[2])
    return (0.8, 0.8, 0.8)


def _cosine_hemisphere(n):
    u1 = random.random()
    u2 = random.random()
    r = math.sqrt(u1)
    theta = 2.0 * math.pi * u2
    x = r * math.cos(theta)
    y = r * math.sin(theta)
    z = math.sqrt(max(0.0, 1.0 - u1))
    n = n.normalized()
    a = Vector((1.0, 0.0, 0.0)) if abs(n.x) < 0.9 else Vector((0.0, 1.0, 0.0))
    t = a.cross(n).normalized()
    b = n.cross(t)
    return (t * x + b * y + n * z).normalized()


def _uniform_sphere():
    z = 2.0 * random.random() - 1.0
    phi = 2.0 * math.pi * random.random()
    r = math.sqrt(max(0.0, 1.0 - z * z))
    return Vector((r * math.cos(phi), r * math.sin(phi), z))


def _scene_bounds(context):
    mn = Vector((1e18, 1e18, 1e18))
    mx = Vector((-1e18, -1e18, -1e18))
    found = False
    for obj in context.scene.objects:
        if obj.type != "MESH":
            continue
        found = True
        for corner in obj.bound_box:
            w = obj.matrix_world @ Vector(corner)
            for i in range(3):
                mn[i] = min(mn[i], w[i])
                mx[i] = max(mx[i], w[i])
    if not found:
        return Vector((-1, -1, -1)), Vector((1, 1, 1))
    return mn, mx


def _ortho_basis(n):
    n = n / (np.linalg.norm(n) + 1e-12)
    a = np.array([1.0, 0.0, 0.0]) if abs(n[0]) < 0.9 else np.array([0.0, 1.0, 0.0])
    u = np.cross(a, n)
    u /= (np.linalg.norm(u) + 1e-12)
    v = np.cross(n, u)
    return u, v, n


def _blur3(tex):
    out = np.zeros_like(tex)
    cnt = 0.0
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            out += np.roll(np.roll(tex, dy, axis=0), dx, axis=1)
            cnt += 1.0
    return out / cnt


# ------------------------------- harvest -----------------------------------

def harvest_vpls(context, num_rays, max_bounces, min_flux, seed):
    random.seed(seed)
    scene = context.scene
    dg = context.evaluated_depsgraph_get()
    mn, mx = _scene_bounds(context)
    diag = (mx - mn).length or 1.0
    lights = [o for o in scene.objects if o.type == "LIGHT" and o.visible_get()]
    positions, normals, radiance = [], [], []
    for lo in lights:
        ld = lo.data
        col = Vector((ld.color[0], ld.color[1], ld.color[2]))
        power = float(getattr(ld, "energy", 10.0))
        flux_per_ray = (col * power) / max(1, num_rays)
        is_sun = (ld.type == "SUN")
        Lpos = lo.matrix_world.translation.copy()
        sun_dir = (lo.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()
        for _ in range(num_rays):
            if is_sun:
                p = Vector((random.uniform(mn.x, mx.x), random.uniform(mn.y, mx.y),
                            random.uniform(mn.z, mx.z)))
                origin = p - sun_dir * diag
                d = sun_dir
            else:
                origin = Lpos.copy()
                d = _uniform_sphere()
            throughput = Vector((flux_per_ray.x, flux_per_ray.y, flux_per_ray.z))
            o = origin
            for _b in range(max_bounces):
                hit, loc, nrm, idx, obj, M = scene.ray_cast(dg, o + d * _EPS, d)
                if not hit:
                    break
                alb = _albedo(obj)
                out = Vector((throughput.x * alb[0], throughput.y * alb[1], throughput.z * alb[2]))
                positions.append((loc.x, loc.y, loc.z))
                normals.append((nrm.x, nrm.y, nrm.z))
                radiance.append((out.x, out.y, out.z))
                throughput = out
                if max(throughput.x, throughput.y, throughput.z) < min_flux:
                    break
                d = _cosine_hemisphere(nrm)
                o = loc
    if not positions:
        return (np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 3)), diag)
    return (np.array(positions), np.array(normals), np.array(radiance), diag)


# ------------------------------- cluster -----------------------------------

def cluster_vpls(pos, nrm, rad, k, iters, seed, normal_w, color_w, tex_size, diag):
    n = len(pos)
    if n == 0:
        return []
    k = int(max(1, min(k, n)))
    lum = np.maximum(_luminance_np(rad), 1e-12)
    chroma = rad / lum[:, None]
    feat = np.concatenate([pos / diag, nrm * normal_w, chroma * color_w], axis=1)

    rng = np.random.default_rng(seed)
    i0 = rng.choice(n, p=lum / lum.sum())
    centers = [feat[i0]]
    for _ in range(1, k):
        d2 = np.min(np.stack([np.sum((feat - c) ** 2, axis=1) for c in centers], axis=0), axis=0)
        prob = d2 * lum
        s = prob.sum()
        centers.append(feat[rng.choice(n, p=prob / s)] if s > 0 else feat[rng.integers(n)])
    C = np.array(centers)

    assign = np.zeros(n, dtype=np.int64)
    for _ in range(iters):
        dists = np.stack([np.sum((feat - C[j]) ** 2, axis=1) for j in range(k)], axis=1)
        assign = np.argmin(dists, axis=1)
        newC = C.copy()
        for j in range(k):
            m = assign == j
            if m.any():
                wj = lum[m]
                newC[j] = (feat[m] * wj[:, None]).sum(0) / wj.sum()
        if np.allclose(newC, C):
            break
        C = newC

    min_size = 0.01 * diag
    clusters = []
    for j in range(k):
        m = assign == j
        cnt = int(m.sum())
        if cnt == 0:
            continue
        P, N, Rd, w = pos[m], nrm[m], rad[m], lum[m]
        centre = (P * w[:, None]).sum(0) / w.sum()
        normal = (N * w[:, None]).sum(0)
        nl = np.linalg.norm(normal)
        normal = normal / nl if nl > 1e-9 else np.array([0.0, 0.0, 1.0])
        u, v, normal = _ortho_basis(normal)
        rel = P - centre
        a = rel @ u
        b = rel @ v
        su = max(float(np.abs(a).max()) if cnt > 1 else min_size, min_size)
        sv = max(float(np.abs(b).max()) if cnt > 1 else min_size, min_size)
        T = int(tex_size)
        tex = np.zeros((T, T, 3))
        ai = np.clip(((a / su) * 0.5 + 0.5) * (T - 1), 0, T - 1).astype(int)
        bi = np.clip(((b / sv) * 0.5 + 0.5) * (T - 1), 0, T - 1).astype(int)
        for t in range(cnt):
            tex[bi[t], ai[t]] += Rd[t]
        if T >= 3:
            tex = _blur3(tex)
        flux = Rd.sum(0)
        area = (2.0 * su) * (2.0 * sv)
        meant = tex.reshape(-1, 3).mean(0)
        scale = np.where(meant > 1e-12, flux / (math.pi * area * meant + 1e-12), 0.0)
        tex = tex * scale
        clusters.append({"centre": centre, "normal": normal, "u": u, "v": v,
                         "su": su, "sv": sv, "tex": tex, "flux": flux})
    return clusters


# ------------------------------- emit --------------------------------------

def _rig_collection(context):
    coll = bpy.data.collections.get(RIG_COLL)
    if coll is None:
        coll = bpy.data.collections.new(RIG_COLL)
        context.scene.collection.children.link(coll)
    return coll


def clear_rig(context):
    coll = bpy.data.collections.get(RIG_COLL)
    if coll is None:
        return 0
    n = 0
    for obj in list(coll.objects):
        data = obj.data
        for slot in list(obj.material_slots):
            m = slot.material
            if m is not None and m.use_nodes:
                for nd in m.node_tree.nodes:
                    if nd.type == "TEX_IMAGE" and nd.image is not None and nd.image.users <= 1:
                        try:
                            bpy.data.images.remove(nd.image)
                        except Exception:
                            pass
        bpy.data.objects.remove(obj, do_unlink=True)
        try:
            if isinstance(data, bpy.types.Mesh) and data.users == 0:
                bpy.data.meshes.remove(data)
            elif isinstance(data, bpy.types.Light) and data.users == 0:
                bpy.data.lights.remove(data)
        except Exception:
            pass
        n += 1
    return n


def _emitter_material(name, img, strength):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    tex = nt.nodes.new("ShaderNodeTexImage")
    tex.image = img
    tex.interpolation = "Linear"
    emn = nt.nodes.new("ShaderNodeEmission")
    emn.inputs["Strength"].default_value = strength
    tr = nt.nodes.new("ShaderNodeBsdfTransparent")
    geo = nt.nodes.new("ShaderNodeNewGeometry")
    mix = nt.nodes.new("ShaderNodeMixShader")
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    nt.links.new(tex.outputs["Color"], emn.inputs["Color"])
    nt.links.new(geo.outputs["Backfacing"], mix.inputs["Fac"])
    nt.links.new(emn.outputs[0], mix.inputs[1])
    nt.links.new(tr.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return mat


def emit_points(context, clusters, strength, size, offset):
    """Emit one soft point light per cluster at its centre, coloured + brightened by its
    harvested flux. In practice this simple emitter beats the textured area quads on a diffuse
    scene (area emitters near surfaces over-light them); kept as the robust default."""
    coll = _rig_collection(context)
    made = 0
    for i, c in enumerate(clusters):
        fl = c["flux"]
        lum = float(0.2126 * fl[0] + 0.7152 * fl[1] + 0.0722 * fl[2])
        ld = bpy.data.lights.new("GIRig_%03d" % i, type="POINT")
        ld.energy = strength * max(lum, 1e-9)
        ld.color = tuple(float(x) for x in np.clip(fl / max(lum, 1e-9), 0.0, None))
        ld.shadow_soft_size = size
        ld["gi_rig"] = 1
        ob = bpy.data.objects.new("GIRig_%03d" % i, ld)
        ob["gi_rig"] = 1
        ob.location = tuple(c["centre"] + c["normal"] * offset)
        coll.objects.link(ob)
        made += 1
    return made


def emit_textured(context, clusters, strength, offset):
    coll = _rig_collection(context)
    made = 0
    for i, c in enumerate(clusters):
        centre = c["centre"]; normal = c["normal"]; u = c["u"]; v = c["v"]
        su = c["su"]; sv = c["sv"]; tex = c["tex"]
        base = centre + normal * offset
        p0 = base - su * u - sv * v
        p1 = base + su * u - sv * v
        p2 = base + su * u + sv * v
        p3 = base - su * u + sv * v
        me = bpy.data.meshes.new("GIRig_%03d" % i)
        me.from_pydata([tuple(p0), tuple(p1), tuple(p2), tuple(p3)], [], [(0, 1, 2, 3)])
        uvl = me.uv_layers.new(name="UV")
        corners = ((0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0))
        for loop in me.loops:
            uvl.data[loop.index].uv = corners[loop.index % 4]
        me.update()
        T = tex.shape[0]
        img = bpy.data.images.new("GIRigTex_%03d" % i, T, T)
        img.colorspace_settings.name = "Non-Color"
        rgba = np.ones((T, T, 4), dtype=np.float32)
        rgba[..., :3] = np.clip(tex, 0.0, None).astype(np.float32)
        img.pixels.foreach_set(rgba.ravel())
        img.pack()
        mat = _emitter_material("GIRigMat_%03d" % i, img, strength)
        me.materials.append(mat)
        ob = bpy.data.objects.new("GIRig_%03d" % i, me)
        ob["gi_rig"] = 1
        try:
            ob.visible_camera = False
            ob.visible_shadow = False
        except Exception:
            pass
        coll.objects.link(ob)
        made += 1
    return made


# ------------------------------- operators ---------------------------------

class GITOLIGHTS_OT_bake(bpy.types.Operator):
    bl_idname = "gitolights.bake"
    bl_label = "Harvest GI -> Lights"
    bl_description = ("Trace bounce light and rebuild it as a small set of textured area lights. "
                      "Clears any previous rig first.")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        sc = context.scene
        clear_rig(context)
        pos, nrm, rad, diag = harvest_vpls(context, sc.gi2l_rays, sc.gi2l_bounces,
                                           sc.gi2l_min_flux, sc.gi2l_seed)
        if len(pos) == 0:
            self.report({"WARNING"}, "No bounce hits - is there a light and geometry?")
            return {"CANCELLED"}
        clusters = cluster_vpls(pos, nrm, rad, sc.gi2l_lights, sc.gi2l_iters, sc.gi2l_seed,
                                sc.gi2l_normal_w, sc.gi2l_color_w, sc.gi2l_tex, diag)
        if sc.gi2l_emitter == "TEXTURED":
            made = emit_textured(context, clusters, sc.gi2l_strength, sc.gi2l_offset)
            kind = "textured"
        else:
            made = emit_points(context, clusters, sc.gi2l_strength, sc.gi2l_size, sc.gi2l_offset)
            kind = "point"
        self.report({"INFO"}, "Harvested %d VPLs -> %d %s lights" % (len(pos), made, kind))
        return {"FINISHED"}


class GITOLIGHTS_OT_clear(bpy.types.Operator):
    bl_idname = "gitolights.clear"
    bl_label = "Clear Rig"
    bl_description = "Delete the GI_Rig collection"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        n = clear_rig(context)
        self.report({"INFO"}, "Removed %d rig lights" % n)
        return {"FINISHED"}


class GITOLIGHTS_PT_panel(bpy.types.Panel):
    bl_label = "GI to Lights"
    bl_idname = "GITOLIGHTS_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "GI Lights"

    def draw(self, context):
        sc = context.scene
        layout = self.layout
        col = layout.column(align=True)
        col.prop(sc, "gi2l_rays")
        col.prop(sc, "gi2l_bounces")
        col.prop(sc, "gi2l_lights")
        layout.separator()
        col = layout.column(align=True)
        col.prop(sc, "gi2l_emitter")
        col.prop(sc, "gi2l_strength")
        col.prop(sc, "gi2l_offset")
        if sc.gi2l_emitter == "POINTS":
            col.prop(sc, "gi2l_size")
        else:
            col.prop(sc, "gi2l_tex")
        adv = layout.column(align=True)
        adv.label(text="Clustering:")
        adv.prop(sc, "gi2l_normal_w")
        adv.prop(sc, "gi2l_color_w")
        adv.prop(sc, "gi2l_iters")
        adv.prop(sc, "gi2l_min_flux")
        adv.prop(sc, "gi2l_seed")
        layout.separator()
        layout.operator("gitolights.bake", icon="LIGHT_AREA")
        layout.operator("gitolights.clear", icon="TRASH")


_classes = (GITOLIGHTS_OT_bake, GITOLIGHTS_OT_clear, GITOLIGHTS_PT_panel)


def register():
    S = bpy.types.Scene
    S.gi2l_rays = bpy.props.IntProperty(
        name="Rays / light", default=6000, min=100, max=500000,
        description="Particle rays launched from each real light")
    S.gi2l_bounces = bpy.props.IntProperty(
        name="Bounces", default=3, min=1, max=8,
        description="Indirect bounces to harvest")
    S.gi2l_lights = bpy.props.IntProperty(
        name="Lights (N)", default=48, min=1, max=2000,
        description="Number of textured area lights to reduce the VPLs down to")
    S.gi2l_emitter = bpy.props.EnumProperty(
        name="Emitter", default="POINTS",
        items=[("POINTS", "Soft Points", "One soft point light per cluster - robust default"),
               ("TEXTURED", "Textured Area", "One textured area quad per cluster - experimental")],
        description="How each cluster is turned into a light")
    S.gi2l_size = bpy.props.FloatProperty(
        name="Light Size", default=0.4, min=0.0, max=50.0,
        description="Soft radius of each point light (fattening tames the point singularity)")
    S.gi2l_strength = bpy.props.FloatProperty(
        name="Strength", default=1.0, min=0.0, max=1000.0,
        description="Global brightness multiplier (per-cluster brightness is already physical)")
    S.gi2l_offset = bpy.props.FloatProperty(
        name="Surface Offset", default=0.02, min=0.0, max=5.0,
        description="Push each area light this far off its surface along the normal")
    S.gi2l_tex = bpy.props.IntProperty(
        name="Gobo Res", default=8, min=1, max=64,
        description="Resolution of each light's radiance texture (1 = flat/untextured)")
    S.gi2l_normal_w = bpy.props.FloatProperty(
        name="Normal weight", default=1.0, min=0.0, max=10.0,
        description="How strongly clustering separates by surface orientation")
    S.gi2l_color_w = bpy.props.FloatProperty(
        name="Colour weight", default=0.6, min=0.0, max=10.0,
        description="How strongly clustering separates by bounced colour")
    S.gi2l_iters = bpy.props.IntProperty(name="k-means iters", default=14, min=1, max=100)
    S.gi2l_min_flux = bpy.props.FloatProperty(name="Min Flux", default=0.002, min=0.0, max=1.0)
    S.gi2l_seed = bpy.props.IntProperty(name="Seed", default=1, min=0, max=100000)
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    S = bpy.types.Scene
    for p in ("gi2l_rays", "gi2l_bounces", "gi2l_lights", "gi2l_emitter", "gi2l_size",
              "gi2l_strength", "gi2l_offset", "gi2l_tex", "gi2l_normal_w", "gi2l_color_w",
              "gi2l_iters", "gi2l_min_flux", "gi2l_seed"):
        if hasattr(S, p):
            delattr(S, p)


if __name__ == "__main__":
    register()
