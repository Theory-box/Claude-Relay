bl_info = {
    "name": "Floorplan Trace",
    "author": "Claude",
    "version": (1, 0, 0),
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar (N) > Trace",
    "description": "Click-to-place polyline tracing with angle/alignment/grid snapping.",
    "category": "Mesh",
}

import bpy
import bmesh
from bpy.app.handlers import persistent
from math import radians, atan2, sin, cos, pi
from mathutils import Vector, Quaternion, Matrix
from mathutils.geometry import intersect_line_plane
from bpy_extras.view3d_utils import (
    region_2d_to_origin_3d,
    region_2d_to_vector_3d,
    region_2d_to_location_3d,
    location_3d_to_region_2d,
)

# ------------------------------------------------------------------ state
_running = False
_stop_request = False
_addon_keymaps = []
_pan_kmis = []
_nav_kmis = []
_msgbus_owner = object()
_pending_scale = {}


def _launch_scale_dialog():
    try:
        bpy.ops.object.floorplan_apply_scale('INVOKE_DEFAULT')
    except Exception:
        pass
    return None


# ------------------------------------------------------------------ prefs
class FT_Prefs(bpy.types.AddonPreferences):
    bl_idname = __name__

    free_placement_key: bpy.props.EnumProperty(
        name="Free-placement bind",
        description="Hold this to suspend all snapping for precise placement",
        items=[
            ('RIGHTMOUSE', "Right Mouse (hold)", ""),
            ('LEFT_ALT', "Left Alt (hold)", ""),
            ('LEFT_CTRL', "Left Ctrl (hold)", ""),
            ('LEFT_SHIFT', "Left Shift (hold)", ""),
        ],
        default='LEFT_ALT',
    )

    custom_nav: bpy.props.BoolProperty(
        name="Custom trackpad navigation", default=True,
        description="Remap two-finger to pan/orbit/zoom and one-finger to look. "
                    "Off = stock Blender nav (two-finger orbit), with two-finger pan only when locked",
        update=lambda self, ctx: _refresh_nav())
    pan_ctrl: bpy.props.BoolProperty(name="Ctrl", default=False, update=lambda self, ctx: _refresh_nav())
    pan_shift: bpy.props.BoolProperty(name="Shift", default=True, update=lambda self, ctx: _refresh_nav())
    pan_alt: bpy.props.BoolProperty(name="Alt", default=False, update=lambda self, ctx: _refresh_nav())
    orbit_ctrl: bpy.props.BoolProperty(name="Ctrl", default=False, update=lambda self, ctx: _refresh_nav())
    orbit_shift: bpy.props.BoolProperty(name="Shift", default=False, update=lambda self, ctx: _refresh_nav())
    orbit_alt: bpy.props.BoolProperty(name="Alt", default=False, update=lambda self, ctx: _refresh_nav())
    rts_ctrl: bpy.props.BoolProperty(name="Ctrl", default=True, update=lambda self, ctx: _refresh_nav())
    rts_shift: bpy.props.BoolProperty(name="Shift", default=True, update=lambda self, ctx: _refresh_nav())
    rts_alt: bpy.props.BoolProperty(name="Alt", default=False, update=lambda self, ctx: _refresh_nav())
    rts_invert_x: bpy.props.BoolProperty(name="RTS Invert X", default=False)
    rts_invert_y: bpy.props.BoolProperty(name="RTS Invert Y", default=False)
    look_ctrl: bpy.props.BoolProperty(name="Ctrl", default=True, update=lambda self, ctx: _refresh_nav())
    look_shift: bpy.props.BoolProperty(name="Shift", default=True, update=lambda self, ctx: _refresh_nav())
    look_alt: bpy.props.BoolProperty(name="Alt", default=False, update=lambda self, ctx: _refresh_nav())

    look_sensitivity: bpy.props.FloatProperty(
        name="Look Sensitivity", default=1.0, min=0.05, max=10.0,
        description="Speed of the Ctrl+Shift camera look")
    look_invert_x: bpy.props.BoolProperty(
        name="Invert X", default=False,
        description="Flip horizontal look direction")
    look_invert_y: bpy.props.BoolProperty(
        name="Invert Y", default=True,
        description="Flip vertical look direction")

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "free_placement_key")
        col.separator()
        col.label(text="Toggle shortcut: right-click the 'Trace' button in the")
        col.label(text="N-panel and choose 'Assign Shortcut'.")
        col.separator()

        box = self.layout.box()
        box.label(text="Look / RTS feel")
        box.prop(self, "look_sensitivity")
        row = box.row(align=True)
        row.prop(self, "look_invert_x")
        row.prop(self, "look_invert_y")
        row = box.row(align=True)
        row.prop(self, "rts_invert_x")
        row.prop(self, "rts_invert_y")

        box = self.layout.box()
        box.label(text="Trackpad Navigation")
        box.prop(self, "custom_nav")
        nav = box.column(align=True)
        nav.enabled = self.custom_nav
        nav.label(text="Two-finger: pan / orbit / RTS pan     One-finger: look")
        nav.label(text="(Zoom stays Blender-native)")

        def modrow(label, base):
            r = nav.row(align=True)
            r.label(text=label)
            r.prop(self, base + "_ctrl", toggle=True)
            r.prop(self, base + "_shift", toggle=True)
            r.prop(self, base + "_alt", toggle=True)

        modrow("Pan", "pan")
        modrow("Orbit", "orbit")
        modrow("RTS Pan", "rts")
        modrow("Look", "look")


def get_prefs(context):
    try:
        return context.preferences.addons[__name__].preferences
    except (KeyError, AttributeError):
        return None


def _move_cutter_in_front(rv3d, cutter, target):
    """knife_project only cuts a target that sits *behind* the cutter along the view.
    Slide the cutter along the view axis (toward the camera) until it clears the
    target's front. Moving purely along the view axis leaves the projected outline
    unchanged, so the cut still lands exactly where it was drawn.
    Returns the delta vector applied (to undo later if the cutter is kept)."""
    if rv3d is None:
        return None
    fwd = (rv3d.view_rotation @ Vector((0.0, 0.0, -1.0))).normalized()

    def proj_range(o):
        corners = [o.matrix_world @ Vector(c) for c in o.bound_box]
        ps = [w.dot(fwd) for w in corners]
        return min(ps), max(ps)

    try:
        t_min, _t_max = proj_range(target)
        c_min, c_max = proj_range(cutter)
    except Exception:
        return None
    span = max(abs(_t_max - t_min), abs(c_max - c_min), 1.0)
    margin = span * 0.5 + 0.1
    # want the whole cutter in front of the target's nearest face
    delta = (t_min - margin) - c_max
    move = fwd * delta
    cutter.location = cutter.location + move
    return move


def _do_knife_project(context, cutter, target, cut_through, keep_cutter):
    """Shared core: knife-project `cutter` onto `target` from the current view.
    Returns (ok, message). Leaves the target in Object Mode; deletes the cutter
    unless keep_cutter."""
    if cutter is None or target is None or cutter == target:
        return False, "cutter and target must be two different objects"
    if context.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass
    win = context.window
    # prefer the viewport the tool was invoked from, else the first 3D view
    area = context.area if (context.area and context.area.type == 'VIEW_3D') else None
    if area is None and win is not None:
        area = next((a for a in win.screen.areas if a.type == 'VIEW_3D'), None)
    region = space = rv3d = None
    if area is not None:
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        space = area.spaces.active
        rv3d = space.region_3d if space else None

    # make sure the cutter sits in front of the target along the view axis
    moved = _move_cutter_in_front(rv3d, cutter, target)

    # Order matters (per Blender's own knife_project docs): select the TARGET, enter
    # edit mode on it, and only THEN select the cutter -- then refresh the depsgraph.
    # knife_project reads the cutter's *evaluated* mesh; selecting the cutter before
    # edit mode or skipping this update leaves that evaluated mesh empty, which is what
    # produces the misleading "No other selected objects have wire or boundary edges".
    for o in list(context.view_layer.objects.selected):
        o.select_set(False)
    target.select_set(True)
    context.view_layer.objects.active = target

    ok = False
    msg = ""
    try:
        bpy.ops.object.mode_set(mode='EDIT')
        cutter.select_set(True)
        context.view_layer.update()
        if area is not None and region is not None and space is not None:
            with context.temp_override(window=win, area=area, region=region,
                                       space_data=space):
                bpy.ops.mesh.knife_project(cut_through=cut_through)
        else:
            bpy.ops.mesh.knife_project(cut_through=cut_through)
        ok = True
    except Exception as e:
        ok = False
        msg = str(e)
    try:
        bpy.ops.object.mode_set(mode='OBJECT')
    except Exception:
        pass

    if not keep_cutter:
        try:
            bpy.data.objects.remove(cutter, do_unlink=True)
        except Exception:
            pass
    elif moved is not None:
        # restore the kept cutter to where the user had it
        try:
            cutter.location = cutter.location - moved
        except Exception:
            pass
    return ok, msg


# ------------------------------------------------------------------ settings
class FT_Settings(bpy.types.PropertyGroup):
    use_angle_snap: bpy.props.BoolProperty(name="Angle Snap", default=True)
    angle_increment: bpy.props.FloatProperty(
        name="Angle Step", default=45.0, min=5.0, max=90.0, subtype='ANGLE_UNIT' if False else 'NONE',
        description="Allowed directions, in degrees (45 -> 8 directions, 90 -> pure ortho)")
    angle_tolerance: bpy.props.FloatProperty(
        name="Angle Tolerance", default=7.0, min=0.0, max=45.0,
        description="Snap to an allowed angle only when the drag is within this many degrees of it")
    use_alignment: bpy.props.BoolProperty(name="Alignment Snap", default=True)
    use_extension: bpy.props.BoolProperty(name="Extension Guides", default=True,
        description="Snap to the infinite line extending an existing edge")
    use_relative_angle: bpy.props.BoolProperty(name="Angle From Last Edge", default=True,
        description="Also snap turns relative to the previous segment (e.g. 90 off a 45 wall)")
    use_distance_memory: bpy.props.BoolProperty(name="Distance Memory", default=True,
        description="Snap the current length to lengths/spacings already drawn on this guideline")
    snap_scope: bpy.props.EnumProperty(
        name="Snap Scope",
        description="Which points act as alignment/guide candidates",
        items=[
            ('TRACE', "Current Trace", "Only points in the polyline being drawn"),
            ('OBJECT', "Whole Object", "Every vertex in the active object"),
        ],
        default='TRACE',
    )
    align_px: bpy.props.IntProperty(name="Align Px", default=10, min=1, max=60,
        description="Pixel tolerance for lining up with an earlier point")
    close_px: bpy.props.IntProperty(name="Close Px", default=14, min=2, max=60,
        description="Pixel tolerance for closing onto the start point")
    dist_px: bpy.props.IntProperty(name="Distance Px", default=12, min=2, max=60,
        description="Pixel tolerance for matching a remembered length")
    use_grid: bpy.props.BoolProperty(name="Grid Snap", default=False)
    grid_size: bpy.props.FloatProperty(name="Grid Size", default=0.1, min=0.0001,
        description="Snap increment in scene units")
    mmb_pan_when_locked: bpy.props.BoolProperty(
        name="MMB Pans When Locked", default=True,
        description="While view rotation is locked, plain middle-mouse / two-finger pans instead of orbiting",
        update=lambda self, ctx: _resync_pan())
    cut_through: bpy.props.BoolProperty(
        name="Cut Through", default=False,
        description="Cut both sides of the mesh (project through it) instead of just the front face")
    project_cutter: bpy.props.PointerProperty(
        name="Cutter", type=bpy.types.Object,
        description="Object to knife-project onto the mesh you're editing")


# ------------------------------------------------------------------ operator
class MESH_OT_floorplan_trace(bpy.types.Operator):
    """Toggle floorplan tracing.\nRight-click this button to assign a shortcut"""
    bl_idname = "mesh.floorplan_trace"
    bl_label = "Trace"
    bl_options = {'REGISTER'}

    cut_mode: bpy.props.BoolProperty(default=False, options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        o = context.edit_object
        if o is not None and o.type == 'MESH':
            return True
        return context.mode == 'OBJECT'

    # ---- helpers -------------------------------------------------
    def gather_toggle_keys(self, context):
        keys = set()
        wm = context.window_manager
        for kc in (wm.keyconfigs.user, wm.keyconfigs.addon):
            if not kc:
                continue
            for km in kc.keymaps:
                for kmi in km.keymap_items:
                    if kmi.idname == self.bl_idname and kmi.active:
                        keys.add(kmi.type)
        # never let mouse buttons act as the finish-toggle
        keys.discard('LEFTMOUSE')
        keys.discard('RIGHTMOUSE')
        keys.discard('MIDDLEMOUSE')
        return keys

    def refresh_anchors(self):
        if self.chain:
            self.start_vert = self.chain[0]
            self.start_world = self.mw @ self.chain[0].co
            self.last_world = self.mw @ self.chain[-1].co
        else:
            self.start_vert = None
            self.start_world = None
            self.last_world = None

    def chain_world(self):
        return [self.mw @ v.co for v in self.chain]

    def align_candidates(self, s):
        if not self.chain:
            # first point of a fresh line: allow aligning to existing geometry
            return [self.mw @ v.co for v in self.bm.verts]
        if s.snap_scope == 'OBJECT':
            return [self.mw @ v.co for v in self.bm.verts]
        return self.chain_world()

    def plane_point(self, coord):
        origin = region_2d_to_origin_3d(self.win_region, self.rv3d, coord)
        vec = region_2d_to_vector_3d(self.win_region, self.rv3d, coord)
        if origin is None or vec is None:
            return None
        return intersect_line_plane(origin, origin + vec,
                                    self.plane_origin, self.plane_normal)

    def to2d(self, world):
        return location_3d_to_region_2d(self.win_region, self.rv3d, world)

    def to_uv(self, world):
        d = world - self.plane_origin
        return d.dot(self.u_axis), d.dot(self.v_axis)

    def from_uv(self, u, v):
        return self.plane_origin + self.u_axis * u + self.v_axis * v

    def _ppu(self):
        # screen pixels per 1 unit of uv, so uv-space tolerances match pixel tolerances
        p0 = self.to2d(self.plane_origin)
        p1 = self.to2d(self.from_uv(1.0, 0.0))
        if p0 is None or p1 is None:
            return 1.0
        d = (Vector((p1.x, p1.y)) - Vector((p0.x, p0.y))).length
        return d if d > 1e-6 else 1.0

    def _segments_uv(self, s):
        segs = []
        for i in range(len(self.chain) - 1):
            a = Vector(self.to_uv(self.mw @ self.chain[i].co))
            b = Vector(self.to_uv(self.mw @ self.chain[i + 1].co))
            segs.append((a, b))
        if s.snap_scope == 'OBJECT':
            for e in self.bm.edges:
                a = Vector(self.to_uv(self.mw @ e.verts[0].co))
                b = Vector(self.to_uv(self.mw @ e.verts[1].co))
                segs.append((a, b))
        return segs

    def _distance_candidates(self, s, Lp, d, ppu):
        """Lengths worth snapping to, measured along direction d from last point Lp.
        Scoped to the current guideline: points/edges collinear with (Lp, d)."""
        perp_tol = s.align_px / ppu
        pts_t = []
        for w in self.align_candidates(s):
            rel = Vector(self.to_uv(w)) - Lp
            along = rel.dot(d)
            perp = (rel - d * along).length
            if perp <= perp_tol:
                pts_t.append(along)
        cands = set()
        # land aligned with an existing collinear point
        for t in pts_t:
            if t > 1e-6:
                cands.add(round(t, 6))
        # lengths of edges lying on this guideline
        for a, b in self._segments_uv(s):
            seg = b - a
            L = seg.length
            if L < 1e-6:
                continue
            sd = seg / L
            if abs(sd.dot(d)) > 0.999:
                rel = a - Lp
                if (rel - d * rel.dot(d)).length <= perp_tol:
                    cands.add(round(L, 6))
        # repeated interval (evenly spaced pattern) among collinear points
        ts = sorted(pts_t)
        diffs = [ts[i + 1] - ts[i] for i in range(len(ts) - 1) if ts[i + 1] - ts[i] > 1e-4]
        for dv in diffs:
            if sum(1 for x in diffs if abs(x - dv) <= perp_tol) >= 2:
                cands.add(round(dv, 6))
        return cands

    def compute_target(self, context, coord):
        s = context.scene.floorplan_trace
        raw = self.plane_point(coord)
        if raw is None:
            return None
        res = {'world': raw.copy(), 'close': False, 'guide': None, 'angle': False,
               'ext': None, 'dist': None, 'dist_a': None, 'dist_b': None, 'dir': None}

        if self.free_active:
            return res

        m = Vector(coord)
        ppu = self._ppu()

        # 1. close onto start
        if self.chain and self.start_world is not None and len(self.chain) >= 3:
            s2 = self.to2d(self.start_world)
            if s2 is not None and (m - Vector((s2.x, s2.y))).length <= s.close_px:
                res['world'] = self.start_world.copy()
                res['close'] = True
                return res

        # work in the drawing plane's (u, v) coordinates; P is the running target
        P = Vector(self.to_uv(raw))
        Lp = Vector(self.to_uv(self.last_world)) if self.last_world is not None else None
        angle_locked = False
        locked_dir = None

        # 2. angle snap: world axes plus (optionally) relative to the previous segment
        if Lp is not None and s.use_angle_snap:
            d = P - Lp
            if d.length > 1e-6:
                inc = radians(s.angle_increment)
                if inc > 0:
                    ang = atan2(d.y, d.x)
                    bases = [0.0]
                    if s.use_relative_angle and len(self.chain) >= 2:
                        pa = Vector(self.to_uv(self.mw @ self.chain[-2].co))
                        pb = Vector(self.to_uv(self.mw @ self.chain[-1].co))
                        seg = pb - pa
                        if seg.length > 1e-6:
                            bases.append(atan2(seg.y, seg.x))
                    best_diff = None
                    best_ang = None
                    for base in bases:
                        cand = base + round((ang - base) / inc) * inc
                        diff = abs(atan2(sin(ang - cand), cos(ang - cand)))
                        if best_diff is None or diff < best_diff:
                            best_diff = diff
                            best_ang = cand
                    if best_diff <= radians(s.angle_tolerance):
                        angle_locked = True
                        locked_dir = Vector((cos(best_ang), sin(best_ang)))
                        t = max(0.0, d.dot(locked_dir))
                        P = Lp + locked_dir * t

        if angle_locked:
            # LENGTH snapping along the lock ray: keep the direction square, snap only
            # how far along it. Guideline crossings, remembered lengths, and grid all
            # become candidate distances -> the corner lands on the guide AND stays square.
            cur_t = (P - Lp).dot(locked_dir)
            cands = []  # (t, tol_px, kind, data)
            if s.use_extension:
                for a, b in self._segments_uv(s):
                    e = b - a
                    L = e.length
                    if L < 1e-6:
                        continue
                    e = e / L
                    denom = locked_dir.x * e.y - locked_dir.y * e.x
                    if abs(denom) < 1e-6:
                        continue  # parallel: no crossing
                    ao = a - Lp
                    t = (ao.x * e.y - ao.y * e.x) / denom
                    if t > 1e-6:
                        cands.append((t, s.align_px, 'ext', (a, e)))
            if self.use_alignment_enabled(s):
                for w in self.align_candidates(s):
                    pu, pv = self.to_uv(w)
                    if abs(locked_dir.x) > 1e-6:
                        t = (pu - Lp.x) / locked_dir.x
                        if t > 1e-6:
                            cands.append((t, s.align_px, 'align', w))
                    if abs(locked_dir.y) > 1e-6:
                        t = (pv - Lp.y) / locked_dir.y
                        if t > 1e-6:
                            cands.append((t, s.align_px, 'align', w))
            if s.use_distance_memory:
                for cd in self._distance_candidates(s, Lp, locked_dir, ppu):
                    cands.append((cd, s.dist_px, 'dist', None))
            if s.use_grid and s.grid_size > 0:
                gt = round(cur_t / s.grid_size) * s.grid_size
                if gt > 1e-6:
                    cands.append((gt, s.align_px, 'grid', None))
            best = None
            for c in cands:
                if abs(cur_t - c[0]) * ppu <= c[1]:
                    if best is None or abs(cur_t - c[0]) < abs(cur_t - best[0]):
                        best = c
            if best is not None:
                t, tol, kind, data = best
                P = Lp + locked_dir * t
                if kind == 'ext':
                    res['ext'] = (data[0], data[1])
                elif kind == 'align':
                    res['guide'] = data.copy()
                elif kind == 'dist':
                    res['dist'] = t
                    res['dist_a'] = Lp.copy()
                    res['dist_b'] = P.copy()
        else:
            # not locked: project onto an edge extension, else free x/y alignment + grid
            if s.use_extension:
                best = float(s.align_px)
                hit = None
                for a, b in self._segments_uv(s):
                    e = b - a
                    L = e.length
                    if L < 1e-6:
                        continue
                    e = e / L
                    proj = a + e * (P - a).dot(e)
                    perp = (P - proj).length * ppu
                    if perp < best:
                        best = perp
                        hit = (a, e, proj)
                if hit is not None:
                    a, e, proj = hit
                    P = proj.copy()
                    res['ext'] = (a, e)
            if res['ext'] is None:
                candidates = self.align_candidates(s) if self.use_alignment_enabled(s) else []
                if candidates:
                    best_u = best_v = None
                    bud = bvd = s.align_px
                    gu_w = gv_w = None
                    for w in candidates:
                        w2 = self.to2d(w)
                        if w2 is None:
                            continue
                        cu, cv = self.to_uv(w)
                        if abs(m.x - w2.x) < bud:
                            bud = abs(m.x - w2.x); best_u = cu; gu_w = w
                        if abs(m.y - w2.y) < bvd:
                            bvd = abs(m.y - w2.y); best_v = cv; gv_w = w
                    if best_u is not None:
                        P.x = best_u; res['guide'] = gu_w.copy()
                    if best_v is not None:
                        P.y = best_v; res['guide'] = gv_w.copy()
                    if s.use_grid and s.grid_size > 0:
                        if best_u is None:
                            P.x = round(P.x / s.grid_size) * s.grid_size
                        if best_v is None:
                            P.y = round(P.y / s.grid_size) * s.grid_size
                elif not self.chain:
                    if s.use_grid and s.grid_size > 0:
                        P.x = round(P.x / s.grid_size) * s.grid_size
                        P.y = round(P.y / s.grid_size) * s.grid_size

        res['world'] = self.from_uv(P.x, P.y)
        res['angle'] = angle_locked
        res['dir'] = (locked_dir.copy() if (angle_locked and locked_dir is not None)
                      else None)
        return res

    def use_alignment_enabled(self, s):
        return s.use_alignment

    def place(self, context):
        d = self.current
        if d is None:
            return
        if d['close']:
            if (self.chain and self.start_vert is not None
                    and self.chain[-1] is not self.start_vert):
                try:
                    self.bm.edges.new((self.chain[-1], self.start_vert))
                except ValueError:
                    pass
            bmesh.update_edit_mesh(self.me)
            # loop closed
            if self.cut_mode:
                # in cut mode a closed loop confirms the cut
                self._finish_requested = True
                return
            # normal trace: start a new polyline on next click
            self.chain = []
            self.created = set()
            self.refresh_anchors()
            return
        local = self.mw_inv @ d['world']
        v = self.bm.verts.new(local)
        self.created.add(v)
        if self.chain:
            try:
                self.bm.edges.new((self.chain[-1], v))
            except ValueError:
                pass
        self.chain.append(v)
        self.refresh_anchors()
        bmesh.update_edit_mesh(self.me)

    def remove_last(self, context):
        if not self.chain:
            return
        v = self.chain[-1]
        if v not in self.created:
            return  # don't delete pre-existing geometry
        self.chain.pop()
        self.created.discard(v)
        try:
            self.bm.verts.remove(v)
        except Exception:
            pass
        self.refresh_anchors()
        bmesh.update_edit_mesh(self.me)

    # ---- lifecycle ----------------------------------------------
    def invoke(self, context, event):
        global _running, _stop_request
        if _running:
            _stop_request = True
            return {'CANCELLED'}

        if context.space_data is None or context.space_data.type != 'VIEW_3D':
            self.report({'WARNING'}, "Run from a 3D Viewport")
            return {'CANCELLED'}

        self.created_object = False
        self.cut_target = None
        obj = context.edit_object

        if self.cut_mode:
            # Cut Trace: target is the mesh being edited; trace into a temp cutter object
            if obj is None or obj.type != 'MESH':
                self.report({'WARNING'}, "Enter Edit Mode on the mesh you want to cut")
                return {'CANCELLED'}
            self.cut_target = obj
            bpy.ops.object.mode_set(mode='OBJECT')
            mesh = bpy.data.meshes.new("CutTrace")
            cutter = bpy.data.objects.new("CutTrace", mesh)
            context.collection.objects.link(cutter)
            for o in list(context.selected_objects):
                o.select_set(False)
            cutter.select_set(True)
            context.view_layer.objects.active = cutter
            try:
                bpy.ops.object.mode_set(mode='EDIT')
            except RuntimeError:
                bpy.data.objects.remove(cutter, do_unlink=True)
                self._reenter_target(context)
                self.report({'WARNING'}, "Could not enter Edit Mode")
                return {'CANCELLED'}
            self.created_object = True
            obj = cutter
        elif obj is None or obj.type != 'MESH':
            # Object Mode: spawn a fresh empty mesh object and edit it
            if context.mode != 'OBJECT':
                self.report({'WARNING'}, "Enter Edit Mode on a mesh first")
                return {'CANCELLED'}
            mesh = bpy.data.meshes.new("FloorplanTrace")
            obj = bpy.data.objects.new("FloorplanTrace", mesh)
            context.collection.objects.link(obj)
            for o in list(context.selected_objects):
                o.select_set(False)
            obj.select_set(True)
            context.view_layer.objects.active = obj
            try:
                bpy.ops.object.mode_set(mode='EDIT')
            except RuntimeError:
                bpy.data.objects.remove(obj, do_unlink=True)
                self.report({'WARNING'}, "Could not enter Edit Mode")
                return {'CANCELLED'}
            self.created_object = True

        self.rv3d = context.space_data.region_3d
        self.win_region = next((r for r in context.area.regions
                                if r.type == 'WINDOW'), None)
        if self.win_region is None:
            return {'CANCELLED'}

        self.obj = obj
        self.me = obj.data
        self.bm = bmesh.from_edit_mesh(self.me)
        self.mw = obj.matrix_world.copy()
        self.mw_inv = self.mw.inverted()
        self.created = set()
        self.current = None
        self.free_active = False
        self._finish_requested = False

        # drawing-plane basis from the current view (plans in Top, elevations in Front/Side)
        rot = self.rv3d.view_rotation
        self.u_axis = (rot @ Vector((1.0, 0.0, 0.0))).normalized()
        self.v_axis = (rot @ Vector((0.0, 1.0, 0.0))).normalized()
        self.plane_normal = (rot @ Vector((0.0, 0.0, 1.0))).normalized()

        # continue-from-selection vs fresh
        selected = [v for v in self.bm.verts if v.select]
        if len(selected) == 1:
            self.chain = [selected[0]]
            self.plane_origin = self.mw @ selected[0].co
        else:
            self.chain = []
            self.plane_origin = context.scene.cursor.location.copy()
        self.refresh_anchors()

        self.toggle_keys = self.gather_toggle_keys(context)
        # arm keyboard-toggle only once the launch key is released
        self.armed = event.type not in self.toggle_keys

        _running = True
        _stop_request = False
        context.window_manager.floorplan_trace_active = True

        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            _draw_callback, (self,), 'WINDOW', 'POST_PIXEL')
        if self.cut_mode:
            context.area.header_text_set(
                "CUT: LMB place  |  click start to close  |  Enter: cut into mesh  |  Esc: cancel")
        else:
            context.area.header_text_set(
                "LMB place  |  hold free-key: no snap  |  Backspace: remove point  "
                "|  click start: close  |  Enter/Esc: finish")
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def _reenter_target(self, context):
        target = getattr(self, "cut_target", None)
        if target is None:
            return
        try:
            if context.mode != 'OBJECT':
                bpy.ops.object.mode_set(mode='OBJECT')
            for o in list(context.view_layer.objects.selected):
                o.select_set(False)
            target.select_set(True)
            context.view_layer.objects.active = target
            bpy.ops.object.mode_set(mode='EDIT')
        except Exception:
            pass

    def finish(self, context, cut=True):
        global _running, _stop_request
        _running = False
        _stop_request = False
        try:
            context.window_manager.floorplan_trace_active = False
        except Exception:
            pass
        if getattr(self, "_handle", None):
            try:
                bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            except Exception:
                pass
            self._handle = None

        if self.cut_mode:
            cutter = self.obj
            target = self.cut_target
            try:
                has_geo = self.bm is not None and len(self.bm.verts) >= 2
            except Exception:
                has_geo = False
            s = context.scene.floorplan_trace
            if cut and has_geo and target is not None:
                ok, msg = _do_knife_project(context, cutter, target, s.cut_through,
                                            keep_cutter=False)
                if not ok:
                    self.report({'WARNING'}, "Cut failed: " +
                                (msg or "knife_project found nothing to cut"))
            else:
                # cancelled or nothing drawn: discard the temp cutter
                try:
                    if context.mode != 'OBJECT':
                        bpy.ops.object.mode_set(mode='OBJECT')
                    bpy.data.objects.remove(cutter, do_unlink=True)
                except Exception:
                    pass
            self._reenter_target(context)
        elif getattr(self, "created_object", False):
            # discard an auto-created trace object that never got any geometry
            try:
                empty = self.bm is not None and len(self.bm.verts) == 0
            except Exception:
                empty = False
            if empty:
                try:
                    bpy.ops.object.mode_set(mode='OBJECT')
                    bpy.data.objects.remove(self.obj, do_unlink=True)
                except Exception:
                    pass

        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()
        return {'FINISHED'}

    def modal(self, context, event):
        global _stop_request
        if _stop_request:
            return self.finish(context)

        # bail if we left the mesh / edit mode
        if context.mode != 'EDIT_MESH' or context.edit_object is not self.obj:
            return self.finish(context)

        if context.area:
            context.area.tag_redraw()

        in_win = (self.win_region.x <= event.mouse_x <=
                  self.win_region.x + self.win_region.width and
                  self.win_region.y <= event.mouse_y <=
                  self.win_region.y + self.win_region.height)

        # let the UI (N-panel, header, toggle button) work
        if not in_win and event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE',
                                         'MOUSEMOVE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}

        # viewport navigation
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE',
                          'TRACKPADPAN', 'TRACKPADZOOM'}:
            return {'PASS_THROUGH'}

        prefs = get_prefs(context)
        free_key = prefs.free_placement_key if prefs else 'RIGHTMOUSE'

        # free-placement (hold) key
        if event.type == free_key and free_key != 'LEFTMOUSE':
            if event.value == 'PRESS':
                self.free_active = True
            elif event.value == 'RELEASE':
                self.free_active = False
            coord = (event.mouse_x - self.win_region.x,
                     event.mouse_y - self.win_region.y)
            self.current = self.compute_target(context, coord)
            return {'RUNNING_MODAL'}

        # keyboard toggle-off (user-assigned shortcut)
        if event.type in self.toggle_keys:
            if event.value == 'RELEASE':
                self.armed = True
                return {'RUNNING_MODAL'}
            if event.value == 'PRESS' and self.armed:
                return self.finish(context)
            return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE':
            coord = (event.mouse_x - self.win_region.x,
                     event.mouse_y - self.win_region.y)
            self.current = self.compute_target(context, coord)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            coord = (event.mouse_x - self.win_region.x,
                     event.mouse_y - self.win_region.y)
            self.current = self.compute_target(context, coord)
            self.place(context)
            if self._finish_requested:
                return self.finish(context, cut=True)
            return {'RUNNING_MODAL'}

        if event.type in {'BACK_SPACE', 'DEL'} and event.value == 'PRESS':
            self.remove_last(context)
            return {'RUNNING_MODAL'}

        if event.type in {'RET', 'NUMPAD_ENTER', 'SPACE'} and event.value == 'PRESS':
            return self.finish(context, cut=True)
        if event.type == 'ESC' and event.value == 'PRESS':
            return self.finish(context, cut=False)

        return {'RUNNING_MODAL'}


# ------------------------------------------------------------------ overlay
def _draw_callback(self):
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
    except Exception:
        return
    d = getattr(self, "current", None)
    if not d:
        return
    try:
        def s(w):
            r = self.to2d(w)
            return (r.x, r.y) if r else None

        try:
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        except Exception:
            shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR')

        gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(1.6)

        tgt = s(d['world'])

        # rubber-band segment
        if self.last_world is not None and tgt:
            a = s(self.last_world)
            if a:
                b = batch_for_shader(shader, 'LINES', {"pos": [a, tgt]})
                shader.bind()
                shader.uniform_float("color", (0.20, 0.90, 0.45, 1.0))
                b.draw(shader)

        # extension guide: a long line through the target along the edge's direction
        if d.get('ext') is not None and tgt:
            a_uv, dir_uv = d['ext']
            sa = s(self.from_uv(a_uv.x, a_uv.y))
            sb = s(self.from_uv(a_uv.x + dir_uv.x, a_uv.y + dir_uv.y))
            if sa and sb:
                sd = Vector((sb[0] - sa[0], sb[1] - sa[1]))
                if sd.length > 1e-6:
                    sd = sd.normalized() * 3000.0
                    p1 = (tgt[0] - sd.x, tgt[1] - sd.y)
                    p2 = (tgt[0] + sd.x, tgt[1] + sd.y)
                    b = batch_for_shader(shader, 'LINES', {"pos": [p1, p2]})
                    shader.bind()
                    shader.uniform_float("color", (0.3, 0.7, 1.0, 0.55))
                    b.draw(shader)

        # angle-lock guide: faint ray from the last point through the target
        if (d.get('dir') is not None and self.last_world is not None and tgt
                and d.get('ext') is None):
            la = s(self.last_world)
            if la:
                sd = Vector((tgt[0] - la[0], tgt[1] - la[1]))
                if sd.length > 1e-6:
                    sd = sd.normalized() * 3000.0
                    p1 = (la[0] - sd.x, la[1] - sd.y)
                    p2 = (la[0] + sd.x, la[1] + sd.y)
                    b = batch_for_shader(shader, 'LINES', {"pos": [p1, p2]})
                    shader.bind()
                    shader.uniform_float("color", (0.55, 0.9, 0.55, 0.4))
                    b.draw(shader)

        # distance-memory: highlight the matched span and a tick at the target
        if d.get('dist') is not None and d.get('dist_a') is not None and tgt:
            a_uv = d['dist_a']
            aw = s(self.from_uv(a_uv.x, a_uv.y))
            if aw:
                b = batch_for_shader(shader, 'LINES', {"pos": [aw, tgt]})
                shader.bind()
                shader.uniform_float("color", (1.0, 0.85, 0.2, 0.9))
                b.draw(shader)
                # small perpendicular tick at the target
                r = 7.0
                tick = [(tgt[0] - r, tgt[1] - r), (tgt[0] + r, tgt[1] + r)]
                b = batch_for_shader(shader, 'LINES', {"pos": tick})
                shader.bind()
                shader.uniform_float("color", (1.0, 0.85, 0.2, 1.0))
                b.draw(shader)

        # alignment guide
        if d.get('guide') is not None and tgt:
            g2 = s(d['guide'])
            if g2:
                b = batch_for_shader(shader, 'LINES', {"pos": [g2, tgt]})
                shader.bind()
                shader.uniform_float("color", (1.0, 0.35, 0.7, 0.85))
                b.draw(shader)

        # target marker (small square)
        if tgt:
            r = 5.0
            sq = [(tgt[0]-r, tgt[1]-r), (tgt[0]+r, tgt[1]-r),
                  (tgt[0]+r, tgt[1]+r), (tgt[0]-r, tgt[1]+r), (tgt[0]-r, tgt[1]-r)]
            col = (1.0, 0.8, 0.1, 1.0) if d['close'] else (1.0, 1.0, 1.0, 1.0)
            b = batch_for_shader(shader, 'LINE_STRIP', {"pos": sq})
            shader.bind()
            shader.uniform_float("color", col)
            b.draw(shader)

        # close ring
        if d['close'] and self.start_world is not None:
            c2 = s(self.start_world)
            if c2:
                ring = [(c2[0] + cos(i * pi / 8) * 10.0,
                         c2[1] + sin(i * pi / 8) * 10.0) for i in range(17)]
                b = batch_for_shader(shader, 'LINE_STRIP', {"pos": ring})
                shader.bind()
                shader.uniform_float("color", (1.0, 0.8, 0.1, 1.0))
                b.draw(shader)

        # distance-memory length label
        if d.get('dist') is not None and tgt:
            try:
                import blf
                fid = 0
                try:
                    blf.size(fid, 15)
                except TypeError:
                    blf.size(fid, 15, 72)
                blf.color(fid, 1.0, 0.85, 0.2, 1.0)
                blf.position(fid, tgt[0] + 12, tgt[1] + 12, 0)
                blf.draw(fid, "%.4g" % d['dist'])
            except Exception:
                pass

        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')
    except Exception:
        pass


# ------------------------------------------------------------------ view lock
def _set_pan_active(state):
    for kmi in _pan_kmis:
        try:
            kmi.active = bool(state)
        except Exception:
            pass


def _resync_pan():
    """Match the pan bindings to whatever the current viewport lock state is."""
    locked_any = False
    setting = True
    try:
        for w in bpy.context.window_manager.windows:
            for area in w.screen.areas:
                if area.type != 'VIEW_3D':
                    continue
                for sp in area.spaces:
                    if (sp.type == 'VIEW_3D' and sp.region_3d
                            and sp.region_3d.lock_rotation):
                        locked_any = True
        sc = bpy.context.scene
        if sc:
            setting = sc.floorplan_trace.mmb_pan_when_locked
    except Exception:
        pass
    _set_pan_active(locked_any and setting)


class VIEW3D_OT_floorplan_toggle_lock(bpy.types.Operator):
    """Lock viewport rotation (locks the pan bindings to match)"""
    bl_idname = "view3d.floorplan_toggle_lock"
    bl_label = "Lock View Rotation"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        sd = context.space_data
        return sd is not None and getattr(sd, "region_3d", None) is not None

    def execute(self, context):
        rv = context.space_data.region_3d
        rv.lock_rotation = not rv.lock_rotation
        _resync_pan()
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


# ------------------------------------------------------------------ view nav
class VIEW3D_OT_floorplan_view(bpy.types.Operator):
    """Snap/orbit orthographic views (works even when rotation is locked).\nRight-click to assign a shortcut"""
    bl_idname = "view3d.floorplan_view"
    bl_label = "Floorplan Ortho View"

    action: bpy.props.EnumProperty(
        items=[
            ('TOP', "Top", "Top view"),
            ('BOTTOM', "Bottom", "Bottom view"),
            ('ORBITUP', "Orbit Up", "Pitch the view up 90 degrees"),
            ('ORBITDOWN', "Orbit Down", "Pitch the view down 90 degrees"),
            ('ORBITLEFT', "Orbit Left", "Next side view to the left"),
            ('ORBITRIGHT', "Orbit Right", "Next side view to the right"),
            ('ROLLLEFT', "Roll Left", "Roll the view 90 degrees left"),
            ('ROLLRIGHT', "Roll Right", "Roll the view 90 degrees right"),
        ],
        default='TOP',
    )

    @classmethod
    def poll(cls, context):
        sd = context.space_data
        return sd is not None and sd.type == 'VIEW_3D'

    def execute(self, context):
        area = context.area
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        if region is None:
            return {'CANCELLED'}
        rv = context.space_data.region_3d
        was_locked = bool(getattr(rv, "lock_rotation", False))
        if was_locked:
            rv.lock_rotation = False
        try:
            with context.temp_override(area=area, region=region):
                a = self.action
                if a == 'TOP':
                    bpy.ops.view3d.view_axis(type='TOP', align_active=False)
                elif a == 'BOTTOM':
                    bpy.ops.view3d.view_axis(type='BOTTOM', align_active=False)
                elif a == 'ORBITLEFT':
                    bpy.ops.view3d.view_orbit(angle=radians(90), type='ORBITLEFT')
                elif a == 'ORBITRIGHT':
                    bpy.ops.view3d.view_orbit(angle=radians(90), type='ORBITRIGHT')
                elif a == 'ORBITUP':
                    bpy.ops.view3d.view_orbit(angle=radians(90), type='ORBITUP')
                elif a == 'ORBITDOWN':
                    bpy.ops.view3d.view_orbit(angle=radians(90), type='ORBITDOWN')
                elif a == 'ROLLLEFT':
                    bpy.ops.view3d.view_roll(angle=radians(90), type='ANGLE')
                elif a == 'ROLLRIGHT':
                    bpy.ops.view3d.view_roll(angle=radians(-90), type='ANGLE')
        except Exception as e:
            self.report({'WARNING'}, "View change failed: %s" % e)
        finally:
            if was_locked:
                rv.lock_rotation = True
        area.tag_redraw()
        return {'FINISHED'}


# ------------------------------------------------------------------ navigate
def _do_pan(context, rv3d, region, dx, dy):
    """RTS pan: ground-slide along world XY when tilted/perspective; in-plane pan
    when in an ortho view (so top plans and elevations still pan correctly)."""
    prefs = get_prefs(context)
    ix = -1.0 if (prefs and prefs.rts_invert_x) else 1.0
    iy = -1.0 if (prefs and prefs.rts_invert_y) else 1.0
    rot = rv3d.view_rotation
    right = rot @ Vector((1.0, 0.0, 0.0))
    up = rot @ Vector((0.0, 1.0, 0.0))
    fwd = rot @ Vector((0.0, 0.0, -1.0))
    h = max(getattr(region, "height", 1000), 1)
    scale = rv3d.view_distance / h
    if rv3d.is_perspective:
        gr = Vector((right.x, right.y, 0.0))
        gr = gr.normalized() if gr.length > 1e-6 else Vector((1.0, 0.0, 0.0))
        gf = Vector((fwd.x, fwd.y, 0.0))
        if gf.length < 1e-4:
            gf = Vector((up.x, up.y, 0.0))
            gf = gf.normalized() if gf.length > 1e-6 else Vector((0.0, 1.0, 0.0))
        else:
            gf = gf.normalized()
        move = gr * (dx * ix * scale) + gf * (dy * iy * scale)
        loc = rv3d.view_location.copy()
        loc.x += move.x
        loc.y += move.y
        rv3d.view_location = loc
    else:
        rv3d.view_location = (rv3d.view_location
                              + right * (dx * ix * scale)
                              + up * (dy * iy * scale))


class VIEW3D_OT_floorplan_rts_pan(bpy.types.Operator):
    """RTS ground pan (two-finger). Slides across the ground when tilted"""
    bl_idname = "view3d.floorplan_rts_pan"
    bl_label = "Floorplan RTS Pan"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        sd = context.space_data
        return sd is not None and sd.type == 'VIEW_3D'

    def invoke(self, context, event):
        sd = context.space_data
        rv = sd.region_3d if sd else None
        if rv is None:
            return {'PASS_THROUGH'}
        _do_pan(context, rv, context.region,
                event.mouse_x - event.mouse_prev_x,
                event.mouse_y - event.mouse_prev_y)
        if context.area:
            context.area.tag_redraw()
        return {'FINISHED'}


class VIEW3D_OT_floorplan_look(bpy.types.Operator):
    """First-person camera look in place. Hold the configured modifier and move;
    release it to exit. Cursor is grabbed so it can't run off screen"""
    bl_idname = "view3d.floorplan_look"
    bl_label = "Floorplan Camera Look"
    bl_options = {'GRAB_CURSOR', 'BLOCKING'}

    @classmethod
    def poll(cls, context):
        sd = context.space_data
        return sd is not None and sd.type == 'VIEW_3D'

    def _mods_held(self, event):
        prefs = get_prefs(bpy.context)
        if not prefs:
            return True
        if prefs.look_ctrl and not event.ctrl:
            return False
        if prefs.look_shift and not event.shift:
            return False
        if prefs.look_alt and not event.alt:
            return False
        # require at least one modifier so a bare move doesn't trap the cursor
        if not (prefs.look_ctrl or prefs.look_shift or prefs.look_alt):
            return event.ctrl or event.shift or event.alt
        return True

    def _look(self, context, dx, dy):
        prefs = get_prefs(context)
        sens = prefs.look_sensitivity if prefs else 1.0
        ix = -1.0 if (prefs and prefs.look_invert_x) else 1.0
        iy = -1.0 if (prefs and prefs.look_invert_y) else 1.0
        base = radians(0.25)
        yaw = -dx * ix * base * sens
        pitch = -dy * iy * base * sens
        rv = self.rv3d
        rot = rv.view_rotation.copy()
        d = rv.view_distance
        old_fwd = rot @ Vector((0.0, 0.0, -1.0))
        eye = rv.view_location - old_fwd * d
        f = Quaternion(Vector((0.0, 0.0, 1.0)), yaw) @ old_fwd
        hr = f.cross(Vector((0.0, 0.0, 1.0)))
        if hr.length < 1e-6:
            hr = rot @ Vector((1.0, 0.0, 0.0))
        hr.normalize()
        f = Quaternion(hr, pitch) @ f
        f.normalize()
        z = -f
        x = Vector((0.0, 0.0, 1.0)).cross(z)
        if x.length < 1e-6:
            x = rot @ Vector((1.0, 0.0, 0.0))
        x.normalize()
        y = z.cross(x)
        y.normalize()
        rv.view_rotation = Matrix((x, y, z)).transposed().to_quaternion()
        rv.view_location = eye + f * d
        if context.area:
            context.area.tag_redraw()

    def invoke(self, context, event):
        sd = context.space_data
        if sd is None or sd.type != 'VIEW_3D':
            return {'CANCELLED'}
        self.rv3d = sd.region_3d
        self.region = context.region
        dx = event.mouse_x - event.mouse_prev_x
        dy = event.mouse_y - event.mouse_prev_y
        if dx or dy:
            self._look(context, dx, dy)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if not self._mods_held(event):
            return {'FINISHED'}
        if event.type == 'MOUSEMOVE':
            dx = event.mouse_x - event.mouse_prev_x
            dy = event.mouse_y - event.mouse_prev_y
            if dx or dy:
                self._look(context, dx, dy)
            return {'RUNNING_MODAL'}
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            return {'FINISHED'}
        return {'RUNNING_MODAL'}


# ------------------------------------------------------------------ calibrate
def _calib_draw(self):
    try:
        import gpu
        from gpu_extras.batch import batch_for_shader
    except Exception:
        return
    try:
        reg = self.region
        rv = self.rv3d

        def s(w):
            r = location_3d_to_region_2d(reg, rv, w)
            return (r.x, r.y) if r else None

        try:
            shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        except Exception:
            shader = gpu.shader.from_builtin('2D_UNIFORM_COLOR')
        gpu.state.blend_set('ALPHA')
        gpu.state.line_width_set(2.0)

        def seg(p, q, color):
            a = s(p)
            b = s(q)
            if a and b:
                batch = batch_for_shader(shader, 'LINES', {"pos": [a, b]})
                shader.bind()
                shader.uniform_float("color", color)
                batch.draw(shader)

        n = len(self.points)
        ref = (1.0, 0.6, 0.1, 1.0)   # reference line (orange)
        tgt = (0.2, 0.8, 1.0, 1.0)   # target line (blue)
        if n >= 2:
            seg(self.points[0], self.points[1], ref)
        if n >= 4:
            seg(self.points[2], self.points[3], tgt)
        if n == 1 and self.cur is not None:
            seg(self.points[0], self.cur, ref)
        if n == 3 and self.cur is not None:
            seg(self.points[2], self.cur, tgt)
        for p in self.points:
            ps = s(p)
            if ps:
                r = 7
                sq = [(ps[0]-r, ps[1]-r), (ps[0]+r, ps[1]-r),
                      (ps[0]+r, ps[1]+r), (ps[0]-r, ps[1]+r), (ps[0]-r, ps[1]-r)]
                b = batch_for_shader(shader, 'LINE_STRIP', {"pos": sq})
                shader.bind()
                shader.uniform_float("color", (1.0, 0.9, 0.1, 1.0))
                b.draw(shader)

        # live cursor crosshair so it's obvious the tool is tracking
        if self.cur is not None:
            cs = s(self.cur)
            if cs:
                r = 10
                cross = [(cs[0]-r, cs[1]), (cs[0]+r, cs[1])]
                cross2 = [(cs[0], cs[1]-r), (cs[0], cs[1]+r)]
                for line in (cross, cross2):
                    bc = batch_for_shader(shader, 'LINES', {"pos": line})
                    shader.bind()
                    shader.uniform_float("color", (1.0, 1.0, 1.0, 0.9))
                    bc.draw(shader)

        sw = getattr(self, "snap_world", None)
        if sw is not None:
            ps = s(sw)
            if ps:
                rr = 9
                ring = [(ps[0] + cos(i * pi / 8) * rr, ps[1] + sin(i * pi / 8) * rr)
                        for i in range(17)]
                bb = batch_for_shader(shader, 'LINE_STRIP', {"pos": ring})
                shader.bind()
                shader.uniform_float("color", (0.2, 1.0, 0.3, 1.0))
                bb.draw(shader)

        gpu.state.line_width_set(1.0)
        gpu.state.blend_set('NONE')
    except Exception:
        pass


class OBJECT_OT_floorplan_project_cut(bpy.types.Operator):
    """Knife-project the chosen cutter object onto the mesh you're editing"""
    bl_idname = "object.floorplan_project_cut"
    bl_label = "Project Cut"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        o = context.edit_object
        return o is not None and o.type == 'MESH'

    def execute(self, context):
        s = context.scene.floorplan_trace
        target = context.edit_object
        cutter = s.project_cutter
        if cutter is None or cutter.type not in {'MESH', 'CURVE'}:
            self.report({'WARNING'}, "Pick a mesh or curve object to project")
            return {'CANCELLED'}
        if cutter == target:
            self.report({'WARNING'}, "Cutter and target must be different objects")
            return {'CANCELLED'}
        ok, msg = _do_knife_project(context, cutter, target, s.cut_through, keep_cutter=True)
        # return to edit mode on the target
        try:
            for o in list(context.view_layer.objects.selected):
                o.select_set(False)
            target.select_set(True)
            context.view_layer.objects.active = target
            bpy.ops.object.mode_set(mode='EDIT')
        except Exception:
            pass
        if not ok:
            self.report({'WARNING'}, "Cut failed: " +
                        (msg or "knife_project found nothing to cut"))
        return {'FINISHED'}


class OBJECT_OT_floorplan_calibrate(bpy.types.Operator):
    """Scale selected objects to a known measurement.\nClick the two ends of a measured line, then type its real length"""
    bl_idname = "object.floorplan_calibrate"
    bl_label = "Calibrate Scale"

    mode: bpy.props.EnumProperty(
        items=[
            ('DIMENSION', "Type Length", "Draw one line, then type its real length"),
            ('LINE', "Fit to Line", "Draw a line on the drawing, then a matching line "
                                    "on the model; the selection moves/scales/rotates to fit"),
        ],
        default='DIMENSION',
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context):
        return context.mode == 'OBJECT' and len(context.selected_objects) > 0

    def plane_point(self, coord):
        # project onto the plane that faces the current view, through the
        # reference depth -- works for plans (top view) and elevations (front view)
        return region_2d_to_location_3d(self.region, self.rv3d, coord, self.depth_co)

    def _finish(self, context):
        if getattr(self, "_handle", None):
            try:
                bpy.types.SpaceView3D.draw_handler_remove(self._handle, 'WINDOW')
            except Exception:
                pass
            self._handle = None
        if context.area:
            context.area.header_text_set(None)
            context.area.tag_redraw()

    def _should_snap(self):
        # snap only while placing the target (second) line in LINE mode
        return self.mode == 'LINE' and len(self.points) >= 2

    def _nearest_vertex(self, coord):
        m = Vector(coord)
        best = None
        best_d = self.snap_px
        for w in self.snap_verts:
            r = location_3d_to_region_2d(self.region, self.rv3d, w)
            if r is None:
                continue
            d = (m - Vector((r.x, r.y))).length
            if d < best_d:
                best_d = d
                best = w
        return best.copy() if best is not None else None

    def get_point(self, context, coord):
        if self._should_snap():
            v = self._nearest_vertex(coord)
            if v is not None:
                return v, True
        p = self.plane_point(coord)
        return (p, False)

    def _update_header(self, context):
        if not context.area:
            return
        n = len(self.points)
        if self.mode == 'DIMENSION':
            msg = "Click the two ends of a known measurement"
        else:
            if n < 2:
                msg = "Reference line: click 2 points on the drawing"
            else:
                msg = "Target line: click 2 model vertices (snaps to verts)"
        context.area.header_text_set(msg + "  |  Esc: cancel")

    def _apply_line_fit(self, context, a0, a1, b0, b1):
        av = a1 - a0
        bv = b1 - b0
        if av.length < 1e-6 or bv.length < 1e-6:
            self.report({'WARNING'}, "A drawn line is too short")
            return
        scale = bv.length / av.length
        R = av.normalized().rotation_difference(bv.normalized()).to_matrix().to_4x4()
        M = (Matrix.Translation(b0) @ Matrix.Scale(scale, 4) @
             R @ Matrix.Translation(-a0))
        for obj in context.selected_objects:
            obj.matrix_world = M @ obj.matrix_world

    def invoke(self, context, event):
        sd = context.space_data
        if sd is None or sd.type != 'VIEW_3D':
            self.report({'WARNING'}, "Run from a 3D Viewport")
            return {'CANCELLED'}
        self.rv3d = sd.region_3d
        self.region = next((r for r in context.area.regions
                            if r.type == 'WINDOW'), None)
        if self.region is None:
            return {'CANCELLED'}
        ao = context.active_object
        if ao is not None and ao.select_get():
            self.depth_co = ao.matrix_world.translation.copy()
        else:
            self.depth_co = context.scene.cursor.location.copy()
        self.points = []
        self.cur = None
        self.snap_world = None
        self.snap_px = 14
        self.needed = 2 if self.mode == 'DIMENSION' else 4
        # precompute world-space vertices of unselected meshes for target snapping
        self.snap_verts = []
        if self.mode == 'LINE':
            sel = set(context.selected_objects)
            for obj in context.visible_objects:
                if obj.type == 'MESH' and obj not in sel and obj.data:
                    mw = obj.matrix_world
                    self.snap_verts.extend(mw @ v.co for v in obj.data.vertices)
        self._handle = bpy.types.SpaceView3D.draw_handler_add(
            _calib_draw, (self,), 'WINDOW', 'POST_PIXEL')
        self._update_header(context)
        context.window_manager.modal_handler_add(self)
        context.area.tag_redraw()
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if context.mode != 'OBJECT':
            self._finish(context)
            return {'CANCELLED'}
        if context.area:
            context.area.tag_redraw()
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE',
                          'TRACKPADPAN', 'TRACKPADZOOM'}:
            return {'PASS_THROUGH'}
        coord = (event.mouse_x - self.region.x, event.mouse_y - self.region.y)
        inside = (0 <= coord[0] <= self.region.width and
                  0 <= coord[1] <= self.region.height)
        if not inside:
            return {'PASS_THROUGH'}
        if event.type == 'MOUSEMOVE':
            w, snapped = self.get_point(context, coord)
            self.cur = w
            self.snap_world = w if snapped else None
            return {'RUNNING_MODAL'}
        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            p, snapped = self.get_point(context, coord)
            if p is not None:
                self.points.append(p.copy())
                if len(self.points) >= self.needed:
                    if self.mode == 'DIMENSION':
                        a, b = self.points[0], self.points[1]
                        measured = (b - a).length
                        self._finish(context)
                        if measured < 1e-6:
                            self.report({'WARNING'}, "Points too close together")
                            return {'CANCELLED'}
                        _pending_scale.clear()
                        _pending_scale.update(pivot=a.copy(), measured=measured)
                        bpy.app.timers.register(_launch_scale_dialog,
                                                first_interval=0.01)
                        return {'FINISHED'}
                    else:
                        a0, a1, b0, b1 = self.points[:4]
                        self._finish(context)
                        self._apply_line_fit(context, a0, a1, b0, b1)
                        return {'FINISHED'}
                self._update_header(context)
            return {'RUNNING_MODAL'}
        if event.type in {'RIGHTMOUSE', 'ESC'} and event.value == 'PRESS':
            self._finish(context)
            return {'CANCELLED'}
        return {'RUNNING_MODAL'}


class OBJECT_OT_floorplan_apply_scale(bpy.types.Operator):
    """Enter the real length of the measured line and scale the selection"""
    bl_idname = "object.floorplan_apply_scale"
    bl_label = "Set Reference Length"
    bl_options = {'REGISTER', 'UNDO'}

    pivot_x: bpy.props.FloatProperty(options={'HIDDEN'})
    pivot_y: bpy.props.FloatProperty(options={'HIDDEN'})
    pivot_z: bpy.props.FloatProperty(options={'HIDDEN'})
    measured: bpy.props.FloatProperty(options={'HIDDEN'})
    length: bpy.props.FloatProperty(
        name="Real Length", subtype='DISTANCE', unit='LENGTH', min=0.0, default=0.0,
        description="Actual length this line represents (type units like 12ft, 5cm, 2\")")

    def invoke(self, context, event):
        piv = _pending_scale.get('pivot')
        if piv is not None:
            self.pivot_x, self.pivot_y, self.pivot_z = piv.x, piv.y, piv.z
            self.measured = _pending_scale.get('measured', 0.0)
        if self.measured <= 1e-9:
            self.report({'WARNING'}, "Measured line is too short")
            return {'CANCELLED'}
        if self.length <= 0.0:
            self.length = self.measured
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        col = self.layout.column()
        col.prop(self, "length")
        col.label(text="Measured: %.4g BU" % self.measured)

    def execute(self, context):
        if self.measured <= 1e-9 or self.length <= 0.0:
            return {'CANCELLED'}
        factor = self.length / self.measured
        piv = Vector((self.pivot_x, self.pivot_y, self.pivot_z))
        scene = context.scene
        area = next((a for a in context.window.screen.areas
                     if a.type == 'VIEW_3D'), None)
        region = None
        if area:
            region = next((r for r in area.regions if r.type == 'WINDOW'), None)
        saved_cursor = scene.cursor.location.copy()
        saved_pivot = scene.tool_settings.transform_pivot_point
        scene.cursor.location = piv
        scene.tool_settings.transform_pivot_point = 'CURSOR'
        try:
            if area and region:
                with context.temp_override(area=area, region=region):
                    bpy.ops.transform.resize(value=(factor, factor, factor),
                                             orient_type='GLOBAL')
            else:
                bpy.ops.transform.resize(value=(factor, factor, factor),
                                         orient_type='GLOBAL')
        except Exception as e:
            self.report({'WARNING'}, "Scale failed: %s" % e)
        finally:
            scene.tool_settings.transform_pivot_point = saved_pivot
            scene.cursor.location = saved_cursor
        return {'FINISHED'}


# ------------------------------------------------------------------ panel
class VIEW3D_PT_floorplan_trace(bpy.types.Panel):
    bl_label = "Floorplan Trace"
    bl_idname = "VIEW3D_PT_floorplan_trace"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Trace"

    def draw(self, context):
        layout = self.layout
        wm = context.window_manager
        s = context.scene.floorplan_trace

        col = layout.column()
        in_edit = context.edit_object and context.edit_object.type == 'MESH'
        if in_edit or context.mode == 'OBJECT':
            col.scale_y = 1.4
            col.operator("mesh.floorplan_trace",
                         text="Tracing ON" if wm.floorplan_trace_active else "Trace",
                         depress=wm.floorplan_trace_active, icon='GREASEPENCIL').cut_mode = False
            layout.label(text="Right-click button to assign a shortcut", icon='INFO')
            if not in_edit:
                layout.label(text="Object Mode: starts a new object", icon='ADD')
        else:
            col.label(text="Enter Object or Edit Mode", icon='INFO')

        # Cut tools (only while editing a mesh)
        if in_edit:
            cut = layout.box()
            cut.label(text="Cut Into This Mesh", icon='MOD_BOOLEAN')
            c = cut.column()
            c.scale_y = 1.3
            c.operator("mesh.floorplan_trace", text="Cut Trace",
                       icon='GREASEPENCIL').cut_mode = True
            cut.prop(s, "cut_through")
            row = cut.row(align=True)
            row.prop(s, "project_cutter", text="")
            row.operator("object.floorplan_project_cut", text="Project Cut")

        rv = context.space_data.region_3d if context.space_data else None
        if rv is not None and hasattr(rv, "lock_rotation"):
            layout.operator("view3d.floorplan_toggle_lock",
                            text="View Rotation Locked" if rv.lock_rotation
                            else "Lock View Rotation",
                            icon='LOCKED' if rv.lock_rotation else 'UNLOCKED',
                            depress=rv.lock_rotation)
            sub = layout.row()
            sub.enabled = rv.lock_rotation
            sub.prop(s, "mmb_pan_when_locked", text="Middle-mouse / two-finger pans when locked")

        nav = layout.box()
        nav.label(text="Ortho Views")
        grid = nav.column(align=True)
        # up (pitch up toward top)
        r = grid.row(align=True)
        r.label(text="")
        r.operator("view3d.floorplan_view", text="", icon='TRIA_UP').action = 'ORBITUP'
        r.label(text="")
        # left / right (orbit to next side)
        r = grid.row(align=True)
        r.operator("view3d.floorplan_view", text="", icon='TRIA_LEFT').action = 'ORBITLEFT'
        r.label(text="")
        r.operator("view3d.floorplan_view", text="", icon='TRIA_RIGHT').action = 'ORBITRIGHT'
        # down (pitch down toward bottom)
        r = grid.row(align=True)
        r.label(text="")
        r.operator("view3d.floorplan_view", text="", icon='TRIA_DOWN').action = 'ORBITDOWN'
        r.label(text="")
        # roll
        grid.separator()
        r = grid.row(align=True)
        r.operator("view3d.floorplan_view", text="Roll", icon='LOOP_BACK').action = 'ROLLLEFT'
        r.operator("view3d.floorplan_view", text="Roll", icon='LOOP_FORWARDS').action = 'ROLLRIGHT'

        cal = layout.box()
        cal.label(text="Reference Scale")
        if context.mode == 'OBJECT' and len(context.selected_objects) > 0:
            col = cal.column(align=True)
            col.operator("object.floorplan_calibrate",
                         text="Type Length", icon='DRIVER_DISTANCE').mode = 'DIMENSION'
            col.operator("object.floorplan_calibrate",
                         text="Fit to Line", icon='ARROW_LEFTRIGHT').mode = 'LINE'
        else:
            cal.label(text="Select object(s) in Object Mode", icon='INFO')

        box = layout.box()
        box.label(text="Angle")
        box.prop(s, "use_angle_snap")
        r = box.column()
        r.enabled = s.use_angle_snap
        r.prop(s, "angle_increment")
        r.prop(s, "angle_tolerance")
        r.prop(s, "use_relative_angle")

        box = layout.box()
        box.label(text="Alignment")
        box.prop(s, "use_alignment")
        sub = box.column()
        sub.enabled = s.use_alignment
        sub.prop(s, "snap_scope", text="")
        sub.prop(s, "align_px")
        box.prop(s, "close_px")

        box = layout.box()
        box.label(text="Inference")
        box.prop(s, "use_extension")
        box.prop(s, "use_distance_memory")
        row = box.row()
        row.enabled = s.use_distance_memory
        row.prop(s, "dist_px")

        box = layout.box()
        box.label(text="Grid")
        box.prop(s, "use_grid")
        row = box.row()
        row.enabled = s.use_grid
        row.prop(s, "grid_size")


# ------------------------------------------------------------------ register
classes = (
    FT_Prefs,
    FT_Settings,
    MESH_OT_floorplan_trace,
    VIEW3D_OT_floorplan_toggle_lock,
    VIEW3D_OT_floorplan_view,
    VIEW3D_OT_floorplan_rts_pan,
    VIEW3D_OT_floorplan_look,
    OBJECT_OT_floorplan_project_cut,
    OBJECT_OT_floorplan_calibrate,
    OBJECT_OT_floorplan_apply_scale,
    VIEW3D_PT_floorplan_trace,
)


def _build_nav_keymaps():
    kc = bpy.context.window_manager.keyconfigs.addon
    if not kc:
        return
    prefs = get_prefs(bpy.context)
    if not prefs or not prefs.custom_nav:
        return
    km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')

    def add(idname, etype, ctrl, shift, alt):
        kmi = km.keymap_items.new(idname, etype, 'ANY',
                                  ctrl=ctrl, shift=shift, alt=alt)
        _nav_kmis.append((km, kmi))

    add('view3d.move', 'TRACKPADPAN', prefs.pan_ctrl, prefs.pan_shift, prefs.pan_alt)
    add('view3d.rotate', 'TRACKPADPAN', prefs.orbit_ctrl, prefs.orbit_shift, prefs.orbit_alt)
    add('view3d.floorplan_rts_pan', 'TRACKPADPAN', prefs.rts_ctrl, prefs.rts_shift, prefs.rts_alt)
    add('view3d.floorplan_look', 'MOUSEMOVE', prefs.look_ctrl, prefs.look_shift, prefs.look_alt)


def _clear_nav_keymaps():
    for km, kmi in _nav_kmis:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _nav_kmis.clear()


def _refresh_nav():
    _clear_nav_keymaps()
    _build_nav_keymaps()


def _register_keymaps():
    kc = bpy.context.window_manager.keyconfigs.addon
    if not kc:
        return
    km = kc.keymaps.new(name='3D View', space_type='VIEW_3D')
    # native pan while the view is locked; two-finger + middle-mouse, toggled by lock
    for etype, evalue in (('TRACKPADPAN', 'ANY'), ('MIDDLEMOUSE', 'PRESS')):
        kmi = km.keymap_items.new('view3d.move', etype, evalue)
        kmi.active = False
        _addon_keymaps.append((km, kmi))
        _pan_kmis.append(kmi)
    # configurable two-finger pan / orbit / zoom and one-finger look
    _build_nav_keymaps()


def _unregister_keymaps():
    _clear_nav_keymaps()
    for km, kmi in _addon_keymaps:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _addon_keymaps.clear()
    _pan_kmis.clear()


@persistent
def _on_load(_dummy):
    _subscribe_msgbus()
    _resync_pan()


def _subscribe_msgbus():
    try:
        bpy.msgbus.clear_by_owner(_msgbus_owner)
        bpy.msgbus.subscribe_rna(
            key=(bpy.types.RegionView3D, "lock_rotation"),
            owner=_msgbus_owner,
            args=(),
            notify=_resync_pan,
        )
    except Exception:
        pass


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Scene.floorplan_trace = bpy.props.PointerProperty(type=FT_Settings)
    bpy.types.WindowManager.floorplan_trace_active = bpy.props.BoolProperty(default=False)
    _register_keymaps()
    _subscribe_msgbus()
    if _on_load not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load)


def unregister():
    global _stop_request
    _stop_request = True
    try:
        bpy.msgbus.clear_by_owner(_msgbus_owner)
    except Exception:
        pass
    if _on_load in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load)
    _unregister_keymaps()
    del bpy.types.WindowManager.floorplan_trace_active
    del bpy.types.Scene.floorplan_trace
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
