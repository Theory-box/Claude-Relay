bl_info = {
    "name":        "OG Light Baking (test panel)",
    "author":      "OpenGOAL Tools",
    "version":     (1, 0, 0),
    "blender":     (4, 4, 0),
    "location":    "View3D > N-Panel > OpenGOAL",
    "description": "Bake scene lighting to vertex colors on selected meshes",
    "category":    "3D View",
}

"""
OG_PT_LightBaking — scratch patch
Adds a "🔆 Light Baking" panel to the OpenGOAL N-panel tab.

HOW TO MERGE INTO MAIN ADDON:
1. Copy the OGBakeProps class into the PropertyGroup section
2. Copy OG_OT_BakeVertexLighting + OG_PT_LightBaking into the classes section
3. Add OGBakeProps registration to register() / unregister()
4. Add the panel + operator to the `classes` tuple

STANDALONE TEST:
Paste this whole file into Blender's text editor and Run Script to test
the panel in isolation before merging.
"""

import bpy
from bpy.props import IntProperty
from bpy.types import Panel, Operator, PropertyGroup


# ── Properties ────────────────────────────────────────────────────────────────

class OGBakeProps(PropertyGroup):
    samples: IntProperty(
        name="Samples",
        description="Number of Cycles samples per vertex for the bake. "
                    "Higher = cleaner result but slower. 64–256 is usually enough.",
        default=128,
        min=1,
        max=4096,
    )


# ── Operator ──────────────────────────────────────────────────────────────────

class OG_OT_BakeVertexLighting(Operator):
    bl_idname      = "og.bake_vertex_lighting"
    bl_label       = "Bake Vertex Lighting"
    bl_description = ("Bake scene lighting to vertex colors on all selected mesh objects. "
                      "Forces Cycles render engine. Existing 'BakedLight' color attribute "
                      "is overwritten; created if absent.")
    bl_options     = {"REGISTER", "UNDO"}

    def execute(self, ctx):
        meshes = [o for o in ctx.selected_objects if o.type == 'MESH']
        if not meshes:
            self.report({"WARNING"}, "No mesh objects selected")
            return {"CANCELLED"}

        scene = ctx.scene

        # ── Store user render state ────────────────────────────────────────
        prev_engine  = scene.render.engine
        prev_samples = scene.cycles.samples
        prev_active  = ctx.view_layer.objects.active

        # ── Switch to Cycles ───────────────────────────────────────────────
        scene.render.engine  = "CYCLES"
        scene.cycles.samples = ctx.scene.og_bake_props.samples

        baked, skipped = 0, 0

        for obj in meshes:
            ctx.view_layer.objects.active = obj

            mesh = obj.data
            attr_name = "BakedLight"

            # Ensure vertex color attribute exists (overwrite if present)
            if attr_name in mesh.color_attributes:
                mesh.color_attributes.remove(mesh.color_attributes[attr_name])
            mesh.color_attributes.new(
                name=attr_name,
                type="BYTE_COLOR",
                domain="CORNER",   # face corner = standard for baking
            )

            # Select the attribute as the active render target
            mesh.color_attributes.active_color = mesh.color_attributes[attr_name]

            # Bake — DIFFUSE type captures light + shadow, not albedo
            try:
                bpy.ops.object.bake(
                    type="DIFFUSE",
                    pass_filter={"DIRECT", "INDIRECT"},  # light only, skip color
                    target="VERTEX_COLORS",
                    save_mode="INTERNAL",
                )
                self.report({"INFO"}, f"Baked: {obj.name}")
                baked += 1
            except Exception as e:
                self.report({"WARNING"}, f"Failed on {obj.name}: {e}")
                skipped += 1

        # ── Restore user render state ──────────────────────────────────────
        scene.render.engine          = prev_engine
        scene.cycles.samples         = prev_samples
        ctx.view_layer.objects.active = prev_active

        self.report(
            {"INFO"},
            f"Light bake done — {baked} baked, {skipped} skipped"
        )
        return {"FINISHED"}


# ── Panel ─────────────────────────────────────────────────────────────────────

class OG_PT_LightBaking(Panel):
    bl_label       = "🔆  Light Baking"
    bl_idname      = "OG_PT_light_baking"
    bl_space_type  = "VIEW_3D"
    bl_region_type = "UI"
    bl_category    = "OpenGOAL"
    bl_options     = {"DEFAULT_CLOSED"}

    def draw(self, ctx):
        layout = self.layout
        props  = ctx.scene.og_bake_props

        # ── Info ──────────────────────────────────────────────────────────
        col = layout.column(align=True)
        col.label(text="Bakes lighting → vertex colors", icon="LIGHT_SUN")
        col.label(text="Attribute name: BakedLight", icon="BLANK1")
        layout.separator(factor=0.5)

        # ── Sample count ──────────────────────────────────────────────────
        row = layout.row(align=True)
        row.prop(props, "samples")
        layout.separator(factor=0.3)

        # ── Bake button ───────────────────────────────────────────────────
        sel_meshes = [o for o in ctx.selected_objects if o.type == 'MESH']
        count = len(sel_meshes)

        row = layout.row()
        row.scale_y = 1.4
        if count == 0:
            row.enabled = False
            row.operator("og.bake_vertex_lighting",
                         text="Bake Vertex Lighting (select meshes first)",
                         icon="RENDER_STILL")
        else:
            row.operator("og.bake_vertex_lighting",
                         text=f"Bake Vertex Lighting  ({count} object{'s' if count != 1 else ''})",
                         icon="RENDER_STILL")


# ── Standalone registration (for testing in text editor) ──────────────────────

classes = (OGBakeProps, OG_OT_BakeVertexLighting, OG_PT_LightBaking)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.og_bake_props = bpy.props.PointerProperty(type=OGBakeProps)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    if hasattr(bpy.types.Scene, "og_bake_props"):
        del bpy.types.Scene.og_bake_props

if __name__ == "__main__":
    register()
