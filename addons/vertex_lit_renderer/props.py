import bpy


def _view_attr_update(self, context):
    # Selecting a different colour attribute needs a re-extraction of the vertex colours.
    try:
        from . import engine
        engine._FORCE_REEXTRACT = True
    except Exception:
        pass
    try:
        for area in context.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    except Exception:
        pass


class VertexLitSettings(bpy.types.PropertyGroup):

    # ── Lighting ────────────────────────────────────────────────────────────
    # Hemisphere fill: low-frequency sky/ground ambient. (Matcaps land here later.)
    hemi_intensity: bpy.props.FloatProperty(
        name="Sky/Ground", default=1.0, min=0.0, max=4.0,
        description="Hemisphere (sky/ground) intensity — 0 turns it off")
    sky_color: bpy.props.FloatVectorProperty(
        name="Sky", subtype='COLOR', default=(0.60, 0.68, 0.78),
        min=0.0, max=1.0, description="Hemisphere sky colour (upper)")
    ground_color: bpy.props.FloatVectorProperty(
        name="Ground", subtype='COLOR', default=(0.20, 0.18, 0.16),
        min=0.0, max=1.0, description="Hemisphere ground colour (lower)")

    # Directional sun — no object, no shadows. Height (elevation) + Angle (azimuth).
    sun_intensity: bpy.props.FloatProperty(
        name="Sun", default=1.0, min=0.0, max=10.0,
        description="Sun brightness — 0 turns it off")
    sun_color: bpy.props.FloatVectorProperty(
        name="Sun Color", subtype='COLOR', default=(1.0, 0.96, 0.90),
        min=0.0, max=1.0, description="Sun colour")
    sun_elevation: bpy.props.FloatProperty(
        name="Height", subtype='ANGLE', default=0.785398,  # 45 deg
        min=-1.5708, max=1.5708, description="Sun elevation above the horizon")
    sun_azimuth: bpy.props.FloatProperty(
        name="Angle", subtype='ANGLE', default=0.785398,  # 45 deg
        description="Sun compass direction (rotation around up)")
    # Sun shadows (directional shadow map, no light object)
    use_shadows: bpy.props.BoolProperty(
        name="Sun Shadows", default=False,
        description="Cast shadows from the sun (directional shadow map)")
    shadow_resolution: bpy.props.EnumProperty(
        name="Shadow Res",
        items=[('1024', '1024', ''), ('2048', '2048', ''), ('4096', '4096', '')],
        default='2048')
    shadow_bias: bpy.props.FloatProperty(
        name="Bias", default=0.0015, min=0.0, max=0.05, precision=4,
        description="Depth bias to avoid shadow acne")
    shadow_softness: bpy.props.FloatProperty(
        name="Softness", default=1.5, min=0.0, max=8.0,
        description="Soft-edge width (PCF kernel spread)")

    # ── View Mode (Blender's "Color") ───────────────────────────────────────
    view_mode: bpy.props.EnumProperty(
        name="View Mode",
        items=[
            ('TEXTURED',  "Textured",  "Show materials / textures (live node graph)"),
            ('SOLID',     "Solid",     "Flat single colour on every surface"),
            ('RANDOM',    "Random",    "A random colour per object or per material"),
            ('ATTRIBUTE', "Attribute", "Show the mesh colour attribute (vertex colours)"),
            ('NORMAL',    "Normal",    "Visualise surface normals as colour"),
            ('DEPTH',     "Depth",     "Visualise distance from the camera as greyscale"),
        ],
        default='TEXTURED',
        description="What surface colour to display")
    random_mode: bpy.props.EnumProperty(
        name="Random By",
        items=[('OBJECT',   "Per Object",   "A colour per object"),
               ('MATERIAL', "Per Material", "A colour per material (shared objects match; "
                                            "multi-material objects get one colour per slot)")],
        default='OBJECT')
    depth_min: bpy.props.FloatProperty(
        name="Near", default=0.0, min=0.0, soft_max=100.0,
        description="Distance mapped to white")
    depth_max: bpy.props.FloatProperty(
        name="Far", default=20.0, min=0.01, soft_max=1000.0,
        description="Distance mapped to black")
    solid_color: bpy.props.FloatVectorProperty(
        name="Solid Color", subtype='COLOR', default=(0.8, 0.8, 0.8),
        min=0.0, max=1.0, description="Flat colour used by the Solid view mode")
    view_attribute: bpy.props.StringProperty(
        name="Attribute", default="",
        description="Colour attribute to display in Attribute view (blank = active)",
        update=_view_attr_update)

    # ── Background ──────────────────────────────────────────────────────────
    background_mode: bpy.props.EnumProperty(
        name="Background",
        items=[
            ('WORLD', "World", "Hemisphere sky/ground gradient"),
            ('COLOR', "Color", "A single flat colour"),
        ],
        default='WORLD',
        description="What to draw behind the scene")
    background_color: bpy.props.FloatVectorProperty(
        name="Background Color", subtype='COLOR', default=(0.05, 0.05, 0.05),
        min=0.0, max=1.0, description="Flat background colour")

    # ── Shading ─────────────────────────────────────────────────────────────
    backface_cull: bpy.props.BoolProperty(
        name="Backface Culling", default=True,
        description="Cull back faces globally. Turn off to render both sides of every face")
    # Camera key light: a headlamp that follows the view, added on top of the hemisphere.
    key_intensity: bpy.props.FloatProperty(
        name="Key Light", default=0.8, min=0.0, max=4.0,
        description="Intensity of the camera-following key light")

    # Object outline (screen-space)
    use_outline: bpy.props.BoolProperty(
        name="Outline", default=False,
        description="Draw an outline around objects (Workbench-style)")
    outline_size: bpy.props.FloatProperty(
        name="Outline Width", default=1.5, min=0.5, max=10.0,
        description="Outline thickness in pixels")
    outline_color: bpy.props.FloatVectorProperty(
        name="Outline Color", subtype='COLOR', size=4, default=(0.0, 0.0, 0.0, 1.0),
        min=0.0, max=1.0, description="Outline colour and opacity (alpha)")

    # Cavity World (SSAO): valley darkens crevices, ridge brightens exposed surfaces
    use_ao: bpy.props.BoolProperty(
        name="Cavity World", default=False,
        description="World-space cavity (SSAO): darken crevices (valley), brighten exposed (ridge)")
    ao_strength: bpy.props.FloatProperty(name="Valley", default=1.0, min=0.0, max=4.0)
    ao_ridge: bpy.props.FloatProperty(
        name="Ridge", default=0.0, min=0.0, max=4.0,
        description="World-space ridge: brighten convex, exposed surfaces (reverse AO)")
    ao_radius: bpy.props.FloatProperty(name="Distance", default=0.5, min=0.01, max=5.0)
    ao_bias: bpy.props.FloatProperty(name="Bias", default=0.02, min=0.0, max=0.5)
    ao_samples: bpy.props.EnumProperty(
        name="Quality",
        items=[('16', "Low (16)", "16 samples"),
               ('32', "Medium (32)", "32 samples"),
               ('64', "High (64)", "64 samples")],
        default='16', description="AO samples per pixel — higher is smoother but slower")

    # Cavity Screen (curvature): ridge brightens edges, valley darkens creases
    use_cavity: bpy.props.BoolProperty(
        name="Cavity Screen", default=False,
        description="Screen-space curvature: brighten convex edges (ridge), darken creases (valley)")
    cavity_ridge: bpy.props.FloatProperty(name="Ridge", default=1.0, min=0.0, max=4.0)
    cavity_valley: bpy.props.FloatProperty(name="Valley", default=1.0, min=0.0, max=4.0)

    # ── Settings ────────────────────────────────────────────────────────────
    aa_method: bpy.props.EnumProperty(
        name="Anti-Aliasing",
        items=[('OFF', "None", "No anti-aliasing"),
               ('FXAA', "FXAA", "Fast approximate anti-aliasing (post-process edge smoothing)")],
        default='FXAA',
        description="Edge anti-aliasing method")
    supersampling: bpy.props.EnumProperty(
        name="Supersampling",
        items=[('1', "1x (off)", "No supersampling"),
               ('1.5', "1.5x", "Render at 1.5x resolution and downscale"),
               ('2', "2x", "Render at 2x resolution and downscale — sharpest, slowest")],
        default='1',
        description="Render at higher resolution and downscale for smooth edges (SSAA)")
    bake_resolution: bpy.props.EnumProperty(
        name="Bake Size",
        items=[('512', "512", ""), ('1024', "1024", ""), ('2048', "2048", ""), ('4096', "4096", "")],
        default='1024',
        description="Resolution of the baked material image")

    # ── Hidden (kept for engine wiring; no UI) ──────────────────────────────
    energy_scale: bpy.props.FloatProperty(
        name="Light Energy Scale", default=0.01, min=0.0001, max=10.0)


def register():
    bpy.utils.register_class(VertexLitSettings)
    bpy.types.Scene.vertex_lit = bpy.props.PointerProperty(type=VertexLitSettings)
    bpy.types.Object.vlr_ao_exclude = bpy.props.BoolProperty(
        name="Exclude from Cavity World", default=False,
        description="This object won't cast or receive world cavity (AO)")
    bpy.types.Object.vlr_outline_exclude = bpy.props.BoolProperty(
        name="Exclude from Outline", default=False,
        description="This object won't get an outline")


def unregister():
    del bpy.types.Object.vlr_ao_exclude
    del bpy.types.Object.vlr_outline_exclude
    del bpy.types.Scene.vertex_lit
    bpy.utils.unregister_class(VertexLitSettings)
