bl_info = {
    "name": "GI to Lights (experimental)",
    "author": "Theory-box / Claude Relay",
    "version": (0, 1, 0),
    "blender": (4, 2, 0),
    "location": "View3D > Sidebar > GI Lights",
    "description": ("Experimental: bake a scene's bounce (indirect) lighting into a small set of "
                    "real Blender lights via Instant-Radiosity harvesting + clustering. Keep direct "
                    "lighting live; the rig approximates the GI so you can iterate without full GI."),
    "category": "Lighting",
}

# ---------------------------------------------------------------------------
# Route 1 (fit-to-full-GI by direct deposition), prototype:
#   1) HARVEST  - shoot particle rays from each real light, random-walk them through the
#                 scene (multi-bounce), and drop a Virtual Point Light (VPL) at every
#                 surface hit carrying the bounced radiance (tinted by that surface's albedo).
#                 This is Keller's Instant Radiosity. No images, no training loop - the
#                 lights are read straight off the trace.
#   2) CLUSTER  - k-means the thousands of VPLs down to N lights (weighted by radiance),
#                 summing member flux so energy is preserved.
#   3) EMIT     - create N soft point lights (fattened to tame the VPL singularity) in a
#                 "GI_Rig" collection. Render with direct-only + this rig to approximate GI.
#
# Energy is physically motivated but APPROXIMATE - absolute brightness is exposed as a
# Strength multiplier to tune against a reference. Spatial layout + colour bleeding are
# the parts that are meant to be correct.
# ---------------------------------------------------------------------------

import bpy
import math
import random
import numpy as np
from mathutils import Vector

RIG_COLL = "GI_Rig"
_EPS = 1.0e-4


# ------------------------------- helpers -----------------------------------

def _luminance(rgb):
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.4152 * rgb[2]


def _albedo(obj):
    """Base-colour RGB of the object's active material (Principled Base Color), default grey."""
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
        for n in mat.node_tree.nodes:  # fall back to any emission/diffuse colour
            if n.type in {"BSDF_DIFFUSE", "EMISSION"}:
                c = n.inputs[0].default_value
                return (c[0], c[1], c[2])
    if mat is not None:
        c = mat.diffuse_color
        return (c[0], c[1], c[2])
    return (0.8, 0.8, 0.8)


def _cosine_hemisphere(n):
    """Cosine-weighted sample in the hemisphere about normal n (Vector)."""
    u1 = random.random()
    u2 = random.random()
    r = math.sqrt(u1)
    theta = 2.0 * math.pi * u2
    x = r * math.cos(theta)
    y = r * math.sin(theta)
    z = math.sqrt(max(0.0, 1.0 - u1))
    # build a basis around n
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


# ------------------------------- harvest -----------------------------------

def harvest_vpls(context, num_rays, max_bounces, min_flux, seed):
    """Return (positions Nx3, normals Nx3, radiance Nx3) numpy arrays of harvested VPLs."""
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
        total_flux = col * power                      # RGB "flux" in the light's own units
        flux_per_ray = total_flux / max(1, num_rays)
        is_sun = (ld.type == "SUN")
        Lpos = lo.matrix_world.translation.copy()
        sun_dir = (lo.matrix_world.to_3x3() @ Vector((0.0, 0.0, -1.0))).normalized()

        for _ in range(num_rays):
            if is_sun:
                # launch from a plane above the scene, along the sun direction
                p = Vector((random.uniform(mn.x, mx.x),
                            random.uniform(mn.y, mx.y),
                            random.uniform(mn.z, mx.z)))
                origin = p - sun_dir * diag
                direction = sun_dir
            else:
                origin = Lpos.copy()
                direction = _uniform_sphere()

            throughput = Vector((flux_per_ray.x, flux_per_ray.y, flux_per_ray.z))
            o = origin
            d = direction
            for _b in range(max_bounces):
                hit, loc, nrm, idx, obj, M = scene.ray_cast(dg, o + d * _EPS, d)
                if not hit:
                    break
                alb = _albedo(obj)
                out = Vector((throughput.x * alb[0],
                              throughput.y * alb[1],
                              throughput.z * alb[2]))   # diffuse radiosity leaving this point
                positions.append((loc.x, loc.y, loc.z))
                normals.append((nrm.x, nrm.y, nrm.z))
                radiance.append((out.x, out.y, out.z))
                throughput = out
                if max(throughput.x, throughput.y, throughput.z) < min_flux:
                    break
                d = _cosine_hemisphere(nrm)
                o = loc

    if not positions:
        return (np.zeros((0, 3)), np.zeros((0, 3)), np.zeros((0, 3)))
    return (np.array(positions, dtype=np.float64),
            np.array(normals, dtype=np.float64),
            np.array(radiance, dtype=np.float64))


# ------------------------------- cluster -----------------------------------

def cluster_vpls(pos, nrm, rad, k, iters, seed):
    """Weighted k-means on VPL positions. Returns list of dicts:
    {pos(3), normal(3), color(3 normalised), power(float sum-luminance)}."""
    n = len(pos)
    if n == 0:
        return []
    k = int(max(1, min(k, n)))
    rng = np.random.default_rng(seed)
    w = np.array([_luminance(r) for r in rad])        # weight by radiance
    w = np.maximum(w, 1e-12)

    # k-means++ style seeding weighted by radiance
    idx0 = rng.choice(n, p=w / w.sum())
    centers = [pos[idx0]]
    for _ in range(1, k):
        d2 = np.min(np.stack([np.sum((pos - c) ** 2, axis=1) for c in centers], axis=0), axis=0)
        prob = d2 * w
        s = prob.sum()
        if s <= 0:
            centers.append(pos[rng.integers(n)])
        else:
            centers.append(pos[rng.choice(n, p=prob / s)])
    C = np.array(centers)

    assign = np.zeros(n, dtype=np.int64)
    for _ in range(iters):
        # assign
        dists = np.stack([np.sum((pos - C[j]) ** 2, axis=1) for j in range(k)], axis=1)
        assign = np.argmin(dists, axis=1)
        # update (radiance-weighted centroid)
        newC = C.copy()
        for j in range(k):
            m = assign == j
            wm = w[m]
            if wm.sum() > 0:
                newC[j] = (pos[m] * wm[:, None]).sum(axis=0) / wm.sum()
        if np.allclose(newC, C):
            C = newC
            break
        C = newC

    clusters = []
    for j in range(k):
        m = assign == j
        if not m.any():
            continue
        rad_sum = rad[m].sum(axis=0)                   # preserve total flux
        nrm_mean = nrm[m].mean(axis=0)
        nl = np.linalg.norm(nrm_mean)
        nrm_mean = nrm_mean / nl if nl > 1e-9 else np.array([0.0, 0.0, 1.0])
        lum = _luminance(rad_sum)
        color = (rad_sum / lum) if lum > 1e-9 else np.array([1.0, 1.0, 1.0])
        clusters.append({"pos": C[j], "normal": nrm_mean,
                         "color": color, "power": float(lum)})
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
        bpy.data.objects.remove(obj, do_unlink=True)
        try:
            if data is not None and data.users == 0:
                bpy.data.lights.remove(data)
        except Exception:
            pass
        n += 1
    return n


def emit_lights(context, clusters, strength, size, offset):
    coll = _rig_collection(context)
    made = 0
    for i, c in enumerate(clusters):
        ld = bpy.data.lights.new("GIRig_%03d" % i, type="POINT")
        ld.energy = strength * c["power"]
        ld.color = (float(c["color"][0]), float(c["color"][1]), float(c["color"][2]))
        ld.shadow_soft_size = size            # fatten the light -> tames the VPL singularity
        ld["gi_rig"] = 1
        ob = bpy.data.objects.new("GIRig_%03d" % i, ld)
        # nudge the light slightly off the surface along its normal so it lights the room
        p = Vector((c["pos"][0], c["pos"][1], c["pos"][2]))
        nrm = Vector((c["normal"][0], c["normal"][1], c["normal"][2]))
        ob.location = p + nrm * offset
        ob["gi_rig"] = 1
        coll.objects.link(ob)
        made += 1
    return made


# ------------------------------- operators ---------------------------------

class GITOLIGHTS_OT_bake(bpy.types.Operator):
    bl_idname = "gitolights.bake"
    bl_label = "Harvest GI -> Lights"
    bl_description = ("Trace bounce light from the scene's real lights and rebuild it as a small "
                      "set of Blender lights. Clears any previous rig first.")
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        sc = context.scene
        clear_rig(context)
        pos, nrm, rad = harvest_vpls(context, sc.gi2l_rays, sc.gi2l_bounces,
                                     sc.gi2l_min_flux, sc.gi2l_seed)
        if len(pos) == 0:
            self.report({"WARNING"}, "No bounce hits - is there a light and geometry in the scene?")
            return {"CANCELLED"}
        clusters = cluster_vpls(pos, nrm, rad, sc.gi2l_lights, sc.gi2l_iters, sc.gi2l_seed)
        made = emit_lights(context, clusters, sc.gi2l_strength, sc.gi2l_size, sc.gi2l_offset)
        self.report({"INFO"}, "Harvested %d VPLs -> %d lights" % (len(pos), made))
        return {"FINISHED"}


class GITOLIGHTS_OT_clear(bpy.types.Operator):
    bl_idname = "gitolights.clear"
    bl_label = "Clear Rig"
    bl_description = "Delete the GI_Rig light collection"
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
        col.prop(sc, "gi2l_strength")
        col.prop(sc, "gi2l_size")
        col.prop(sc, "gi2l_offset")
        adv = layout.column(align=True)
        adv.prop(sc, "gi2l_iters")
        adv.prop(sc, "gi2l_min_flux")
        adv.prop(sc, "gi2l_seed")
        layout.separator()
        layout.operator("gitolights.bake", icon="LIGHT_DATA")
        layout.operator("gitolights.clear", icon="TRASH")


_classes = (GITOLIGHTS_OT_bake, GITOLIGHTS_OT_clear, GITOLIGHTS_PT_panel)


def register():
    S = bpy.types.Scene
    S.gi2l_rays = bpy.props.IntProperty(
        name="Rays / light", default=2000, min=100, max=200000,
        description="Particle rays launched from each real light (more = smoother harvest)")
    S.gi2l_bounces = bpy.props.IntProperty(
        name="Bounces", default=2, min=1, max=8,
        description="Indirect bounces to harvest. 1 = single-bounce; higher = fuller GI")
    S.gi2l_lights = bpy.props.IntProperty(
        name="Lights (N)", default=32, min=1, max=1000,
        description="Number of lights to reduce the harvested VPLs down to")
    S.gi2l_strength = bpy.props.FloatProperty(
        name="Strength", default=1.0, min=0.0, max=1000.0,
        description="Global brightness multiplier for the rig (tune to match a reference)")
    S.gi2l_size = bpy.props.FloatProperty(
        name="Light Size", default=0.5, min=0.0, max=50.0,
        description="Soft radius of each rig light - fattening tames the point singularity")
    S.gi2l_offset = bpy.props.FloatProperty(
        name="Surface Offset", default=0.05, min=0.0, max=5.0,
        description="Push each light this far off its surface along the normal")
    S.gi2l_iters = bpy.props.IntProperty(
        name="k-means iters", default=12, min=1, max=100)
    S.gi2l_min_flux = bpy.props.FloatProperty(
        name="Min Flux", default=0.002, min=0.0, max=1.0,
        description="Stop a walk when carried flux drops below this")
    S.gi2l_seed = bpy.props.IntProperty(name="Seed", default=1, min=0, max=100000)
    for c in _classes:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_classes):
        bpy.utils.unregister_class(c)
    S = bpy.types.Scene
    for p in ("gi2l_rays", "gi2l_bounces", "gi2l_lights", "gi2l_strength", "gi2l_size",
              "gi2l_offset", "gi2l_iters", "gi2l_min_flux", "gi2l_seed"):
        if hasattr(S, p):
            delattr(S, p)


if __name__ == "__main__":
    register()
