import bpy
import numpy as np


class VERTEX_LIT_OT_bake_to_vertex_colors(bpy.types.Operator):
    """Bake the current GI state (per-vertex lighting) into a color attribute
    named 'VertexLit_Baked'. Writes the shadow-tested direct + indirect
    lighting (same values the render view is using right now). Does NOT
    include base albedo or textures — those stay in the material so you can
    multiply them against this attribute downstream. Useful for exporting
    to game engines, switching to another render engine without re-lighting,
    or using the scene with Blender's workbench / Eevee with a simple
    'Color Attribute' material"""

    bl_idname = "vertex_lit.bake_to_vertex_colors"
    bl_label  = "Bake GI to Vertex Colors"
    bl_options = {'REGISTER', 'UNDO'}

    attribute_name: bpy.props.StringProperty(
        name="Attribute Name",
        default="VertexLit_Baked",
        description="Name of the color attribute to write. Replaces any "
                    "existing attribute with this name.",
    )
    selected_only: bpy.props.BoolProperty(
        name="Selected Only",
        default=False,
        description="Bake only the selected mesh objects. Off = every mesh "
                    "in the scene that has current GI data.",
    )
    include_alpha: bpy.props.BoolProperty(
        name="Alpha = 1",
        default=True,
        description="Set alpha channel to 1.0. Off = leave alpha as "
                    "whatever came out of the lighting computation (usually "
                    "meaningless for GI — keep this on unless you have a "
                    "specific reason).",
    )

    @classmethod
    def poll(cls, context):
        # Need GI to be initialized. Don't require render view to be active —
        # user might have left view but accum is still present.
        from . import engine as _e
        return _e._global_gi is not None

    def execute(self, context):
        from . import engine as _e
        gi = _e._global_gi
        if gi is None:
            self.report({'ERROR'}, "GI not initialized")
            return {'CANCELLED'}

        # Snapshot the accumulator under the lock — very short critical
        # section, just dict copy references (numpy .copy() is C-level).
        with gi._lock:
            count = gi._count
            accum_snap = {name: arr.copy() for name, arr in gi._accum.items()}

        if count <= 0 or not accum_snap:
            self.report({'ERROR'}, "No GI data available yet — enter render "
                                   "view and wait a few passes first.")
            return {'CANCELLED'}

        scene = context.scene
        vls   = getattr(scene, 'vertex_lit', None)
        bounce_str = float(getattr(vls, 'gi_bounce_strength', 1.0))

        # Which objects to bake into
        if self.selected_only:
            targets = [o for o in context.selected_objects if o.type == 'MESH']
            if not targets:
                self.report({'ERROR'}, "No mesh objects selected.")
                return {'CANCELLED'}
        else:
            targets = [o for o in scene.objects if o.type == 'MESH']

        n_baked   = 0
        n_skipped = 0
        for obj in targets:
            accum = accum_snap.get(obj.name)
            if accum is None:
                n_skipped += 1
                continue

            mesh = obj.data
            n_verts = len(mesh.vertices)
            if accum.shape[0] != n_verts:
                # Mesh changed since GI was computed. Happens if user edited
                # topology after the last rebuild.
                n_skipped += 1
                continue

            # Per-vertex lit value
            lit = (accum / max(count, 1)) * bounce_str   # (n_verts, 3)

            # Build flat RGBA float32 buffer
            flat = np.empty(n_verts * 4, dtype=np.float32)
            flat[0::4] = lit[:, 0]
            flat[1::4] = lit[:, 1]
            flat[2::4] = lit[:, 2]
            flat[3::4] = 1.0 if self.include_alpha else 0.0

            # Replace any existing attribute with the same name
            existing = mesh.color_attributes.get(self.attribute_name)
            if existing is not None:
                mesh.color_attributes.remove(existing)
            attr = mesh.color_attributes.new(
                name=self.attribute_name,
                type='FLOAT_COLOR',
                domain='POINT',
            )
            attr.data.foreach_set('color', flat)
            mesh.update()
            n_baked += 1

        if n_baked == 0:
            self.report({'ERROR'}, f"No objects baked (skipped {n_skipped}).")
            return {'CANCELLED'}

        msg = f"Baked {n_baked} mesh{'es' if n_baked != 1 else ''} to '{self.attribute_name}'"
        if n_skipped:
            msg += f" (skipped {n_skipped} with no GI data or mismatched topology)"
        self.report({'INFO'}, msg)
        return {'FINISHED'}


def register():
    bpy.utils.register_class(VERTEX_LIT_OT_bake_to_vertex_colors)

def unregister():
    bpy.utils.unregister_class(VERTEX_LIT_OT_bake_to_vertex_colors)
