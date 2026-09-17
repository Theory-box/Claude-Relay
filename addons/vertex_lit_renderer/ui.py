import bpy

# Everything lives in ONE real panel ("Workbench 2.0"). Its sections are collapsible LAYOUT panels
# (UILayout.panel, Blender 4.1+) so that, unlike registered sub-panels, their HEADERS can be indented
# too. Hierarchy reads like a tree: a section's header is one step in from its parent's contents, and
# its own contents one step further.
_INDENT = 3.0          # horizontal indent per level (separator factor)
_FORCE_OPEN = False    # tests/screenshots: draw every section expanded


def indent(layout, steps=1):
    """Return a column indented `steps` indent steps inside `layout`."""
    if steps <= 0:
        return layout.column()
    row = layout.row()
    row.separator(factor=_INDENT * steps)
    return row.column()


def section(parent, idname, label, default_closed=False, toggle_owner=None, toggle=None):
    """A collapsible section inside `parent`. Its header sits at `parent`'s indent; the returned body
    column is one step further in. Returns None while the section is collapsed. With `toggle`, a
    checkbox for that property is drawn in the header (like Outline / Cavity)."""
    header, body = parent.panel(idname, default_closed=(default_closed and not _FORCE_OPEN))
    if toggle_owner is not None:
        header.prop(toggle_owner, toggle, text="")
    header.label(text=label)
    if body is None:
        return None
    return indent(body)


class VERTEX_LIT_PT_settings(bpy.types.Panel):
    bl_label = "Workbench 2.0"
    bl_idname = "VERTEX_LIT_PT_settings"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'render'

    @classmethod
    def poll(cls, context):
        return context.scene.render.engine == 'VERTEX_LIT'

    def draw(self, context):
        s = context.scene.vertex_lit
        root = indent(self.layout)
        self.draw_lighting(context, s, root)
        self.draw_viewmode(context, s, root)
        self.draw_background(context, s, root)
        self.draw_shading(context, s, root)
        self.draw_antialiasing(context, s, root)
        self.draw_bake(context, s, root)
        self.draw_splats(context, s, root)

    # ── Lighting ─────────────────────────────────────────────────────────────
    def draw_lighting(self, context, s, root):
        body = section(root, "VLR_lighting", "Lighting")
        if body is None:
            return
        body.prop(s, 'key_intensity')   # camera headlamp

        sky = section(body, "VLR_skyground", "Sky / Ground")
        if sky is not None:
            col = sky.column(align=True)
            col.prop(s, 'hemi_intensity')
            row = col.row(align=True)
            row.prop(s, 'sky_color')
            row.prop(s, 'ground_color')

        sun = section(body, "VLR_sun", "Sun")
        if sun is not None:
            col = sun.column(align=True)
            col.prop(s, 'sun_intensity')
            col.prop(s, 'sun_color', text="")
            col.prop(s, 'sun_elevation')
            col.prop(s, 'sun_azimuth')

            shadows = section(sun, "VLR_sun_shadows", "Shadows", default_closed=True,
                              toggle_owner=s, toggle='use_shadows')
            if shadows is not None:
                shadows.active = s.use_shadows and s.sun_intensity > 0.0
                col = shadows.column(align=True)
                col.prop(s, 'shadow_distance')
                col.prop(s, 'shadow_resolution')
                col.prop(s, 'shadow_softness')
                col.prop(s, 'shadow_bias')
                if s.use_shadows and s.sun_intensity <= 0.0:
                    shadows.label(text="Sun intensity is 0 - no shadows", icon='INFO')

    # ── View Mode / Background ───────────────────────────────────────────────
    def draw_viewmode(self, context, s, root):
        body = section(root, "VLR_viewmode", "View Mode")
        if body is None:
            return
        body.prop(s, 'view_mode', text="")
        if s.view_mode == 'SOLID':
            body.prop(s, 'solid_color', text="")
        elif s.view_mode == 'RANDOM':
            body.prop(s, 'random_mode', text="")
        elif s.view_mode == 'NORMAL':
            body.prop(s, 'normal_space', text="")
        elif s.view_mode == 'DEPTH':
            body.prop(s, 'depth_auto')
            sub = indent(body).column(align=True)      # Near/Far belong to the checkbox above
            sub.active = not s.depth_auto
            sub.prop(s, 'depth_min')
            sub.prop(s, 'depth_max')
        elif s.view_mode == 'ATTRIBUTE':
            ob = context.active_object
            me = ob.data if (ob is not None and ob.type == 'MESH') else None
            if me is not None and hasattr(me, 'color_attributes'):
                body.prop_search(s, 'view_attribute', me, 'color_attributes', text="")
            else:
                body.prop(s, 'view_attribute', text="")

    def draw_background(self, context, s, root):
        body = section(root, "VLR_background", "Background", default_closed=True)
        if body is None:
            return
        body.prop(s, 'background_mode', text="")
        if s.background_mode == 'COLOR':
            body.prop(s, 'background_color', text="")

    # ── Shading ──────────────────────────────────────────────────────────────
    def draw_shading(self, context, s, root):
        body = section(root, "VLR_shading", "Shading")
        if body is None:
            return
        body.prop(s, 'backface_cull')

        outline = section(body, "VLR_outline", "Outline", default_closed=True,
                          toggle_owner=s, toggle='use_outline')
        if outline is not None:
            outline.active = s.use_outline
            col = outline.column(align=True)
            col.prop(s, 'outline_size')
            col.prop(s, 'outline_color', text="")

        cw = section(body, "VLR_cavity_world", "Cavity World", default_closed=True,
                     toggle_owner=s, toggle='use_ao')
        if cw is not None:
            cw.active = s.use_ao
            col = cw.column(align=True)
            col.prop(s, 'ao_strength', text="Valley")
            col.prop(s, 'ao_ridge', text="Ridge")
            col.prop(s, 'ao_radius', text="Distance")
            col.prop(s, 'ao_bias', text="Bias")
            col.prop(s, 'ao_samples', text="Quality")

        cs = section(body, "VLR_cavity_screen", "Cavity Screen", default_closed=True,
                     toggle_owner=s, toggle='use_cavity')
        if cs is not None:
            cs.active = s.use_cavity
            col = cs.column(align=True)
            col.prop(s, 'cavity_ridge', text="Ridge")
            col.prop(s, 'cavity_valley', text="Valley")

    # ── Anti-Aliasing / Bake ─────────────────────────────────────────────────
    def draw_antialiasing(self, context, s, root):
        body = section(root, "VLR_antialiasing", "Anti-Aliasing", default_closed=True)
        if body is None:
            return
        col = body.column()
        col.prop(s, 'aa_method')
        col.prop(s, 'supersampling')

    def draw_bake(self, context, s, root):
        body = section(root, "VLR_bake", "Bake", default_closed=True)
        if body is None:
            return
        body.prop(s, 'bake_resolution')
        ob = context.active_object
        mat = ob.active_material if ob is not None else None
        if ob is None:
            why = "Select a mesh object to bake"
        elif ob.type != 'MESH':
            why = "Active object is not a mesh"
        elif mat is None:
            why = "Active object has no material"
        elif not getattr(mat, 'use_nodes', False):
            why = "Material '{}' does not use nodes".format(mat.name)
        else:
            why = None
        row = body.row()
        row.enabled = why is None
        row.operator("vertex_lit.bake_material", icon='RENDER_STILL')
        if why:
            body.label(text=why, icon='INFO')
        else:
            body.label(text="Active material: {}".format(mat.name), icon='MATERIAL')

    # ── Splats ───────────────────────────────────────────────────────────────
    def draw_splats(self, context, s, root):
        body = section(root, "VLR_splats", "Splats (experimental)", default_closed=True)
        if body is None:
            return
        ob = context.active_object
        is_mesh = ob is not None and ob.type == 'MESH'
        row = body.row(align=True)
        sub = row.row(align=True)
        sub.enabled = is_mesh
        sub.operator("vertex_lit.generate_splats", icon='OUTLINER_OB_POINTCLOUD')
        row.operator("vertex_lit.clear_splats", icon='TRASH')
        if not is_mesh:
            body.label(text="Select a mesh object to convert", icon='INFO')
        body.row().prop(s, 'splat_method', expand=True)
        col = body.column(align=True)
        col.prop(s, 'splat_count')
        col.prop(s, 'splat_color')

        shape = section(body, "VLR_splats_shape", "Shape")
        if shape is not None:
            col = shape.column(align=True)
            col.prop(s, 'splat_size')
            col.prop(s, 'splat_flatness')
            col.prop(s, 'splat_opacity')
            col.prop(s, 'splat_sigma')
            shape.prop(s, 'splat_seed')
            row = shape.row()
            row.prop(s, 'splat_bake')
            row.prop(s, 'splat_hide_src')
            shape.label(text="Applied when converting", icon='INFO')

        display = section(body, "VLR_splats_display", "Display")
        if display is not None:
            col = display.column(align=True)
            col.prop(s, 'splat_lit')
            col.prop(s, 'splat_backface')

        adv = section(body, "VLR_splats_advanced", "Advanced", default_closed=True)
        if adv is not None:
            adv.prop(s, 'splat_gpu_sort')
            sub = indent(adv)
            sub.active = s.splat_gpu_sort                  # radix only applies to the GPU sort
            sub.prop(s, 'splat_radix')
            col = adv.column(align=True)
            col.prop(s, 'splat_unified')
            col.prop(s, 'splat_compute')
            col.prop(s, 'splat_tile')


class VERTEX_LIT_PT_object(bpy.types.Panel):
    bl_label = "Workbench 2.0"
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        ob = context.object
        return (context.scene.render.engine == 'VERTEX_LIT'
                and ob is not None and ob.type == 'MESH')

    def draw(self, context):
        ob = context.object
        col = indent(self.layout)
        col.label(text="Exclude this object from:")
        sub = indent(col).column(align=True)
        sub.prop(ob, 'vlr_outline_exclude', text="Outline")
        sub.prop(ob, 'vlr_ao_exclude', text="Cavity World")


_CLASSES = (
    VERTEX_LIT_PT_settings,
    VERTEX_LIT_PT_object,
)


def register():
    for c in _CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(_CLASSES):
        bpy.utils.unregister_class(c)
