# vertex_lit_renderer/__init__.py

bl_info = {
    "name":        "Vertex Lit Renderer",
    "author":      "Theory-box / Claude",
    (0, 1, 7),
    "blender":     (4, 4, 0),
    "location":    "Properties > Render > Render Engine → Vertex Lit",
    "description": "Gouraud per-vertex shading renderer for retro game look-dev. "
                   "Lighting (diffuse + shadow + ambient) is computed per vertex "
                   "and interpolated – matching the shading model of PS1/N64-era engines.",
    "warning":     "Experimental v0.1 – viewport only, no F12 render",
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
