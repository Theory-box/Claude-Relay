# ============================================================
# CAMERA ENTITY PATCH — scratch/camera_patch.py
# ============================================================
# This file documents every change needed to opengoal_tools.py
# to add fixed camera placement + optional trigger volume linking.
#
# CHANGES SUMMARY:
#   1. collect_cameras(scene)          — new export function
#   2. write_jsonc(...)                — add cameras kwarg
#   3. _bg_build(...)                  — call collect_cameras
#   4. OG_OT_SpawnCamera               — new operator
#   5. OG_OT_LinkCameraVolume          — new operator
#   6. OG_OT_UnlinkCameraVolume        — new operator
#   7. OG_PT_Camera                    — new panel (mirrors NavMesh panel)
#   8. PlaceObjects panel draw()       — add "Add Camera" button
#   9. classes tuple                   — register new classes
#
# HOW IT WORKS:
#   - Camera actor: EMPTY named  CAMERA_<uid>  (type=ARROWS, distinct look)
#   - Volume mesh:  MESH  named  CAMVOL_<uid>  (any convex box the user makes)
#   - Link stored as:  camera_empty["og_camvol_link"] = vol_mesh.name
#
# EXPORT LOGIC:
#   - Camera with NO linked volume:
#       entity-camera with just trans + rot lump tags → always active
#   - Camera WITH linked volume:
#       entity-camera with trans + rot + vol lump tags → active only inside vol
#
# COORDINATE SYSTEM:
#   Blender → OpenGOAL:  x=x, y=z, z=-y  (same as all other actor exports)
#   Rotation: Blender camera points -Z local; OpenGOAL cam-fixed reads a
#   quaternion from the entity's quat field.  We export the object's world
#   quaternion directly after flipping the Y/Z axes.
# ============================================================

import bpy, mathutils, math, json
from mathutils import Matrix, Quaternion, Vector

# ────────────────────────────────────────────────────────────
# 1.  collect_cameras(scene)
# ────────────────────────────────────────────────────────────
# Add this function near collect_actors / collect_ambients.

def collect_cameras(scene):
    """
    Build entity-camera actor list from CAMERA_ empties.

    If the camera has an og_camvol_link pointing to a mesh object, the
    mesh's bounding box corners are exported as a 'vol' polygon lump so the
    engine only activates the camera when Jak enters that box.

    If there is no linked volume, no vol/pvol tags are written and the engine
    treats the camera as always-active (verified in cam-master.gc lines 490-506).
    """
    out = []
    cam_objects = [o for o in scene.objects
                   if o.name.startswith("CAMERA_") and o.type == "EMPTY"]
    for idx, o in enumerate(cam_objects):
        l = o.location
        # Blender → OpenGOAL coordinate flip (same as actors)
        gx = round(l.x, 4)
        gy = round(l.z, 4)
        gz = round(-l.y, 4)

        # ── Rotation ──────────────────────────────────────────────────────────
        # Blender camera: -Z is forward, Y is up.
        # We export the world quaternion with Y/Z axes swapped to match GOAL.
        # cam-fixed-read-entity reads this via cam-slave-get-rot which uses
        # the entity's 'quat' field (stored in entity-actor base).
        #
        # Blender world matrix → swap Y and Z columns/rows:
        wm = o.matrix_world
        # Build a coord-flip matrix: x→x, y→z, z→-y
        flip = Matrix((
            (1,  0,  0,  0),
            (0,  0,  1,  0),
            (0, -1,  0,  0),
            (0,  0,  0,  1),
        ))
        rot_mat = (flip @ wm).to_3x3().normalized()
        q = rot_mat.to_quaternion()
        # GOAL quaternion order: x y z w  (same as Blender)
        qx, qy, qz, qw = round(q.x,6), round(q.y,6), round(q.z,6), round(q.w,6)

        lump = {
            "name": o.name.lower().replace("_", "-"),
        }

        # ── Trigger volume ────────────────────────────────────────────────────
        vol_name = o.get("og_camvol_link", "")
        vol_obj  = bpy.data.objects.get(vol_name) if vol_name else None

        if vol_obj and vol_obj.type == "MESH":
            # Export the 8 corners of the volume mesh's bounding box
            # as the 'vol' polygon lump.  The engine's in-cam-entity-volume?
            # function checks whether target-pos is inside this convex hull.
            #
            # Format: ["vector", x1,y1,z1,w1,  x2,y2,z2,w2, ...]
            # w component is unused by vol (set to 1.0 per convention).
            corners = []
            for corner in vol_obj.bound_box:   # 8 local corners
                world_pt = vol_obj.matrix_world @ Vector(corner)
                cx = round(world_pt.x, 4)
                cy = round(world_pt.z, 4)
                cz = round(-world_pt.y, 4)
                corners += [cx, cy, cz, 1.0]
            lump["vol"] = ["vector"] + corners

        actor = {
            "trans":     [gx, gy, gz],
            "etype":     "entity-camera",
            "game_task": "(game-task none)",
            "quat":      [qx, qy, qz, qw],
            "vis_id":    0,
            "bsphere":   [gx, gy, gz, 30.0],   # 30 m — large enough to not cull
            "lump": lump,
        }
        out.append(actor)
    return out


# ────────────────────────────────────────────────────────────
# 2.  write_jsonc — add cameras parameter
# ────────────────────────────────────────────────────────────
# CHANGE:  def write_jsonc(name, actors, ambients, base_id=10000):
# TO:      def write_jsonc(name, actors, ambients, cameras=None, base_id=10000):
# AND inside the data dict, merge cameras into actors:
#
#   all_actors = list(actors) + (cameras or [])
#   data = { ..., "actors": all_actors, ... }
#
# entity-camera entries live in the same "actors" array as everything else.


# ────────────────────────────────────────────────────────────
# 3.  _bg_build — call collect_cameras
# ────────────────────────────────────────────────────────────
# ADD after:  actors = collect_actors(scene)
#
#   cameras = collect_cameras(scene)
#
# AND pass to write_jsonc:
#
#   write_jsonc(name, actors, ambients, cameras=cameras, base_id=base_id)


# ────────────────────────────────────────────────────────────
# 4.  OG_OT_SpawnCamera  (new operator)
# ────────────────────────────────────────────────────────────

class OG_OT_SpawnCamera(bpy.types.Operator):
    """Place a fixed camera entity at the 3D cursor."""
    bl_idname = "og.spawn_camera"
    bl_label  = "Add Camera"
    bl_description = "Place a fixed entity-camera at the 3D cursor"

    def execute(self, ctx):
        n = len([o for o in ctx.scene.objects if o.name.startswith("CAMERA_")])
        bpy.ops.object.empty_add(type="ARROWS", location=ctx.scene.cursor.location)
        o = ctx.active_object
        o.name = f"CAMERA_{n}"
        o.show_name  = True
        o.empty_display_size = 0.8
        # Distinct teal colour so cameras stand out from actors
        o.color = (0.0, 0.8, 0.9, 1.0)
        self.report({"INFO"},
            f"Added {o.name}  —  rotate to aim. "
            f"Blender -Z axis = camera forward direction.")
        return {"FINISHED"}


# ────────────────────────────────────────────────────────────
# 5.  OG_OT_LinkCameraVolume  (new operator)
# ────────────────────────────────────────────────────────────

class OG_OT_LinkCameraVolume(bpy.types.Operator):
    """Link a trigger volume mesh to the selected camera."""
    bl_idname = "og.link_camera_volume"
    bl_label  = "Link Trigger Volume"
    bl_description = (
        "Select a camera EMPTY + a volume MESH (any order), then click. "
        "The camera activates only when Jak enters the volume."
    )

    def execute(self, ctx):
        selected = ctx.selected_objects
        meshes   = [o for o in selected if o.type == "MESH"]
        cameras  = [o for o in selected if o.name.startswith("CAMERA_")
                    and o.type == "EMPTY"]

        if not cameras:
            self.report({"ERROR"}, "No camera selected — select a CAMERA_ empty too")
            return {"CANCELLED"}
        if not meshes:
            self.report({"ERROR"}, "No mesh selected — select a volume mesh too")
            return {"CANCELLED"}
        if len(meshes) > 1:
            self.report({"ERROR"}, "Multiple meshes selected — select only one volume")
            return {"CANCELLED"}

        vol = meshes[0]
        # Rename mesh with CAMVOL_ prefix if not already
        if not vol.name.startswith("CAMVOL_"):
            vol.name = "CAMVOL_" + vol.name

        for cam in cameras:
            cam["og_camvol_link"] = vol.name

        self.report({"INFO"},
            f"Linked {len(cameras)} camera(s) → volume '{vol.name}'")
        return {"FINISHED"}


# ────────────────────────────────────────────────────────────
# 6.  OG_OT_UnlinkCameraVolume  (new operator)
# ────────────────────────────────────────────────────────────

class OG_OT_UnlinkCameraVolume(bpy.types.Operator):
    """Remove trigger volume link from selected camera(s)."""
    bl_idname = "og.unlink_camera_volume"
    bl_label  = "Unlink Volume"
    bl_description = "Remove trigger volume from selected camera(s) — camera becomes always-active"

    def execute(self, ctx):
        count = 0
        for o in ctx.selected_objects:
            if o.name.startswith("CAMERA_") and "og_camvol_link" in o:
                del o["og_camvol_link"]
                count += 1
        self.report({"INFO"}, f"Unlinked {count} camera(s)")
        return {"FINISHED"}


# ────────────────────────────────────────────────────────────
# 7.  OG_PT_Camera  (new panel)
# ────────────────────────────────────────────────────────────

class OG_PT_Camera(bpy.types.Panel):
    bl_label       = "📷  Camera Settings"
    bl_idname      = "OG_PT_camera"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, ctx):
        """Show when a CAMERA_ empty or a CAMVOL_ mesh is selected."""
        sel = ctx.active_object
        if not sel:
            return False
        if sel.name.startswith("CAMERA_") and sel.type == "EMPTY":
            return True
        if sel.name.startswith("CAMVOL_") and sel.type == "MESH":
            return True
        return False

    def draw(self, ctx):
        layout = self.layout
        sel    = ctx.active_object

        # ── Camera empty selected ─────────────────────────────────────────────
        if sel.name.startswith("CAMERA_") and sel.type == "EMPTY":
            layout.label(text=sel.name, icon="CAMERA_DATA")

            vol_name = sel.get("og_camvol_link", "")
            vol_obj  = bpy.data.objects.get(vol_name) if vol_name else None

            # Status box
            box = layout.box()
            if vol_obj:
                box.label(text="✓ Trigger volume linked", icon="CHECKMARK")
                row = box.row(align=True)
                row.label(text=vol_obj.name, icon="MESH_CUBE")
                row.operator("og.unlink_camera_volume", text="", icon="X")
                box.label(text="Camera activates when Jak enters volume")
            else:
                box.label(text="No trigger volume", icon="INFO")
                box.label(text="Camera is always active")

            layout.separator()

            # Link instructions + button
            if vol_obj:
                layout.operator("og.unlink_camera_volume",
                                text="Unlink Volume", icon="UNLINKED")
            else:
                box2 = layout.box()
                box2.label(text="To add a trigger volume:", icon="INFO")
                box2.label(text="1. Make a mesh box in your scene")
                box2.label(text="2. Select: camera + box (shift-click)")
                box2.label(text="3. Click Link below")
                layout.operator("og.link_camera_volume",
                                text="Link Trigger Volume", icon="LINKED")

            layout.separator()
            # Aim reminder
            hint = layout.box()
            hint.label(text="Aim tip:", icon="QUESTION")
            hint.label(text="Camera -Z axis = look direction")
            hint.label(text="Rotate in Blender to aim the view")

        # ── Volume mesh selected ──────────────────────────────────────────────
        elif sel.name.startswith("CAMVOL_") and sel.type == "MESH":
            layout.label(text=sel.name, icon="MESH_CUBE")
            linked_cams = [o for o in bpy.data.objects
                           if o.get("og_camvol_link") == sel.name
                           and o.name.startswith("CAMERA_")]
            box = layout.box()
            if linked_cams:
                box.label(text=f"{len(linked_cams)} camera(s) linked to this volume:")
                for cam in linked_cams:
                    box.label(text=f"  {cam.name}", icon="CAMERA_DATA")
            else:
                box.label(text="No cameras linked to this volume", icon="ERROR")
                box.label(text="Select a camera + this mesh,")
                box.label(text="then click Link Trigger Volume")
            layout.operator("og.link_camera_volume",
                            text="Link Trigger Volume", icon="LINKED")


# ────────────────────────────────────────────────────────────
# 8.  PlaceObjects panel — add "Add Camera" button
# ────────────────────────────────────────────────────────────
# In OG_PT_PlaceObjects.draw(), after the existing entity/spawn buttons, add:
#
#   layout.separator()
#   layout.label(text="Camera:", icon="CAMERA_DATA")
#   layout.operator("og.spawn_camera", icon="CAMERA_DATA")
#
# (exact location: end of the draw() method, before any return)


# ────────────────────────────────────────────────────────────
# 9.  classes tuple — add new classes
# ────────────────────────────────────────────────────────────
# ADD to classes tuple:
#   OG_OT_SpawnCamera,
#   OG_OT_LinkCameraVolume,
#   OG_OT_UnlinkCameraVolume,
#   OG_PT_Camera,


# ────────────────────────────────────────────────────────────
# NOTES ON ROTATION
# ────────────────────────────────────────────────────────────
# cam-fixed-read-entity calls cam-slave-get-rot which reads the entity
# quaternion from (-> cam-entity quat) — the base entity-actor field.
# The JSONC "quat" field maps directly to this.
#
# Blender's ARROWS empty: +Y local = "up", -Z local = "forward" (matches camera).
# The coordinate flip (x→x, y→z, z→-y) is the same used for all actor positions.
# Applying the same flip to the rotation matrix before converting to quaternion
# should give correct in-game orientation.
#
# If the camera aims wrong in-game, the fix is to apply an additional
# 90° rotation around X before the flip — easy to tune without touching anything else.
