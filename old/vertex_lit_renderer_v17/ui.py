import bpy

class VERTEX_LIT_PT_settings(bpy.types.Panel):
    bl_label='Vertex Lit Settings'; bl_idname='VERTEX_LIT_PT_settings'
    bl_space_type='PROPERTIES'; bl_region_type='WINDOW'; bl_context='render'

    @classmethod
    def poll(cls, context):
        return context.scene.render.engine == 'VERTEX_LIT'

    def draw(self, context):
        layout = self.layout
        s = context.scene.vertex_lit

        box = layout.box()
        row = box.row()
        row.label(text="GI Bounce (BVH ray cast)", icon='SHADERFX')
        row.prop(s, 'use_gi', text="")
        if s.use_gi:
            col = box.column(align=True)
            col.prop(s, 'gi_samples')
            col.prop(s, 'gi_bounce_strength')
            box.label(text="Recomputed when mesh/lights change", icon='INFO')

        box = layout.box()
        box.label(text="Hemisphere Fill", icon='LIGHT_HEMI')
        row = box.row(align=True)
        row.prop(s, 'sky_color', text="Sky")
        row.prop(s, 'ground_color', text="Ground")

        box = layout.box()
        box.label(text="Lights", icon='LIGHT')
        box.prop(s, 'energy_scale')

        box = layout.box()
        row = box.row()
        row.label(text="Shadows", icon='SHADING_RENDERED')
        row.prop(s, 'use_shadows', text="")
        if s.use_shadows:
            col = box.column(align=True)
            col.prop(s, 'shadow_resolution')
            col.prop(s, 'shadow_bias')
            col.prop(s, 'shadow_darkness')

def register():
    bpy.utils.register_class(VERTEX_LIT_PT_settings)

def unregister():
    bpy.utils.unregister_class(VERTEX_LIT_PT_settings)
