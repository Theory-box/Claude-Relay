# vertex_lit_renderer/bake.py
"""
Bake the live material graph to an image, instantly.

The material is evaluated across a flat 0-1 UV plane — exactly as if you put it on a
default unwrapped plane — by drawing one fullscreen triangle and running the transpiled
computeBaseColor(uv) per texel. One GPU pass, no mesh, no ray tracing. The result is a
plain albedo texture you can drop into Workbench / any other engine.
"""
import bpy
import numpy as np
import gpu
from gpu_extras.batch import batch_for_shader

from . import material_shader
from . import shaders as _sh


def _get_gpu_image_tex(image):
    try:
        return gpu.texture.from_image(image) if image is not None else None
    except Exception:
        return None


def bake_material_to_image(mat, res=1024):
    """Render mat's node graph across a 0-1 UV plane into a new Blender image. Returns it."""
    _vert_unused, frag_src, tr = material_shader.build_bake_frag(mat)
    shader = gpu.types.GPUShader(_sh.PLANE_BAKE_VERT, frag_src)
    batch = batch_for_shader(shader, 'TRIS', {"pos": [(-1.0, -1.0), (3.0, -1.0), (-1.0, 3.0)]})

    print("[VertexLit] bake '{}': {} params, {} samplers, {}x{}".format(
        mat.name, len(tr.params), len(tr.samplers), res, res))

    offscreen = gpu.types.GPUOffScreen(res, res)
    arr = None
    try:
        with offscreen.bind():
            gpu.state.viewport_set(0, 0, res, res)
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 1.0))
            gpu.state.blend_set('NONE')
            gpu.state.depth_test_set('NONE')
            gpu.state.face_culling_set('NONE')
            shader.bind()
            nt = mat.node_tree
            for p in tr.params:
                try: shader.uniform_float(p.uniform, p.value(nt))
                except Exception: pass
            for uni, image in [(s.uniform, s.image) for s in tr.samplers]:
                gtex = _get_gpu_image_tex(image)
                if gtex is not None:
                    try: shader.uniform_sampler(uni, gtex)
                    except Exception: pass
            batch.draw(shader)
            buf = fb.read_color(0, 0, res, res, 4, 0, 'FLOAT')
        buf.dimensions = res * res * 4
        arr = np.array(buf, dtype=np.float32).reshape(res, res, 4)
    finally:
        offscreen.free()

    if arr is None:
        return None

    img = bpy.data.images.new("{}_baked".format(mat.name), res, res, alpha=True, float_buffer=False)
    # read_color is bottom-up; Blender image pixels are bottom-up too -> no flip.
    img.pixels = arr.reshape(-1).tolist()
    img.pack()
    return img


class VERTEX_LIT_OT_bake_material(bpy.types.Operator):
    bl_idname = "vertex_lit.bake_material"
    bl_label = "Bake Material to Image"
    bl_description = ("Bake the active material's live node graph to an image (albedo) across a "
                      "flat 0-1 UV plane, instantly on the GPU")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        ob = context.active_object
        mat = ob.active_material if ob is not None else None
        if mat is None or not getattr(mat, 'use_nodes', False):
            self.report({'ERROR'}, "Active object has no node material")
            return {'CANCELLED'}
        res = int(context.scene.vertex_lit.bake_resolution)
        try:
            img = bake_material_to_image(mat, res=res)
        except Exception as e:
            self.report({'ERROR'}, "Bake failed: {}".format(e))
            return {'CANCELLED'}
        if img is None:
            self.report({'ERROR'}, "Bake produced no image")
            return {'CANCELLED'}
        self.report({'INFO'}, "Baked '{}' ({}x{})".format(img.name, res, res))
        return {'FINISHED'}


def register():
    bpy.utils.register_class(VERTEX_LIT_OT_bake_material)


def unregister():
    bpy.utils.unregister_class(VERTEX_LIT_OT_bake_material)
