import bpy

class VertexLitSettings(bpy.types.PropertyGroup):

    # Screen-space Ambient Occlusion (post effect)
    use_ao: bpy.props.BoolProperty(
        name="Ambient Occlusion", default=False,
        description="Screen-space AO — darkens creases/contact")
    ao_strength: bpy.props.FloatProperty(name="AO Strength", default=1.0, min=0.0, max=4.0)
    ao_radius: bpy.props.FloatProperty(name="AO Radius", default=0.5, min=0.01, max=5.0)
    ao_bias: bpy.props.FloatProperty(name="AO Bias", default=0.02, min=0.0, max=0.5)

    # Object outline (screen-space)
    use_outline: bpy.props.BoolProperty(
        name="Outline", default=False,
        description="Draw an outline around objects (Workbench-style)")
    outline_size: bpy.props.FloatProperty(
        name="Outline Width", default=1.5, min=0.5, max=10.0,
        description="Outline thickness in pixels")
    outline_color: bpy.props.FloatVectorProperty(
        name="Outline Color", subtype='COLOR', default=(0.0, 0.0, 0.0),
        min=0.0, max=1.0)

    # Shading model
    shading_mode: bpy.props.EnumProperty(
        name="Shading",
        items=[
            ('WORKBENCH', "Solid (Studio)",
             "Fast Workbench-style studio shading — always lit, no scene lights"),
            ('PIXEL', "Per-Pixel (Lit)",
             "Per-fragment scene-light shading (sun + point/spot/area lights, shadows)"),
        ],
        default='PIXEL')

    # Hemisphere fill (ambient fallback / low-frequency fill light)
    sky_color: bpy.props.FloatVectorProperty(
        name="Sky", subtype='COLOR', default=(0.05, 0.07, 0.10),
        min=0.0, max=1.0, description="Hemisphere sky ambient")
    ground_color: bpy.props.FloatVectorProperty(
        name="Ground", subtype='COLOR', default=(0.03, 0.02, 0.02),
        min=0.0, max=1.0, description="Hemisphere ground ambient")

    # Lights
    energy_scale: bpy.props.FloatProperty(
        name="Light Energy Scale", default=0.01, min=0.0001, max=10.0)

    # Shadows (rasterised shadow map)
    use_shadows: bpy.props.BoolProperty(name="Shadows", default=False)
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
    # Per-object: exclude from contributing to (casting) screen-space AO.
    bpy.types.Object.vlr_ao_exclude = bpy.props.BoolProperty(
        name="Exclude from AO", default=False,
        description="This object won't cast or receive screen-space AO")

def unregister():
    del bpy.types.Object.vlr_ao_exclude
    del bpy.types.Scene.vertex_lit
    bpy.utils.unregister_class(VertexLitSettings)
