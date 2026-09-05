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
        self.layout.prop(s, 'key_intensity')   # camera headlamp


class VERTEX_LIT_PT_skyground(_Base, bpy.types.Panel):
    bl_label = "Sky / Ground"
    bl_parent_id = "VERTEX_LIT_PT_lighting"

    def draw(self, context):
        s = context.scene.vertex_lit
        col = self.layout.column(align=True)
        col.prop(s, 'hemi_intensity')
        row = col.row(align=True)
        row.prop(s, 'sky_color')
        row.prop(s, 'ground_color')


class VERTEX_LIT_PT_sun(_Base, bpy.types.Panel):
    bl_label = "Sun"
    bl_parent_id = "VERTEX_LIT_PT_lighting"

    def draw(self, context):
        s = context.scene.vertex_lit
        layout = self.layout
        col = layout.column(align=True)
        col.prop(s, 'sun_intensity')
        col.prop(s, 'sun_color', text="")
        col.prop(s, 'sun_elevation')
        col.prop(s, 'sun_azimuth')

        col = layout.column(align=True)
        col.prop(s, 'use_shadows')
        if s.use_shadows:
            sub = col.column(align=True)
            sub.active = s.sun_intensity > 0.0
            sub.prop(s, 'shadow_distance')
            sub.prop(s, 'shadow_resolution')
            sub.prop(s, 'shadow_softness')
            sub.prop(s, 'shadow_bias')


class VERTEX_LIT_PT_viewmode(_Base, bpy.types.Panel):
    bl_label = "View Mode"
    bl_parent_id = "VERTEX_LIT_PT_settings"

    def draw(self, context):
        s = context.scene.vertex_lit
        layout = self.layout
        layout.prop(s, 'view_mode', text="")
        if s.view_mode == 'SOLID':
            layout.prop(s, 'solid_color', text="")
        elif s.view_mode == 'RANDOM':
            layout.prop(s, 'random_mode', text="")
        elif s.view_mode == 'NORMAL':
            layout.prop(s, 'normal_space', text="")
        elif s.view_mode == 'DEPTH':
            col = layout.column(align=True)
            col.prop(s, 'depth_auto')
            sub = col.column(align=True)
            sub.active = not s.depth_auto
            sub.prop(s, 'depth_min')
            sub.prop(s, 'depth_max')
        elif s.view_mode == 'ATTRIBUTE':
            ob = context.active_object
            me = ob.data if (ob is not None and ob.type == 'MESH') else None
            if me is not None and hasattr(me, 'color_attributes'):
                layout.prop_search(s, 'view_attribute', me, 'color_attributes', text="")
            else:
                layout.prop(s, 'view_attribute', text="")


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


class VERTEX_LIT_PT_render_settings(_Base, bpy.types.Panel):
    bl_label = "Settings"
    bl_parent_id = "VERTEX_LIT_PT_settings"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = context.scene.vertex_lit
        col = self.layout.column()
        col.prop(s, 'aa_method')
        col.prop(s, 'supersampling')


class VERTEX_LIT_PT_bake(_Base, bpy.types.Panel):
    bl_label = "Bake"
    bl_parent_id = "VERTEX_LIT_PT_settings"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = context.scene.vertex_lit
        layout = self.layout
        col = layout.column(align=True)
        col.prop(s, 'bake_resolution')
        ob = context.active_object
        mat = ob.active_material if ob is not None else None
        row = layout.row()
        row.enabled = (ob is not None and ob.type == 'MESH'
                       and mat is not None and getattr(mat, 'use_nodes', False))
        row.operator("vertex_lit.bake_material", icon='RENDER_STILL')
        if mat is not None:
            layout.label(text="Active material: {}".format(mat.name), icon='MATERIAL')


class VERTEX_LIT_PT_splats(_Base, bpy.types.Panel):
    bl_label = "Splats (experimental)"
    bl_parent_id = "VERTEX_LIT_PT_settings"
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        s = context.scene.vertex_lit
        layout = self.layout
        col = layout.column(align=True)
        col.prop(s, 'splat_ply')
        col.prop(s, 'splat_sigma')
        if getattr(s, 'splat_ply', ''):
            layout.label(text="Composited with scene depth", icon='INFO')


_CLASSES = (
    VERTEX_LIT_PT_settings,
    VERTEX_LIT_PT_lighting,
    VERTEX_LIT_PT_skyground,
    VERTEX_LIT_PT_sun,
    VERTEX_LIT_PT_viewmode,
    VERTEX_LIT_PT_background,
    VERTEX_LIT_PT_shading,
    VERTEX_LIT_PT_outline,
    VERTEX_LIT_PT_cavity_world,
    VERTEX_LIT_PT_cavity_screen,
    VERTEX_LIT_PT_render_settings,
    VERTEX_LIT_PT_bake,
    VERTEX_LIT_PT_splats,
)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
