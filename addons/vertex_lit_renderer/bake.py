# vertex_lit_renderer/bake.py
"""
Bake the live material graph (the transpiled computeBaseColor) to an image, instantly.

Because this engine already compiles each material's node graph to a GLSL
computeBaseColor(), baking is just rasterising the mesh in UV space and evaluating
that function per texel — one GPU pass, no ray tracing. The result is a plain
albedo texture you can drop into Workbench / any other engine.
"""
import bpy
import numpy as np
import gpu
from gpu_extras.batch import batch_for_shader

from . import material_shader
from . import engine as _eng


def _get_gpu_image_tex(image):
    try:
        return gpu.texture.from_image(image) if image is not None else None
    except Exception:
        return None


def bake_material_to_image(obj, mat, depsgraph, res=1024, margin_fill=True):
    """Render obj's UV-space material graph into a new Blender image. Returns the image."""
    vert_src, frag_src, tr = material_shader.build_bake_frag(mat)
    shader = gpu.types.GPUShader(vert_src, frag_src)

    # Per-corner geometry (positions / uvs / normals / colours) for the slot(s) using `mat`.
    data = _eng._extract_mesh_data(obj, depsgraph)
    if not data:
        return None
    gen_min = data.get('gen_min', (0.0, 0.0, 0.0))
    gen_scale = data.get('gen_scale', (1.0, 1.0, 1.0))
    slots = [s for s in data.get('slots', []) if s.get('material_name') == mat.name]
    if not slots:
        slots = data.get('slots', [])   # fall back to everything if names don't line up

    offscreen = gpu.types.GPUOffScreen(res, res)
    arr = None
    try:
        with offscreen.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0))
            gpu.state.blend_set('NONE')
            gpu.state.depth_test_set('NONE')
            gpu.state.face_culling_set('NONE')
            shader.bind()
            try:
                shader.uniform_float('uGenMin', gen_min)
                shader.uniform_float('uGenScale', gen_scale)
            except Exception:
                pass
            nt = mat.node_tree
            for p in tr.params:
                try: shader.uniform_float(p.uniform, p.value(nt))
                except Exception: pass
            for uni, image in [(s.uniform, s.image) for s in tr.samplers]:
                gtex = _get_gpu_image_tex(image)
                if gtex is not None:
                    try: shader.uniform_sampler(uni, gtex)
                    except Exception: pass
            for slot in slots:
                cols = slot['colors'] if slot.get('colors') is not None else \
                    np.ones((len(slot['positions']), 4), dtype=np.float32)
                batch = batch_for_shader(shader, 'TRIS', {
                    'position':  slot['positions'],
                    'normal':    slot['normals'],
                    'vertColor': cols,
                    'texCoord':  slot['uvs'],
                })
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
    bl_description = ("Bake the active material's live node graph to a UV image "
                      "(albedo), instantly on the GPU")
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'ERROR'}, "Select a mesh object")
            return {'CANCELLED'}
        mat = obj.active_material
        if mat is None or not getattr(mat, 'use_nodes', False):
            self.report({'ERROR'}, "Active material has no node graph")
            return {'CANCELLED'}
        res = int(context.scene.vertex_lit.bake_resolution)
        try:
            depsgraph = context.evaluated_depsgraph_get()
            img = bake_material_to_image(obj, mat, depsgraph, res=res)
        except Exception as e:
            self.report({'ERROR'}, "Bake failed: {}".format(e))
            return {'CANCELLED'}
        if img is None:
            self.report({'ERROR'}, "Bake produced no image (no UVs / geometry?)")
            return {'CANCELLED'}
        self.report({'INFO'}, "Baked '{}' ({}x{})".format(img.name, res, res))
        return {'FINISHED'}


def register():
    bpy.utils.register_class(VERTEX_LIT_OT_bake_material)


def unregister():
    bpy.utils.unregister_class(VERTEX_LIT_OT_bake_material)
