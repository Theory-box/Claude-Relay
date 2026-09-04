# vertex_lit_renderer/__init__.py

bl_info = {
    "name":        "Vertex Lit Renderer",
    "author":      "Theory-box / Claude",
    "version":     (0, 9, 5),
    "blender":     (4, 4, 0),
    "location":    "Properties > Render > Render Engine → Vertex Lit",
    "description": "Solid studio + live-node material renderer (+ screen-space AO) for retro game look-dev. "
                   "Lighting (diffuse + shadow + ambient) is computed per vertex "
                   "and interpolated (Gouraud), or per pixel (Phong). "
                   "Optional live material-node preview (transpiles the shader graph to GLSL).",
    "warning":     "Experimental. F12 render is viewport-quality. Default: Solid studio shading",
    "category":    "Render",
}

import bpy


def register():
    from . import props, engine, ui
    props.register()
    engine.register()
    ui.register()


def unregister():
    from . import props, engine, ui
    ui.unregister()
    engine.unregister()
    props.unregister()
