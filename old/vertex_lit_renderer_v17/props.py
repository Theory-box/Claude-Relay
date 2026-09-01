import bpy

class VertexLitSettings(bpy.types.PropertyGroup):

    # Hemisphere fill (ambient fallback / low-frequency fill light)
    sky_color: bpy.props.FloatVectorProperty(
        name="Sky", subtype='COLOR', default=(0.05, 0.07, 0.10),
        min=0.0, max=1.0, description="Hemisphere sky ambient")
    ground_color: bpy.props.FloatVectorProperty(
        name="Ground", subtype='COLOR', default=(0.03, 0.02, 0.02),
        min=0.0, max=1.0, description="Hemisphere ground ambient")

    # GI
    use_gi: bpy.props.BoolProperty(
        name="GI Bounce", default=True,
        description="Compute real one-bounce light with BVH ray casting at rebuild time")
    gi_samples: bpy.props.IntProperty(
        name="Samples", default=8, min=1, max=128,
        description="Ray samples per vertex. More = less noise, slower rebuild")
    gi_bounce_strength: bpy.props.FloatProperty(
        name="Bounce Strength", default=1.0, min=0.0, max=5.0)

    # Lights
    energy_scale: bpy.props.FloatProperty(
        name="Light Energy Scale", default=0.01, min=0.0001, max=10.0)

    # Shadows
    use_shadows: bpy.props.BoolProperty(name="Shadows", default=True)
    shadow_resolution: bpy.props.EnumProperty(
        name="Shadow Resolution",
        items=[('512','512',''),('1024','1024',''),('2048','2048','')],
        default='1024')
    shadow_bias: bpy.props.FloatProperty(name="Bias", default=0.005, min=0.0, max=0.1)
    shadow_darkness: bpy.props.FloatProperty(
        name="Darkness", default=0.25, min=0.0, max=1.0)

def register():
    bpy.utils.register_class(VertexLitSettings)
    bpy.types.Scene.vertex_lit = bpy.props.PointerProperty(type=VertexLitSettings)

def unregister():
    del bpy.types.Scene.vertex_lit
    bpy.utils.unregister_class(VertexLitSettings)
