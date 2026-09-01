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
        name="Samples", default=128, min=1, max=1024,
        description="Ray samples per vertex. More = less noise, slower rebuild")
    gi_rays_per_pass: bpy.props.IntProperty(
        name="Rays Per Pass", default=4, min=1, max=64,
        description="Samples accumulated per vertex per GI pass. Higher = faster convergence per pass")

    gi_thread_pause: bpy.props.FloatProperty(
        name="Thread Pause (ms)", default=0.1, min=0.0, max=20.0, precision=2,
        description="Milliseconds the GI thread sleeps every 64 vertices. "
                    "Lower = faster GI, higher = more Blender responsiveness")

    gi_bounce_strength: bpy.props.FloatProperty(
        name="Bounce Strength", default=1.0, min=0.0, max=5.0)

    # GI denoising (bilateral filter on bounce results, fades to zero near convergence)
    use_denoise: bpy.props.BoolProperty(
        name="Denoise", default=True,
        description="Apply a normal-weighted bilateral filter to GI bounce values. "
                    "Strength fades to zero as the scene converges, so the final "
                    "image is always the exact ray-traced result. Recommended on.")
    denoise_strength: bpy.props.FloatProperty(
        name="Denoise Strength", default=1.0, min=0.0, max=1.0,
        description="Max filter strength applied at 0%% convergence. Fades "
                    "quadratically to zero as sample count reaches target. "
                    "Lower values reduce any residual blurring risk at the "
                    "cost of more visible noise during convergence.")

    # Lights
    energy_scale: bpy.props.FloatProperty(
        name="Light Energy Scale", default=0.01, min=0.0001, max=10.0)


def register():
    bpy.utils.register_class(VertexLitSettings)
    bpy.types.Scene.vertex_lit = bpy.props.PointerProperty(type=VertexLitSettings)
    # Per-object shadow casting toggle (mirrors Cycles' visible_shadow)
    bpy.types.Object.vertex_lit_cast_shadow = bpy.props.BoolProperty(
        name="Cast Shadow",
        default=True,
        description="Object casts shadows in the Vertex Lit renderer")

def unregister():
    del bpy.types.Scene.vertex_lit
    del bpy.types.Object.vertex_lit_cast_shadow
    bpy.utils.unregister_class(VertexLitSettings)
