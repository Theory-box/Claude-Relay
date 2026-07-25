bl_info = {
    "name": "Reference Grid Drop",
    "author": "Claude Relay",
    "version": (1, 0, 0),
    "blender": (4, 4, 0),
    "location": "3D Viewport > drag & drop images  |  Add > Image > Reference Grid",
    "description": "Drop multiple images at once; lays them out as reference-image empties in a grid facing the current view.",
    "category": "Import-Export",
}

import os
import math
import bpy
from bpy.props import StringProperty, CollectionProperty, IntProperty, FloatProperty
from bpy.types import Operator, FileHandler, OperatorFileListElement
from mathutils import Vector, Quaternion

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".hdr",
              ".webp", ".bmp", ".tga", ".dds", ".psd")


class IMPORT_IMAGE_OT_reference_grid(Operator):
    bl_idname = "import_image.reference_grid"
    bl_label = "Reference Image Grid"
    bl_description = "Load multiple images as reference-image empties in a grid facing the current view"
    bl_options = {'REGISTER', 'UNDO'}

    directory: StringProperty(subtype='DIR_PATH', options={'SKIP_SAVE', 'HIDDEN'})
    files: CollectionProperty(type=OperatorFileListElement, options={'SKIP_SAVE', 'HIDDEN'})
    filter_glob: StringProperty(default=";".join("*" + e for e in IMAGE_EXTS), options={'HIDDEN'})

    per_row: IntProperty(name="Images Per Row",
                         description="How many images per row before wrapping",
                         default=4, min=1, max=64)
    cell_size: FloatProperty(name="Image Size",
                             description="Longest side of each image, in Blender units",
                             default=2.0, min=0.01, soft_max=20.0)
    gap: FloatProperty(name="Gap", description="Space between images, in Blender units",
                       default=0.3, min=0.0, soft_max=10.0)

    _view_rot = None
    _center = None

    def _capture_view(self, context):
        rv3d = None
        sp = context.space_data
        if sp and sp.type == 'VIEW_3D':
            rv3d = sp.region_3d
        if rv3d is None:
            for area in context.window.screen.areas:
                if area.type == 'VIEW_3D':
                    rv3d = area.spaces.active.region_3d
                    break
        if rv3d is not None:
            self._view_rot = rv3d.view_rotation.copy()
            self._center = rv3d.view_location.copy()
        else:
            self._view_rot = Quaternion()
            self._center = context.scene.cursor.location.copy()

    def invoke(self, context, event):
        self._capture_view(context)
        if self.files and self.directory:
            return context.window_manager.invoke_props_dialog(self, width=280)
        context.window_manager.fileselect_add(self)   # menu / manual fallback
        return {'RUNNING_MODAL'}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.prop(self, "per_row")
        col.prop(self, "cell_size")
        col.prop(self, "gap")
        n = max(len(self.files), 1)
        rows = math.ceil(n / max(self.per_row, 1))
        self.layout.label(text=f"{n} image(s) -> {rows} row(s)")

    def execute(self, context):
        paths = []
        if self.files:
            paths = [os.path.join(self.directory, f.name) for f in self.files if f.name]
        elif self.directory:
            paths = [self.directory]
        paths = [p for p in paths if os.path.splitext(p)[1].lower() in IMAGE_EXTS]
        if not paths:
            self.report({'WARNING'}, "No supported image files to import")
            return {'CANCELLED'}

        if self._view_rot is None:
            self._capture_view(context)

        if context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass

        view_rot, center = self._view_rot, self._center
        right = view_rot @ Vector((1.0, 0.0, 0.0))
        up = view_rot @ Vector((0.0, 1.0, 0.0))

        per_row = max(self.per_row, 1)
        n = len(paths)
        rows = math.ceil(n / per_row)
        cell = self.cell_size + self.gap

        created, errors = [], 0
        for i, path in enumerate(paths):
            col_i, row_i = i % per_row, i // per_row
            in_row = min(per_row, n - row_i * per_row)
            off_x = (col_i - (in_row - 1) / 2.0) * cell
            off_y = ((rows - 1) / 2.0 - row_i) * cell
            pos = center + right * off_x + up * off_y

            try:
                bpy.ops.object.empty_image_add(filepath=path, align='WORLD',
                                               location=(pos.x, pos.y, pos.z))
            except Exception as exc:
                errors += 1
                print("[Reference Grid] add failed:", path, exc)
                continue

            obj = context.active_object
            if obj is None:
                errors += 1
                continue

            obj.rotation_mode = 'QUATERNION'
            obj.rotation_quaternion = view_rot.copy()

            img = obj.data
            sz = getattr(img, "size", (1, 1)) if img else (1, 1)
            w, h = (sz[0] or 1), (sz[1] or 1)
            obj.empty_display_size = self.cell_size if w >= h else self.cell_size * (w / h)
            obj.empty_image_offset = (-0.5, -0.5)

            for attr, val in (("show_empty_image_perspective", True),
                              ("show_empty_image_orthographic", True),
                              ("show_empty_image_only_axis_aligned", False),
                              ("use_empty_image_alpha", True)):
                if hasattr(obj, attr):
                    setattr(obj, attr, val)

            obj.name = os.path.splitext(os.path.basename(path))[0]
            created.append(obj)

        if created:
            for o in list(context.selected_objects):
                o.select_set(False)
            for o in created:
                o.select_set(True)
            context.view_layer.objects.active = created[0]

        msg = f"Added {len(created)} reference image(s)"
        if errors:
            msg += f" ({errors} failed)"
        self.report({'INFO'}, msg)
        return {'FINISHED'} if created else {'CANCELLED'}


class IMPORT_IMAGE_FH_reference_grid(FileHandler):
    bl_idname = "IMPORT_IMAGE_FH_reference_grid"
    bl_label = "Reference Image Grid"
    bl_import_operator = "import_image.reference_grid"
    bl_file_extensions = ";".join(IMAGE_EXTS)

    @classmethod
    def poll_drop(cls, context):
        return context.area is not None and context.area.type == 'VIEW_3D'


_menu_target = []


def _menu_add(self, context):
    self.layout.operator(IMPORT_IMAGE_OT_reference_grid.bl_idname,
                         text="Reference Grid (multi-image)...", icon='IMAGE_REFERENCE')


classes = (IMPORT_IMAGE_OT_reference_grid, IMPORT_IMAGE_FH_reference_grid)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    menu = getattr(bpy.types, "VIEW3D_MT_image_add", None) or bpy.types.VIEW3D_MT_add
    menu.append(_menu_add)
    _menu_target.append(menu)


def unregister():
    if _menu_target:
        _menu_target.pop().remove(_menu_add)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
