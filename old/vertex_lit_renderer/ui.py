import bpy

ENGINE_ID = 'VERTEX_LIT'

# Modules whose panels gate visibility on COMPAT_ENGINES. We extend each
# panel's COMPAT_ENGINES to include ours so Cycles/EEVEE-hidden settings
# (like the light power slider, sun angle, light color, soft size, etc.)
# show when our engine is active.
_COMPAT_MODULES = (
    'properties_data_light',
    'properties_data_mesh',
    'properties_material',
    'properties_world',
)


def _compat_engines_add(register=True):
    """Iterate bl_ui properties modules and add/remove our engine id to each
    panel's COMPAT_ENGINES. Panels that only compat with EEVEE/Cycles become
    visible (or hidden, on unregister) under our engine."""
    import importlib
    for mod_name in _COMPAT_MODULES:
        try:
            mod = importlib.import_module(f'bl_ui.{mod_name}')
        except Exception:
            continue
        for attr in dir(mod):
            cls = getattr(mod, attr, None)
            compat = getattr(cls, 'COMPAT_ENGINES', None)
            if compat is None: continue
            # Only touch panels that compat with at least one known
            # render engine — avoids accidentally exposing unrelated UI.
            if not (compat & {'BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT', 'CYCLES'}):
                continue
            if register:
                compat.add(ENGINE_ID)
            else:
                compat.discard(ENGINE_ID)


class VERTEX_LIT_PT_settings(bpy.types.Panel):
    bl_label='Vertex Lit Settings'; bl_idname='VERTEX_LIT_PT_settings'
    bl_space_type='PROPERTIES'; bl_region_type='WINDOW'; bl_context='render'

    @classmethod
    def poll(cls, context):
        return context.scene.render.engine == ENGINE_ID

    def draw(self, context):
        layout = self.layout
        s = context.scene.vertex_lit
        # Backend status indicator
        from . import gi as _gi
        if _gi._EMBREE_READY:
            layout.label(text="Backend: Intel Embree", icon='CHECKMARK')
        elif _gi._EMBREE_CHECKED:
            layout.label(text="Backend: BVHTree (embreex unavailable)", icon='ERROR')
        else:
            layout.label(text="Backend: BVHTree", icon='INFO')

        box = layout.box()
        row = box.row()
        row.label(text="GI Bounce (BVH ray cast)", icon='SHADERFX')
        row.prop(s, 'use_gi', text="")
        if s.use_gi:
            col = box.column(align=True)
            col.prop(s, 'gi_samples')
            col.prop(s, 'gi_rays_per_pass')
            from . import gi as _gi
            if not _gi._EMBREE_READY:
                col.prop(s, 'gi_thread_pause')
            col.prop(s, 'gi_bounce_strength')
            box.label(text="Recomputed when mesh/lights change", icon='INFO')

        box = layout.box()
        box.label(text="Hemisphere Fill", icon='LIGHT_HEMI')
        row = box.row(align=True)
        row.prop(s, 'sky_color', text="Sky")
        row.prop(s, 'ground_color', text="Ground")

        box = layout.box()
        header = box.row()
        header.label(text="Denoise", icon='MOD_SMOOTH')
        header.prop(s, 'use_denoise', text="")
        sub = box.column()
        sub.enabled = bool(s.use_denoise)
        sub.prop(s, 'denoise_strength', slider=True)
        if s.use_denoise:
            box.label(text="Fades out as scene converges", icon='INFO')

        box = layout.box()
        box.label(text="Lights", icon='LIGHT')
        box.prop(s, 'energy_scale')

        box = layout.box()
        box.label(text="Bake", icon='RENDER_STILL')
        col = box.column(align=True)
        row = col.row(align=True)
        row.operator('vertex_lit.bake_to_vertex_colors',
                     text="Bake All", icon='VPAINT_HLT').selected_only = False
        row.operator('vertex_lit.bake_to_vertex_colors',
                     text="Bake Selected", icon='VPAINT_HLT').selected_only = True
        row = col.row(align=True)
        row.operator('vertex_lit.clear_baked_vertex_colors',
                     text="Clear All", icon='X').selected_only = False
        row.operator('vertex_lit.clear_baked_vertex_colors',
                     text="Clear Selected", icon='X').selected_only = True
        box.label(text="Writes 'VertexLit_Baked' color attribute", icon='INFO')



class VERTEX_LIT_PT_object(bpy.types.Panel):
    bl_label       = 'Vertex Lit'
    bl_idname      = 'VERTEX_LIT_PT_object'
    bl_space_type  = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context     = 'object'

    @classmethod
    def poll(cls, context):
        return context.scene.render.engine == ENGINE_ID and context.object is not None

    def draw(self, context):
        self.layout.prop(context.object, 'vertex_lit_cast_shadow', icon='SHADING_RENDERED')

def register():
    bpy.utils.register_class(VERTEX_LIT_PT_settings)
    bpy.utils.register_class(VERTEX_LIT_PT_object)
    _compat_engines_add(register=True)

def unregister():
    _compat_engines_add(register=False)
    bpy.utils.unregister_class(VERTEX_LIT_PT_object)
    bpy.utils.unregister_class(VERTEX_LIT_PT_settings)
