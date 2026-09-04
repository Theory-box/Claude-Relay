import bpy


class _Base:
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'render'

    @classmethod
    def poll(cls, context):
        return context.scene.render.engine == 'VERTEX_LIT'


class VERTEX_LIT_PT_settings(_Base, bpy.types.Panel):
    bl_label = "Workbench 2.0"
    bl_idname = "VERTEX_LIT_PT_settings"

    def draw(self, context):
        pass   # container; collapsible sub-panels below


class VERTEX_LIT_PT_lighting(_Base, bpy.types.Panel):
    bl_label = "Lighting"
    bl_parent_id = "VERTEX_LIT_PT_settings"

    def draw(self, context):
        s = context.scene.vertex_lit
        col = self.layout.column(align=True)
        col.prop(s, 'sky_color')
        col.prop(s, 'ground_color')


class VERTEX_LIT_PT_viewmode(_Base, bpy.types.Panel):
    bl_label = "View Mode"
    bl_parent_id = "VERTEX_LIT_PT_settings"

    def draw(self, context):
        s = context.scene.vertex_lit
        layout = self.layout
        layout.prop(s, 'view_mode', text="")
        if s.view_mode == 'SOLID':
            layout.prop(s, 'solid_color', text="")


class VERTEX_LIT_PT_background(_Base, bpy.types.Panel):
    bl_label = "Background"
    bl_parent_id = "VERTEX_LIT_PT_settings"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = context.scene.vertex_lit
        layout = self.layout
        layout.prop(s, 'background_mode', text="")
        if s.background_mode == 'COLOR':
            layout.prop(s, 'background_color', text="")


class VERTEX_LIT_PT_shading(_Base, bpy.types.Panel):
    bl_label = "Shading"
    bl_parent_id = "VERTEX_LIT_PT_settings"

    def draw(self, context):
        s = context.scene.vertex_lit
        col = self.layout.column(align=True)
        col.prop(s, 'backface_cull')
        col.prop(s, 'key_intensity')


class VERTEX_LIT_PT_outline(_Base, bpy.types.Panel):
    bl_label = "Outline"
    bl_parent_id = "VERTEX_LIT_PT_shading"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene.vertex_lit, 'use_outline', text="")

    def draw(self, context):
        s = context.scene.vertex_lit
        layout = self.layout
        layout.active = s.use_outline
        col = layout.column(align=True)
        col.prop(s, 'outline_size')
        col.prop(s, 'outline_color', text="")
        ob = context.active_object
        if ob is not None and ob.type == 'MESH':
            layout.prop(ob, 'vlr_outline_exclude', text="Exclude active object")


class VERTEX_LIT_PT_cavity_world(_Base, bpy.types.Panel):
    bl_label = "Cavity World"
    bl_parent_id = "VERTEX_LIT_PT_shading"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene.vertex_lit, 'use_ao', text="")

    def draw(self, context):
        s = context.scene.vertex_lit
        layout = self.layout
        layout.active = s.use_ao
        col = layout.column(align=True)
        col.prop(s, 'ao_strength', text="Valley")
        col.prop(s, 'ao_ridge', text="Ridge")
        col.prop(s, 'ao_radius', text="Distance")
        col.prop(s, 'ao_bias', text="Bias")
        col.prop(s, 'ao_samples', text="Quality")
        ob = context.active_object
        if ob is not None and ob.type == 'MESH':
            layout.prop(ob, 'vlr_ao_exclude', text="Exclude active object")


class VERTEX_LIT_PT_cavity_screen(_Base, bpy.types.Panel):
    bl_label = "Cavity Screen"
    bl_parent_id = "VERTEX_LIT_PT_shading"
    bl_options = {'DEFAULT_CLOSED'}

    def draw_header(self, context):
        self.layout.prop(context.scene.vertex_lit, 'use_cavity', text="")

    def draw(self, context):
        s = context.scene.vertex_lit
        layout = self.layout
        layout.active = s.use_cavity
        col = layout.column(align=True)
        col.prop(s, 'cavity_ridge', text="Ridge")
        col.prop(s, 'cavity_valley', text="Valley")


_CLASSES = (
    VERTEX_LIT_PT_settings,
    VERTEX_LIT_PT_lighting,
    VERTEX_LIT_PT_viewmode,
    VERTEX_LIT_PT_background,
    VERTEX_LIT_PT_shading,
    VERTEX_LIT_PT_outline,
    VERTEX_LIT_PT_cavity_world,
    VERTEX_LIT_PT_cavity_screen,
)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
