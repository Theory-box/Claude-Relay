import bpy

class VertexLitSettings(bpy.types.PropertyGroup):

    # Hemisphere fill
    sky_color: bpy.props.FloatVectorProperty(
        name="Sky", subtype='COLOR', default=(0.25, 0.30, 0.40),
        min=0.0, max=1.0, description="Ambient colour for upward-facing surfaces")
    ground_color: bpy.props.FloatVectorProperty(
        name="Ground", subtype='COLOR', default=(0.08, 0.07, 0.05),
        min=0.0, max=1.0, description="Ambient colour for downward-facing surfaces")

    # GI — off by default; enable for subtle fill on static geometry
    use_gi: bpy.props.BoolProperty(
        name="GI Bounce", default=False,
        description="One-bounce ray traced GI. Disable for geo nodes / heavy scenes")
    gi_samples: bpy.props.IntProperty(
        name="Samples", default=8, min=1, max=128)
    gi_bounce_strength: bpy.props.FloatProperty(
        name="Bounce Strength", default=0.5, min=0.0, max=5.0)

    # Light scale — 0.1 works for Blender's default 1 W/m² sun
    energy_scale: bpy.props.FloatProperty(
        name="Light Energy Scale", default=0.5, min=0.0001, max=100.0,
        description=(
            "Multiplier on all light energies. "
            "0.1 = good for a 1 W sun (Blender default). "
            "Increase if lights look too dim, decrease if too bright."))

    # Shadows
    use_shadows: bpy.props.BoolProperty(name="Shadows", default=True)
    shadow_resolution: bpy.props.EnumProperty(
        name="Shadow Resolution",
        items=[('512','512',''),('1024','1024',''),('2048','2048','')],
        default='1024')
    shadow_bias: bpy.props.FloatProperty(
        name="Bias", default=0.005, min=0.0, max=0.1)
    shadow_darkness: bpy.props.FloatProperty(
        name="Darkness", default=0.25, min=0.0, max=1.0)

def register():
    bpy.utils.register_class(VertexLitSettings)
    bpy.types.Scene.vertex_lit = bpy.props.PointerProperty(type=VertexLitSettings)

def unregister():
    del bpy.types.Scene.vertex_lit
    bpy.utils.unregister_class(VertexLitSettings)
