# vertex_lit_renderer/splat_ops.py
"""Operators to generate splats from the active mesh (into the in-engine SCENE_CLOUDS registry)."""
import bpy


class VERTEXLIT_OT_generate_splats(bpy.types.Operator):
    bl_idname = "vertex_lit.generate_splats"
    bl_label = "Convert to Splats"
    bl_description = "Sample the active mesh into a gaussian-splat cloud rendered in the scene"
    bl_options = {'REGISTER'}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object first"); return {'CANCELLED'}
        s = context.scene.vertex_lit
        from . import splat_gen, splat_render
        try:
            cloud, diag = splat_gen.generate(
                obj, s.splat_method, int(s.splat_count), s.splat_color,
                s.splat_size, s.splat_flatness, s.splat_opacity,
                bool(s.splat_bake), int(s.splat_seed))
        except Exception as e:
            import traceback; traceback.print_exc()
            self.report({'ERROR'}, "Generate failed: %s" % e); return {'CANCELLED'}
        if cloud is None:
            self.report({'ERROR'}, "Mesh has no faces to sample"); return {'CANCELLED'}
        print("[VertexLit] splat gen (%s) on %s:" % (s.splat_method, obj.name))
        for line in (diag or []): print("   ", line)
        splat_render.SCENE_CLOUDS.append(splat_render.SplatCloud(cloud, sigma=s.splat_sigma))
        if s.splat_hide_src:
            obj.hide_set(True)
        for a in context.screen.areas:
            if a.type == 'VIEW_3D': a.tag_redraw()
        self.report({'INFO'}, "Splatted %s: %d splats (%d cloud(s))"
                    % (obj.name, cloud['count'], len(splat_render.SCENE_CLOUDS)))
        return {'FINISHED'}


class VERTEXLIT_OT_clear_splats(bpy.types.Operator):
    bl_idname = "vertex_lit.clear_splats"
    bl_label = "Clear Splats"
    bl_description = "Remove all generated splat clouds from the scene"

    def execute(self, context):
        from . import splat_render
        splat_render.SCENE_CLOUDS.clear()
        for a in context.screen.areas:
            if a.type == 'VIEW_3D': a.tag_redraw()
        self.report({'INFO'}, "Cleared splats")
        return {'FINISHED'}


_CLASSES = (VERTEXLIT_OT_generate_splats, VERTEXLIT_OT_clear_splats)

def register():
    for c in _CLASSES: bpy.utils.register_class(c)

def unregister():
    for c in reversed(_CLASSES): bpy.utils.unregister_class(c)
