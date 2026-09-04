import bpy


class VertexLitSettings(bpy.types.PropertyGroup):

    # ── Lighting ────────────────────────────────────────────────────────────
    # Hemisphere fill: low-frequency sky/ground ambient. (Matcaps land here later.)
    sky_color: bpy.props.FloatVectorProperty(
        name="Sky", subtype='COLOR', default=(0.60, 0.68, 0.78),
        min=0.0, max=1.0, description="Hemisphere sky colour (upper)")
    ground_color: bpy.props.FloatVectorProperty(
        name="Ground", subtype='COLOR', default=(0.20, 0.18, 0.16),
        min=0.0, max=1.0, description="Hemisphere ground colour (lower)")

    # ── View Mode (Blender's "Color") ───────────────────────────────────────
    view_mode: bpy.props.EnumProperty(
        name="View Mode",
        items=[
            ('TEXTURED',  "Textured",  "Show materials / textures (live node graph)"),
            ('SOLID',     "Solid",     "Flat single colour on every surface"),
            ('RANDOM',    "Random",    "A random colour per object"),
            ('ATTRIBUTE', "Attribute", "Show the mesh colour attribute (vertex colours)"),
            ('NORMAL',    "Normal",    "Visualise surface normals as colour"),
        ],
        default='TEXTURED',
        description="What surface colour to display")
    solid_color: bpy.props.FloatVectorProperty(
        name="Solid Color", subtype='COLOR', default=(0.8, 0.8, 0.8),
        min=0.0, max=1.0, description="Flat colour used by the Solid view mode")

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

    # ── Hidden (kept for engine wiring; no UI) ──────────────────────────────
    energy_scale: bpy.props.FloatProperty(
        name="Light Energy Scale", default=0.01, min=0.0001, max=10.0)
    use_shadows: bpy.props.BoolProperty(name="Shadows", default=False)
    shadow_resolution: bpy.props.EnumProperty(
        name="Shadow Resolution",
        items=[('512', '512', ''), ('1024', '1024', ''), ('2048', '2048', '')],
        default='1024')
    shadow_bias: bpy.props.FloatProperty(name="Bias", default=0.005, min=0.0, max=0.1)
    shadow_darkness: bpy.props.FloatProperty(name="Darkness", default=0.25, min=0.0, max=1.0)


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
