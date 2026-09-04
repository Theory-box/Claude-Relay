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
        row.label(text="Outline", icon='MOD_EDGESPLIT')
        row.prop(s, 'use_outline', text="")
        if s.use_outline:
            col = box.column(align=True)
            col.prop(s, 'outline_size')
            col.prop(s, 'outline_threshold')
            col.prop(s, 'outline_color', text="")

        box = layout.box()
        box.label(text="Shading", icon='SHADING_RENDERED')
        box.prop(s, 'shading_mode', text="")

        box = layout.box()
        row = box.row()
        row.label(text="Ambient Occlusion", icon='SHADING_RENDERED')
        row.prop(s, 'use_ao', text="")
        if s.use_ao:
            col = box.column(align=True)
            col.prop(s, 'ao_strength')
            col.prop(s, 'ao_radius')
            col.prop(s, 'ao_bias')
            box.label(text="Screen-space (offscreen pipeline)", icon='INFO')

        # The rest only affect the Per-Pixel (lit) mode. In Solid (studio) mode they
        # do nothing, so hide them to avoid confusion.
        if s.shading_mode == 'WORKBENCH':
            box = layout.box()
            box.label(text="Solid studio shading — always lit, no scene lights", icon='INFO')
            box.label(text="or shadows. (Switch to Per-Pixel for those.)")
            return

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
