import bpy

class VertexLitSettings(bpy.types.PropertyGroup):

    # Shading model
    shading_mode: bpy.props.EnumProperty(
        name="Shading",
        items=[
            ('WORKBENCH', "Solid (Studio)",
             "Fast Workbench-style studio shading — always lit, no scene lights, "
             "no GI, no shadows"),
            ('VERTEX', "Per-Vertex (Gouraud)",
             "Scene-light lighting computed per vertex (retro; uses GI/shadows)"),
            ('PIXEL', "Per-Pixel (Phong)",
             "Scene-light lighting computed per fragment (uses GI/shadows)"),
        ],
        default='WORKBENCH')

    # Hemisphere fill (ambient fallback / low-frequency fill light)
    sky_color: bpy.props.FloatVectorProperty(
        name="Sky", subtype='COLOR', default=(0.05, 0.07, 0.10),
        min=0.0, max=1.0, description="Hemisphere sky ambient")
    ground_color: bpy.props.FloatVectorProperty(
        name="Ground", subtype='COLOR', default=(0.03, 0.02, 0.02),
        min=0.0, max=1.0, description="Hemisphere ground ambient")

    # GI
    use_gi: bpy.props.BoolProperty(
        name="GI Bounce", default=False,
        description="Compute real one-bounce light with BVH ray casting at rebuild "
                    "time. Off by default (experimental / slow; only affects the "
                    "Per-Vertex and Per-Pixel scene-light modes)")
    gi_samples: bpy.props.IntProperty(
        name="Samples", default=128, min=1, max=1024,
        description="Ray samples per vertex. More = less noise, slower rebuild")
    gi_rays_per_pass: bpy.props.IntProperty(
        name="Rays Per Pass", default=4, min=1, max=64,
        description="Samples accumulated per vertex per GI pass. Higher = faster convergence per pass")

    gi_thread_pause: bpy.props.FloatProperty(
        name="Thread Pause (ms)", default=1.0, min=0.0, max=20.0, precision=1,
        description="Milliseconds the GI thread sleeps every 64 vertices. "
                    "Lower = faster GI, higher = more Blender responsiveness")

    gi_bounce_strength: bpy.props.FloatProperty(
        name="Bounce Strength", default=1.0, min=0.0, max=5.0)

    # Lights
    energy_scale: bpy.props.FloatProperty(
        name="Light Energy Scale", default=0.01, min=0.0001, max=10.0)

    # Live material nodes (experimental)
    use_live_nodes: bpy.props.BoolProperty(
        name="Live Material Nodes", default=False,
        description="Transpile the shader node graph to GLSL so procedural / mix / "
                    "UV-distortion materials preview live in the viewport. "
                    "Experimental; falls back to the base texture if a material "
                    "can't be compiled")

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
