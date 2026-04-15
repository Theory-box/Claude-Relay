bl_info = {
    "name": "Quick Commands",
    "author": "Custom",
    "version": (1, 4, 0),
    "blender": (4, 4, 0),
    "location": "View3D > Sidebar > Quick Commands",
    "description": "Create custom Python command buttons on the fly",
    "category": "Development",
}

import bpy
from bpy.props import StringProperty, CollectionProperty, IntProperty, BoolProperty, FloatProperty, EnumProperty
from bpy.types import Panel, Operator, PropertyGroup, UIList


# A single line of code within a command
class QuickCommandLine(PropertyGroup):
    code: StringProperty(
        name="Code",
        description="A line of Python code",
        default=""
    )


# A single user-defined variable for a command
class QuickCommandVariable(PropertyGroup):
    var_name: StringProperty(
        name="Name",
        description="Variable name used in code (no spaces, valid Python identifier)",
        default="my_var"
    )
    var_type: EnumProperty(
        name="Type",
        description="Data type of this variable",
        items=[
            ('FLOAT',  'Float',   'Floating-point number'),
            ('INT',    'Int',     'Integer number'),
            ('STRING', 'String',  'Text value'),
            ('BOOL',   'Bool',    'True / False toggle'),
        ],
        default='FLOAT'
    )
    val_float: FloatProperty(
        name="Value",
        description="Float value",
        default=0.0,
        precision=4,
        step=1,
    )
    val_int: IntProperty(
        name="Value",
        description="Integer value",
        default=0
    )
    val_string: StringProperty(
        name="Value",
        description="String value",
        default=""
    )
    val_bool: BoolProperty(
        name="Value",
        description="Boolean value",
        default=False
    )

    def python_value(self):
        """Return the variable's current value as the correct Python type."""
        if self.var_type == 'FLOAT':
            return self.val_float
        elif self.var_type == 'INT':
            return self.val_int
        elif self.var_type == 'STRING':
            return self.val_string
        else:  # BOOL
            return self.val_bool


# Property group to store each command
class QuickCommandItem(PropertyGroup):
    name: StringProperty(
        name="Name",
        description="Display name for this command",
        default="New Command"
    )
    # Keep legacy single command field for backwards compat (unused in UI now)
    command: StringProperty(
        name="Command",
        description="Python code to execute",
        default=""
    )
    lines: CollectionProperty(type=QuickCommandLine)
    lines_index: IntProperty(
        name="Active Line Index",
        description="Index of the currently selected code line",
        default=0
    )
    show_code: BoolProperty(
        name="Show Code",
        description="Expand/collapse the Python code lines",
        default=True
    )
    variables: CollectionProperty(type=QuickCommandVariable)
    variables_index: IntProperty(
        name="Active Variable Index",
        default=0
    )
    show_vars: BoolProperty(
        name="Show Variables",
        description="Expand/collapse the variables section",
        default=True
    )


# Operator to execute a command
class QUICKCMD_OT_execute_command(Operator):
    bl_idname = "quickcmd.execute_command"
    bl_label = "Execute Command"
    bl_description = "Execute the Python command(s)"

    index: IntProperty()

    def execute(self, context):
        item = context.scene.quick_commands[self.index]

        # Build full script from lines
        script_lines = [l.code for l in item.lines]
        # Also support legacy single-line command if lines are empty
        if not script_lines and item.command.strip():
            script_lines = [item.command]

        if not any(l.strip() for l in script_lines):
            self.report({'WARNING'}, "No code to execute")
            return {'CANCELLED'}

        script = "\n".join(script_lines)

        # Build variable namespace from this command's variable list
        var_namespace = {v.var_name: v.python_value() for v in item.variables if v.var_name.strip()}

        try:
            exec(script, {"bpy": bpy, "context": context, **var_namespace})
            self.report({'INFO'}, f"Executed: {item.name}")
            return {'FINISHED'}
        except Exception as e:
            self.report({'ERROR'}, f"Error: {str(e)}")
            return {'CANCELLED'}


# Operator to add a new command
class QUICKCMD_OT_add_command(Operator):
    bl_idname = "quickcmd.add_command"
    bl_label = "Add Command"
    bl_description = "Add a new command to the list"

    def execute(self, context):
        item = context.scene.quick_commands.add()
        # Start with one blank line
        item.lines.add()
        context.scene.quick_commands_index = len(context.scene.quick_commands) - 1
        return {'FINISHED'}


# Operator to remove a command
class QUICKCMD_OT_remove_command(Operator):
    bl_idname = "quickcmd.remove_command"
    bl_label = "Remove Command"
    bl_description = "Remove the selected command"

    def execute(self, context):
        commands = context.scene.quick_commands
        index = context.scene.quick_commands_index

        if len(commands) > 0:
            commands.remove(index)
            context.scene.quick_commands_index = min(max(0, index - 1), len(commands) - 1)

        return {'FINISHED'}


# Operator to move command up
class QUICKCMD_OT_move_command_up(Operator):
    bl_idname = "quickcmd.move_command_up"
    bl_label = "Move Up"
    bl_description = "Move command up in the list"

    def execute(self, context):
        commands = context.scene.quick_commands
        index = context.scene.quick_commands_index

        if index > 0:
            commands.move(index, index - 1)
            context.scene.quick_commands_index = index - 1

        return {'FINISHED'}


# Operator to move command down
class QUICKCMD_OT_move_command_down(Operator):
    bl_idname = "quickcmd.move_command_down"
    bl_label = "Move Down"
    bl_description = "Move command down in the list"

    def execute(self, context):
        commands = context.scene.quick_commands
        index = context.scene.quick_commands_index

        if index < len(commands) - 1:
            commands.move(index, index + 1)
            context.scene.quick_commands_index = index + 1

        return {'FINISHED'}


# Operator to add a code line to the selected command
class QUICKCMD_OT_add_line(Operator):
    bl_idname = "quickcmd.add_line"
    bl_label = "Add Line"
    bl_description = "Add another line of Python code to this command"

    def execute(self, context):
        commands = context.scene.quick_commands
        index = context.scene.quick_commands_index
        if len(commands) > 0:
            commands[index].lines.add()
        return {'FINISHED'}


# Operator to remove a code line from the selected command
class QUICKCMD_OT_remove_line(Operator):
    bl_idname = "quickcmd.remove_line"
    bl_label = "Remove Line"
    bl_description = "Remove the selected code line"

    line_index: IntProperty()

    def execute(self, context):
        commands = context.scene.quick_commands
        cmd_index = context.scene.quick_commands_index
        if len(commands) > 0:
            lines = commands[cmd_index].lines
            if len(lines) > 1:
                lines.remove(self.line_index)
                commands[cmd_index].lines_index = min(
                    self.line_index, len(lines) - 1
                )
        return {'FINISHED'}


# Operator to move a code line up
class QUICKCMD_OT_move_line_up(Operator):
    bl_idname = "quickcmd.move_line_up"
    bl_label = "Move Line Up"
    bl_description = "Move the selected code line up"

    def execute(self, context):
        commands = context.scene.quick_commands
        cmd_index = context.scene.quick_commands_index
        if len(commands) == 0:
            return {'CANCELLED'}
        item = commands[cmd_index]
        idx = item.lines_index
        if idx > 0:
            item.lines.move(idx, idx - 1)
            item.lines_index = idx - 1
        return {'FINISHED'}


# Operator to move a code line down
class QUICKCMD_OT_move_line_down(Operator):
    bl_idname = "quickcmd.move_line_down"
    bl_label = "Move Line Down"
    bl_description = "Move the selected code line down"

    def execute(self, context):
        commands = context.scene.quick_commands
        cmd_index = context.scene.quick_commands_index
        if len(commands) == 0:
            return {'CANCELLED'}
        item = commands[cmd_index]
        idx = item.lines_index
        if idx < len(item.lines) - 1:
            item.lines.move(idx, idx + 1)
            item.lines_index = idx + 1
        return {'FINISHED'}



# Operator to duplicate the selected command
class QUICKCMD_OT_duplicate_command(Operator):
    bl_idname = "quickcmd.duplicate_command"
    bl_label = "Duplicate Command"
    bl_description = "Duplicate the selected command"

    def execute(self, context):
        commands = context.scene.quick_commands
        index = context.scene.quick_commands_index

        if len(commands) == 0:
            return {'CANCELLED'}

        src = commands[index]
        new_item = commands.add()
        new_item.name = src.name + " Copy"
        new_item.show_code = src.show_code
        new_item.show_vars = src.show_vars
        for src_line in src.lines:
            new_line = new_item.lines.add()
            new_line.code = src_line.code
        for src_var in src.variables:
            new_var = new_item.variables.add()
            new_var.var_name   = src_var.var_name
            new_var.var_type   = src_var.var_type
            new_var.val_float  = src_var.val_float
            new_var.val_int    = src_var.val_int
            new_var.val_string = src_var.val_string
            new_var.val_bool   = src_var.val_bool

        # Move the new item to sit right after the source
        new_index = len(commands) - 1
        target_index = index + 1
        commands.move(new_index, target_index)
        context.scene.quick_commands_index = target_index

        return {'FINISHED'}




# Operator to add a variable to the selected command
class QUICKCMD_OT_add_variable(Operator):
    bl_idname = "quickcmd.add_variable"
    bl_label = "Add Variable"
    bl_description = "Add a new variable to this command"

    def execute(self, context):
        commands = context.scene.quick_commands
        index = context.scene.quick_commands_index
        if len(commands) > 0:
            v = commands[index].variables.add()
            v.var_name = f"var{len(commands[index].variables)}"
        return {'FINISHED'}


# Operator to remove a variable from the selected command
class QUICKCMD_OT_remove_variable(Operator):
    bl_idname = "quickcmd.remove_variable"
    bl_label = "Remove Variable"
    bl_description = "Remove the selected variable"

    var_index: IntProperty()

    def execute(self, context):
        commands = context.scene.quick_commands
        cmd_index = context.scene.quick_commands_index
        if len(commands) > 0:
            variables = commands[cmd_index].variables
            if len(variables) > 0:
                variables.remove(self.var_index)
                commands[cmd_index].variables_index = min(
                    self.var_index, max(0, len(variables) - 1)
                )
        return {'FINISHED'}


# UI List for displaying commands
class QUICKCMD_UL_command_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            layout.prop(item, "name", text="", emboss=False, icon='SCRIPT')
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon='SCRIPT')


# UI List for displaying code lines within a command
class QUICKCMD_UL_line_list(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            # Show line number + code as a read-only label so the list stays compact
            layout.label(text=f"{index + 1}:  {item.code}", icon='NONE')
        elif self.layout_type in {'GRID'}:
            layout.alignment = 'CENTER'
            layout.label(text="", icon='NONE')


# Main panel
class QUICKCMD_PT_main_panel(Panel):
    bl_label = "Quick Commands"
    bl_idname = "QUICKCMD_PT_main_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quick Cmds"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # List of commands
        row = layout.row()
        row.template_list(
            "QUICKCMD_UL_command_list",
            "",
            scene,
            "quick_commands",
            scene,
            "quick_commands_index",
            rows=3
        )

        # Add/Remove/Move buttons
        col = row.column(align=True)
        col.operator("quickcmd.add_command", icon='ADD', text="")
        col.operator("quickcmd.duplicate_command", icon='COPYDOWN', text="")
        col.operator("quickcmd.remove_command", icon='REMOVE', text="")
        col.separator()
        col.operator("quickcmd.move_command_up", icon='TRIA_UP', text="")
        col.operator("quickcmd.move_command_down", icon='TRIA_DOWN', text="")

        # Show selected command details
        if len(scene.quick_commands) > 0 and scene.quick_commands_index < len(scene.quick_commands):
            layout.separator()

            item = scene.quick_commands[scene.quick_commands_index]

            box = layout.box()

            # Collapsible Python Code sub-panel
            code_header = box.row()
            code_header.prop(item, "show_code",
                             icon='TRIA_DOWN' if item.show_code else 'TRIA_RIGHT',
                             emboss=False,
                             text="Python Code")

            if item.show_code:
                code_box = box.box()

                # UIList showing each line with its code text
                list_row = code_box.row()
                list_row.template_list(
                    "QUICKCMD_UL_line_list",
                    "",
                    item,
                    "lines",
                    item,
                    "lines_index",
                    rows=4,
                )

                # Up/Down/Add/Remove buttons beside the list
                btn_col = list_row.column(align=True)
                btn_col.operator("quickcmd.add_line", icon='ADD', text="")
                op = btn_col.operator("quickcmd.remove_line", icon='REMOVE', text="")
                op.line_index = item.lines_index
                btn_col.separator()
                btn_col.operator("quickcmd.move_line_up", icon='TRIA_UP', text="")
                btn_col.operator("quickcmd.move_line_down", icon='TRIA_DOWN', text="")

                # Edit field for the currently selected line
                if len(item.lines) > 0 and item.lines_index < len(item.lines):
                    active_line = item.lines[item.lines_index]
                    edit_row = code_box.row()
                    edit_row.prop(active_line, "code", text="Edit")

            # ── Variables sub-panel ──
            vars_header = box.row()
            vars_header.prop(item, "show_vars",
                             icon='TRIA_DOWN' if item.show_vars else 'TRIA_RIGHT',
                             emboss=False,
                             text="Variables")

            if item.show_vars:
                vars_box = box.box()

                if len(item.variables) == 0:
                    vars_box.label(text="No variables defined", icon='INFO')
                else:
                    for i, v in enumerate(item.variables):
                        row_v = vars_box.row(align=True)

                        # Name field
                        row_v.prop(v, "var_name", text="")

                        # Type selector (compact)
                        row_v.prop(v, "var_type", text="")

                        # Value field — show the right one for the type
                        if v.var_type == 'FLOAT':
                            row_v.prop(v, "val_float", text="")
                        elif v.var_type == 'INT':
                            row_v.prop(v, "val_int", text="")
                        elif v.var_type == 'STRING':
                            row_v.prop(v, "val_string", text="")
                        else:  # BOOL
                            row_v.prop(v, "val_bool", text="")

                        # Remove button
                        op_rem = row_v.operator("quickcmd.remove_variable", text="", icon='X')
                        op_rem.var_index = i

                # Add variable button
                add_row = vars_box.row()
                add_row.operator("quickcmd.add_variable", text="Add Variable", icon='ADD')

            # Execute button
            row = box.row()
            row.scale_y = 1.5
            op = row.operator("quickcmd.execute_command", text="Execute", icon='PLAY')
            op.index = scene.quick_commands_index



# ─────────────────────────────────────────────
#  MATERIAL TOOLS
# ─────────────────────────────────────────────

class QUICKCMD_OT_clear_materials(Operator):
    bl_idname = "quickcmd.clear_materials"
    bl_label = "Clear Materials"
    bl_description = "Remove all material slots from every selected object"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected = [o for o in context.selected_objects if o.type == 'MESH']
        if not selected:
            self.report({'WARNING'}, "No mesh objects selected")
            return {'CANCELLED'}

        count = 0
        for obj in selected:
            obj.data.materials.clear()
            count += 1

        self.report({'INFO'}, f"Cleared materials on {count} object(s)")
        return {'FINISHED'}


class QUICKCMD_OT_setup_material(Operator):
    bl_idname = "quickcmd.setup_material"
    bl_label = "Setup Material"
    bl_description = "Create a new material with an image texture for each selected object"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        scene = context.scene
        size = scene.qc_mat_texture_size
        use_32bit = scene.qc_mat_32bit

        selected = [o for o in context.selected_objects if o.type == 'MESH']
        if not selected:
            self.report({'WARNING'}, "No mesh objects selected")
            return {'CANCELLED'}

        float_buffer = use_32bit

        for obj in selected:
            # Create material
            mat_name = f"{obj.name}_Mat"
            mat = bpy.data.materials.new(name=mat_name)
            mat.use_nodes = True
            nodes = mat.node_tree.nodes
            links = mat.node_tree.links

            # Clear default nodes
            nodes.clear()

            # Add Principled BSDF
            bsdf = nodes.new("ShaderNodeBsdfPrincipled")
            bsdf.location = (300, 300)

            # Add Material Output
            output = nodes.new("ShaderNodeOutputMaterial")
            output.location = (600, 300)
            links.new(bsdf.outputs["BSDF"], output.inputs["Surface"])

            # Create image texture
            img_name = f"{obj.name}_Tex"
            img = bpy.data.images.new(
                name=img_name,
                width=size,
                height=size,
                float_buffer=float_buffer
            )

            # Add Image Texture node
            tex_node = nodes.new("ShaderNodeTexImage")
            tex_node.location = (-100, 300)
            tex_node.image = img

            # Plug texture color into Base Color
            links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])

            # Assign material to object (replace all slots)
            obj.data.materials.clear()
            obj.data.materials.append(mat)

        bit_str = "32-bit" if use_32bit else "8-bit"
        self.report({'INFO'}, f"Setup {bit_str} {size}x{size} material on {len(selected)} object(s)")
        return {'FINISHED'}


class QUICKCMD_OT_calc_texel_density(Operator):
    bl_idname = "quickcmd.calc_texel_density"
    bl_label = "Calculate Texture Size"
    bl_description = (
        "Based on the active object's UVs and surface area, calculate the "
        "texture size needed to meet the desired pixels-per-unit"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        import math

        scene = context.scene
        obj = context.active_object

        # --- Validate ---
        if obj is None or obj.type != 'MESH':
            self.report({'WARNING'}, "Active object must be a mesh")
            return {'CANCELLED'}

        mesh = obj.data
        if not mesh.uv_layers:
            self.report({'WARNING'}, "Mesh has no UV maps")
            return {'CANCELLED'}

        desired_ppu = scene.qc_td_pixels_per_unit
        if desired_ppu <= 0:
            self.report({'WARNING'}, "Pixels per unit must be greater than 0")
            return {'CANCELLED'}

        # Use first UV layer
        uv_layer = mesh.uv_layers[0]

        # --- Accumulate 3D surface area and UV area ---
        # We need the evaluated/world-space mesh so scale is baked in
        depsgraph = context.evaluated_depsgraph_get()
        obj_eval = obj.evaluated_get(depsgraph)
        mesh_eval = obj_eval.to_mesh()

        # Build a quick polygon -> uv loop map
        # mesh_eval loops match uv_layer loops 1:1
        uv_data = mesh_eval.uv_layers[0].data

        total_3d_area = 0.0
        total_uv_area = 0.0

        for poly in mesh_eval.polygons:
            # 3D area (world space via matrix)
            total_3d_area += poly.area

            # UV area using the shoelace formula on the polygon's UV loop verts
            loop_uvs = [uv_data[li].uv for li in poly.loop_indices]
            n = len(loop_uvs)
            uv_area = 0.0
            for i in range(n):
                u0, v0 = loop_uvs[i]
                u1, v1 = loop_uvs[(i + 1) % n]
                uv_area += (u0 * v1) - (u1 * v0)
            total_uv_area += abs(uv_area) * 0.5

        obj_eval.to_mesh_clear()

        if total_uv_area <= 0:
            self.report({'WARNING'}, "UV area is zero — check your UVs")
            return {'CANCELLED'}

        if total_3d_area <= 0:
            self.report({'WARNING'}, "Mesh surface area is zero")
            return {'CANCELLED'}

        # --- Core formula ---
        # texel_density = (texture_size * sqrt(uv_area)) / sqrt(3d_area)
        # Solving for texture_size:
        # texture_size = desired_ppu * sqrt(3d_area / uv_area)
        raw_size = desired_ppu * math.sqrt(total_3d_area / total_uv_area)

        # Round up to next power of two
        def next_pow2(x):
            return 2 ** math.ceil(math.log2(max(x, 1)))

        recommended = next_pow2(raw_size)

        # Clamp to sane range
        recommended = int(max(1, min(recommended, 65536)))

        # Store results back onto the scene for the UI to read
        scene.qc_td_result_raw = raw_size
        scene.qc_td_result_pow2 = recommended

        self.report(
            {'INFO'},
            f"Raw: {raw_size:.1f}px  →  Recommended: {recommended}x{recommended}"
        )
        return {'FINISHED'}


class QUICKCMD_PT_material_tools(Panel):
    bl_label = "Material Tools"
    bl_idname = "QUICKCMD_PT_material_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quick Cmds"

    def draw(self, context):
        layout = self.layout
        scene = context.scene

        # Clear Materials
        layout.operator("quickcmd.clear_materials", icon='TRASH')

        layout.separator()

        # Material Setup
        box = layout.box()
        box.label(text="Material Setup", icon='MATERIAL')

        row = box.row(align=True)
        row.label(text="Texture Size:")
        row.prop(scene, "qc_mat_texture_size", text="")

        box.prop(scene, "qc_mat_32bit", text="32-bit Float Image")

        row = box.row()
        row.scale_y = 1.4
        row.operator("quickcmd.setup_material", icon='PLAY')

        layout.separator()

        # ── Texel Density Calculator ──
        box = layout.box()
        box.label(text="Texel Density Calculator", icon='TEXTURE')

        box.prop(scene, "qc_td_pixels_per_unit", text="Pixels Per Unit")

        row = box.row()
        row.scale_y = 1.3
        row.operator("quickcmd.calc_texel_density", icon='VIEWZOOM')

        # Show results if a calculation has been run
        if scene.qc_td_result_pow2 > 0:
            res_box = box.box()
            row = res_box.row()
            row.label(text="Exact:", icon='INFO')
            row.label(text=f"{scene.qc_td_result_raw:.1f} px")
            row = res_box.row()
            row.label(text="Recommended (pow2):", icon='CHECKMARK')
            sz = scene.qc_td_result_pow2
            row.label(text=f"{sz} x {sz}")


# ─────────────────────────────────────────────
#  MESH TOOLS
# ─────────────────────────────────────────────

class QUICKCMD_OT_clear_custom_normals(Operator):
    bl_idname = "quickcmd.clear_custom_normals"
    bl_label = "Clear Custom Split Normals"
    bl_description = "Remove custom split normal data from all selected mesh objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        selected = [o for o in context.selected_objects if o.type == 'MESH']
        if not selected:
            self.report({'WARNING'}, "No mesh objects selected")
            return {'CANCELLED'}

        count = 0
        for obj in selected:
            mesh = obj.data
            if mesh.has_custom_normals:
                mesh.free_normals_split()
                count += 1

        if count == 0:
            self.report({'INFO'}, "No custom normals found on selected objects")
        else:
            self.report({'INFO'}, f"Cleared custom normals on {count} object(s)")
        return {'FINISHED'}


class QUICKCMD_OT_separate_to_collection(Operator):
    bl_idname = "quickcmd.separate_to_collection"
    bl_label = "Separate to New Collection"
    bl_description = (
        "Separate selected geometry (like P > Selection) and move the "
        "new object into a named collection"
    )
    bl_options = {'REGISTER', 'UNDO'}

    collection_name: StringProperty(
        name="Collection Name",
        description="Name of the collection to move the separated object into. "
                    "Created if it does not exist.",
        default="Separated"
    )
    make_active: BoolProperty(
        name="Make New Object Active",
        description="After separating, make the newly created object the active object",
        default=False
    )

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self)

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "collection_name")
        layout.prop(self, "make_active")

    def execute(self, context):
        obj = context.active_object

        if obj is None or obj.type != 'MESH':
            self.report({'WARNING'}, "Active object must be a mesh in Edit Mode")
            return {'CANCELLED'}

        if context.mode != 'EDIT_MESH':
            self.report({'WARNING'}, "Must be in Edit Mode")
            return {'CANCELLED'}

        col_name = self.collection_name.strip()
        if not col_name:
            self.report({'WARNING'}, "Collection name cannot be empty")
            return {'CANCELLED'}

        # Snapshot objects before separate so we can identify the new one
        objects_before = set(bpy.data.objects[:])

        # Run the standard separate-by-selection operator
        result = bpy.ops.mesh.separate(type='SELECTED')
        if 'FINISHED' not in result:
            self.report({'WARNING'}, "Separate operation failed — nothing selected?")
            return {'CANCELLED'}

        # Back in Object Mode after separate; find the newly created object(s)
        objects_after = set(bpy.data.objects[:])
        new_objects = list(objects_after - objects_before)

        if not new_objects:
            self.report({'WARNING'}, "No new object was created by the separate")
            return {'CANCELLED'}

        # Get or create the target collection
        target_col = bpy.data.collections.get(col_name)
        if target_col is None:
            target_col = bpy.data.collections.new(col_name)
            context.scene.collection.children.link(target_col)

        # Move each new object into the target collection
        for new_obj in new_objects:
            # Unlink from every collection it currently belongs to
            for col in list(new_obj.users_collection):
                col.objects.unlink(new_obj)
            # Link into the target collection
            target_col.objects.link(new_obj)

        # Optionally make the (first) new object active
        if self.make_active and new_objects:
            context.view_layer.objects.active = new_objects[0]
            for o in context.selected_objects:
                o.select_set(False)
            new_objects[0].select_set(True)

        self.report(
            {'INFO'},
            f"Separated {len(new_objects)} object(s) → '{col_name}'"
        )
        return {'FINISHED'}


class QUICKCMD_PT_mesh_tools(Panel):
    bl_label = "Mesh Tools"
    bl_idname = "QUICKCMD_PT_mesh_tools"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "Quick Cmds"

    def draw(self, context):
        layout = self.layout
        layout.operator("quickcmd.clear_custom_normals", icon='NORMALS_FACE')

        layout.separator()

        # Separate to Collection — only meaningful in Edit Mode
        col = layout.column(align=True)
        col.operator("quickcmd.separate_to_collection", icon='OUTLINER_COLLECTION')


# ─────────────────────────────────────────────
#  ATTRIBUTE TOOLS
# ─────────────────────────────────────────────

# ── Enums ──────────────────────────────────────────────────────────────────

ATTR_DOMAIN_ITEMS = [
    ('POINT',        'Vertex',       'Per-vertex attribute'),
    ('EDGE',         'Edge',         'Per-edge attribute'),
    ('FACE',         'Face',         'Per-face attribute'),
    ('CORNER',       'Face Corner',  'Per-face-corner attribute'),
    ('LAYER',        'Layer',        'Layer domain (UV maps etc.)'),
]

ATTR_TYPE_ITEMS = [
    ('FLOAT',                    'Float',                    'Single float value'),
    ('INT',                      'Integer',                  'Single integer value'),
    ('FLOAT_VECTOR',             'Vector',                   '3-component float vector'),
    ('FLOAT_COLOR',              'Color',                    'RGBA float colour'),
    ('BYTE_COLOR',               'Byte Color',               'RGBA byte colour'),
    ('STRING',                   'String',                   'Text string'),
    ('BOOLEAN',                  'Boolean',                  'True / False'),
    ('FLOAT2',                   '2D Vector',                '2-component float vector'),
    ('INT8',                     '8-Bit Integer',            '8-bit integer (-128 to 127)'),
    ('INT16_2D',                 '2D 16-Bit Integer Vector', '2-component 16-bit integer vector'),
    ('INT2',                     '2D Integer Vector',        '2-component integer vector'),
    ('QUATERNION',               'Quaternion',               '4-component quaternion (W X Y Z)'),
    ('FLOAT4X4',                 '4x4 Matrix',               '4×4 float matrix'),
]

# Types that cannot be created via the Python API in most Blender versions
_UNSUPPORTED_TYPES   = {'STRING'}
_UNSUPPORTED_DOMAINS = {'LAYER'}


# ── PropertyGroup stored per-object ────────────────────────────────────────

class ATTRTOOL_AttributeValueProps(bpy.types.PropertyGroup):
    """Holds the 'staging' value the user wants to assign."""

    # --- scalar ---
    val_float:   bpy.props.FloatProperty(name="Value", default=0.0, precision=4)
    val_int:     bpy.props.IntProperty(name="Value", default=0)
    val_int8:    bpy.props.IntProperty(name="Value", default=0, min=-128, max=127)
    val_bool:    bpy.props.BoolProperty(name="Value", default=False)
    val_string:  bpy.props.StringProperty(name="Value", default="")

    # --- 2-component ---
    val_float2:  bpy.props.FloatVectorProperty(name="Value", size=2, default=(0.0, 0.0))
    val_int2:    bpy.props.IntVectorProperty(name="Value",   size=2, default=(0, 0))
    val_int16_2: bpy.props.IntVectorProperty(name="Value",   size=2, default=(0, 0))

    # --- 3-component ---
    val_vec3:    bpy.props.FloatVectorProperty(name="Value", size=3, default=(0.0, 0.0, 0.0))

    # --- 4-component ---
    val_color:   bpy.props.FloatVectorProperty(
                     name="Value", size=4, default=(1.0, 1.0, 1.0, 1.0),
                     min=0.0, max=1.0, subtype='COLOR')
    val_bcolor:  bpy.props.FloatVectorProperty(
                     name="Value", size=4, default=(1.0, 1.0, 1.0, 1.0),
                     min=0.0, max=1.0, subtype='COLOR')
    val_quat:    bpy.props.FloatVectorProperty(
                     name="Value", size=4, default=(1.0, 0.0, 0.0, 0.0),
                     subtype='QUATERNION')

    # --- 16-component (4×4 matrix stored flat, row-major) ---
    val_mat4x4:  bpy.props.FloatVectorProperty(
                     name="Value", size=16,
                     default=(1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1))

    # UI toggle for matrix collapse
    mat4x4_expanded: bpy.props.BoolProperty(name="Expand Matrix", default=False)


class ATTRTOOL_SceneProps(bpy.types.PropertyGroup):
    """Scene-level UI state for the Attribute Tools panel."""
    active_index: bpy.props.IntProperty(name="Active Attribute Index", default=0)
    attr_domain:  bpy.props.EnumProperty(
                      name="Domain", items=ATTR_DOMAIN_ITEMS, default='POINT')
    attr_type:    bpy.props.EnumProperty(
                      name="Data Type", items=ATTR_TYPE_ITEMS, default='FLOAT')
    value_props:  bpy.props.PointerProperty(type=ATTRTOOL_AttributeValueProps)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_mesh_attributes(obj):
    """Return list of user-facing mesh attributes (skip internal Blender ones)."""
    INTERNAL = {'.corner_vert', '.corner_edge', '.edge_verts', '.poly_offset_index',
                'position', 'sharp_face', 'sharp_edge', 'material_index',
                '.select_vert', '.select_edge', '.select_poly',
                '.hide_vert', '.hide_edge', '.hide_poly',
                'crease_vert', 'crease_edge'}
    if obj is None or obj.type != 'MESH':
        return []
    return [a for a in obj.data.attributes if a.name not in INTERNAL]


def _active_attr(context):
    """Return the currently active attribute or None."""
    obj = context.active_object
    attrs = _get_mesh_attributes(obj)
    sp = context.scene.attrtool
    if not attrs or sp.active_index >= len(attrs):
        return None
    return attrs[sp.active_index]


def _value_for_attr(attr, vp):
    """
    Given an attribute and its staging ValueProps, return the Python value
    (scalar, tuple, or list) to write into the attribute data.
    """
    t = attr.data_type
    if t == 'FLOAT':         return vp.val_float
    if t == 'INT':           return vp.val_int
    if t == 'INT8':          return vp.val_int8
    if t == 'BOOLEAN':       return vp.val_bool
    if t == 'STRING':        return vp.val_string
    if t == 'FLOAT2':        return tuple(vp.val_float2)
    if t == 'INT2':          return tuple(vp.val_int2)
    if t == 'INT16_2D':      return tuple(vp.val_int16_2)
    if t == 'FLOAT_VECTOR':  return tuple(vp.val_vec3)
    if t == 'FLOAT_COLOR':   return tuple(vp.val_color)
    if t == 'BYTE_COLOR':    return tuple(vp.val_bcolor)
    if t == 'QUATERNION':    return tuple(vp.val_quat)
    if t == 'FLOAT4X4':
        m = vp.val_mat4x4
        return [list(m[r*4:(r+1)*4]) for r in range(4)]
    return None


def _domain_elements(bm, domain):
    """Return the selected bmesh elements for the given domain."""
    if domain == 'POINT':
        return [v for v in bm.verts if v.select]
    if domain == 'EDGE':
        return [e for e in bm.edges if e.select]
    if domain == 'FACE':
        return [f for f in bm.faces if f.select]
    if domain == 'CORNER':
        loops = []
        for f in bm.faces:
            if f.select:
                loops.extend(f.loops)
        return loops
    return []


# Maps attribute data_type to the bmesh layer collection and write-attribute
_BM_LAYER_MAP = {
    # (bm_layer_collection_name, layer_type_name, write_attr)
    # write_attr is the attribute on the layer element: None means direct assignment
    'FLOAT':       ('verts',  'float',        None),
    'INT':         ('verts',  'int',           None),
    'INT8':        ('verts',  'int',           None),   # stored as int in bmesh
    'BOOLEAN':     ('verts',  'bool',          None),
    'FLOAT_VECTOR':('verts',  'float_vector',  None),
    'FLOAT2':      ('loops',  'uv',            'uv'),   # UV = float2 on loops
    'FLOAT_COLOR': ('loops',  'float_color',   None),
    'BYTE_COLOR':  ('loops',  'color',         None),
    'INT2':        ('verts',  'int',           None),   # no native int2 layer; fallback
}


def _get_bm_layer(bm, attr_name, domain, dtype):
    """
    Return the bmesh CustomDataLayer for the named attribute, or None.
    We look in the collection that matches the domain.
    """
    domain_to_collection = {
        'POINT':  bm.verts,
        'EDGE':   bm.edges,
        'FACE':   bm.faces,
        'CORNER': bm.loops,
    }
    col = domain_to_collection.get(domain)
    if col is None:
        return None

    layers = col.layers

    # Try every layer type in order until we find one with our attribute name
    for layer_type_name in ('float', 'int', 'bool', 'string',
                             'float_vector', 'float_color', 'color',
                             'uv', 'float2'):
        layer_col = getattr(layers, layer_type_name, None)
        if layer_col is None:
            continue
        layer = layer_col.get(attr_name)
        if layer is not None:
            return layer, layer_type_name

    return None, None


def _write_layer_value(elem, layer, layer_type, value):
    """Write value into elem[layer], handling tuple/vector coercion."""
    if layer_type == 'uv':
        elem[layer].uv = value
    else:
        try:
            elem[layer] = value
        except TypeError:
            # Some layer types need the value as a flat sequence
            import mathutils
            if hasattr(value, '__iter__'):
                elem[layer] = type(elem[layer])(value)
            else:
                elem[layer] = value


# ── UIList ───────────────────────────────────────────────────────────────────

class ATTRTOOL_UL_attributes(bpy.types.UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname, index):
        if self.layout_type in {'DEFAULT', 'COMPACT'}:
            row = layout.row(align=True)
            # Editable name (double-click triggers rename in Blender's UIList)
            row.prop(item, "name", text="", emboss=False, icon='SPREADSHEET')
            # Show domain + type as subtle labels
            row.label(text=f"{item.domain}  ·  {item.data_type}")
        elif self.layout_type == 'GRID':
            layout.label(text="", icon='SPREADSHEET')


# ── Operators ────────────────────────────────────────────────────────────────

class ATTRTOOL_OT_add_attribute(bpy.types.Operator):
    bl_idname  = "attrtool.add_attribute"
    bl_label   = "Add Attribute"
    bl_description = "Add a new attribute to the active mesh"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            self.report({'WARNING'}, "Active object must be a mesh")
            return {'CANCELLED'}

        sp = context.scene.attrtool
        domain = sp.attr_domain
        dtype  = sp.attr_type

        if domain in _UNSUPPORTED_DOMAINS:
            self.report({'WARNING'}, f"Domain '{domain}' cannot be created via the API")
            return {'CANCELLED'}
        if dtype in _UNSUPPORTED_TYPES:
            self.report({'WARNING'}, f"Type '{dtype}' cannot be created via the API")
            return {'CANCELLED'}

        mesh = obj.data
        # Generate a unique name
        base = "Attribute"
        existing = {a.name for a in mesh.attributes}
        name = base
        counter = 1
        while name in existing:
            name = f"{base}.{counter:03d}"
            counter += 1

        try:
            mesh.attributes.new(name=name, type=dtype, domain=domain)
        except Exception as e:
            self.report({'ERROR'}, f"Could not create attribute: {e}")
            return {'CANCELLED'}

        # Select the new attribute
        attrs = _get_mesh_attributes(obj)
        for i, a in enumerate(attrs):
            if a.name == name:
                sp.active_index = i
                break

        self.report({'INFO'}, f"Created attribute '{name}'")
        return {'FINISHED'}


class ATTRTOOL_OT_remove_attribute(bpy.types.Operator):
    bl_idname  = "attrtool.remove_attribute"
    bl_label   = "Remove Attribute"
    bl_description = "Remove the selected attribute from the active mesh"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        obj = context.active_object
        attr = _active_attr(context)
        if attr is None:
            self.report({'WARNING'}, "No attribute selected")
            return {'CANCELLED'}

        name = attr.name
        try:
            obj.data.attributes.remove(attr)
        except Exception as e:
            self.report({'ERROR'}, f"Could not remove attribute: {e}")
            return {'CANCELLED'}

        sp = context.scene.attrtool
        sp.active_index = max(0, sp.active_index - 1)
        self.report({'INFO'}, f"Removed attribute '{name}'")
        return {'FINISHED'}


class ATTRTOOL_OT_assign(bpy.types.Operator):
    bl_idname  = "attrtool.assign"
    bl_label   = "Assign"
    bl_description = (
        "Write the staged value to the attribute on all selected "
        "mesh elements matching the attribute's domain"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        import bmesh

        obj  = context.active_object
        attr = _active_attr(context)

        if attr is None:
            self.report({'WARNING'}, "No attribute selected")
            return {'CANCELLED'}

        domain = attr.domain

        if domain == 'LAYER':
            self.report({'WARNING'}, "Cannot assign to Layer domain attributes via this panel")
            return {'CANCELLED'}

        if context.mode != 'EDIT_MESH':
            self.report({'WARNING'}, "Enter Edit Mode to assign attributes")
            return {'CANCELLED'}

        vp    = context.scene.attrtool.value_props
        value = _value_for_attr(attr, vp)

        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        elems = _domain_elements(bm, domain)
        if not elems:
            self.report({'WARNING'}, "Nothing selected in the attribute's domain")
            return {'CANCELLED'}

        layer, layer_type = _get_bm_layer(bm, attr.name, domain, attr.data_type)
        if layer is None:
            self.report({'ERROR'},
                f"Cannot find bmesh layer for '{attr.name}' "
                f"(type '{attr.data_type}' may not be editable in Edit Mode via bmesh).")
            return {'CANCELLED'}

        for elem in elems:
            _write_layer_value(elem, layer, layer_type, value)

        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        self.report({'INFO'}, f"Assigned to {len(elems)} element(s)")
        return {'FINISHED'}


class ATTRTOOL_OT_remove_value(bpy.types.Operator):
    bl_idname  = "attrtool.remove_value"
    bl_label   = "Remove"
    bl_description = (
        "Reset the attribute value to zero/false on all selected "
        "mesh elements matching the attribute's domain"
    )
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        import bmesh

        obj  = context.active_object
        attr = _active_attr(context)

        if attr is None:
            self.report({'WARNING'}, "No attribute selected")
            return {'CANCELLED'}

        if context.mode != 'EDIT_MESH':
            self.report({'WARNING'}, "Enter Edit Mode to remove attribute values")
            return {'CANCELLED'}

        domain = attr.domain
        dtype  = attr.data_type

        bm = bmesh.from_edit_mesh(obj.data)
        bm.verts.ensure_lookup_table()
        bm.edges.ensure_lookup_table()
        bm.faces.ensure_lookup_table()

        elems = _domain_elements(bm, domain)
        if not elems:
            self.report({'WARNING'}, "Nothing selected")
            return {'CANCELLED'}

        layer, layer_type = _get_bm_layer(bm, attr.name, domain, dtype)
        if layer is None:
            self.report({'ERROR'},
                f"Cannot find bmesh layer for '{attr.name}'.")
            return {'CANCELLED'}

        # Build the appropriate zero value for this type
        zero_map = {
            'FLOAT':        0.0,
            'INT':          0,
            'INT8':         0,
            'BOOLEAN':      False,
            'FLOAT_VECTOR': (0.0, 0.0, 0.0),
            'FLOAT2':       (0.0, 0.0),
            'INT2':         (0, 0),
            'INT16_2D':     (0, 0),
            'FLOAT_COLOR':  (0.0, 0.0, 0.0, 0.0),
            'BYTE_COLOR':   (0.0, 0.0, 0.0, 0.0),
            'QUATERNION':   (1.0, 0.0, 0.0, 0.0),
            'FLOAT4X4':     [0.0] * 16,
        }
        zero = zero_map.get(dtype, 0)

        for elem in elems:
            _write_layer_value(elem, layer, layer_type, zero)

        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        self.report({'INFO'}, f"Reset {len(elems)} element(s)")
        return {'FINISHED'}


class ATTRTOOL_OT_fill_all(bpy.types.Operator):
    bl_idname  = "attrtool.fill_all"
    bl_label   = "Fill All"
    bl_description = "Write the staged value to every element in the mesh for this attribute"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        import bmesh

        obj  = context.active_object
        attr = _active_attr(context)

        if attr is None:
            self.report({'WARNING'}, "No attribute selected")
            return {'CANCELLED'}

        if obj is None or obj.type != 'MESH':
            self.report({'WARNING'}, "Active object must be a mesh")
            return {'CANCELLED'}

        vp    = context.scene.attrtool.value_props
        value = _value_for_attr(attr, vp)
        domain = attr.domain

        # Fill All always works: exit Edit Mode if needed, write via attr.data, return
        was_edit = (context.mode == 'EDIT_MESH')
        if was_edit:
            bpy.ops.object.mode_set(mode='OBJECT')

        dtype = attr.data_type
        count = 0
        for elem in attr.data:
            try:
                if dtype in ('FLOAT', 'INT', 'INT8', 'BOOLEAN', 'STRING', 'QUATERNION'):
                    elem.value = value
                elif dtype in ('FLOAT_VECTOR', 'FLOAT2', 'INT2', 'INT16_2D', 'FLOAT4X4'):
                    elem.vector = value
                elif dtype in ('FLOAT_COLOR', 'BYTE_COLOR'):
                    elem.color = value
                else:
                    elem.value = value
            except AttributeError:
                try:    elem.vector = value
                except AttributeError:
                    try:    elem.color = value
                    except: pass
            count += 1

        obj.data.update()

        if was_edit:
            bpy.ops.object.mode_set(mode='EDIT')

        self.report({'INFO'}, f"Filled {count} element(s)")
        return {'FINISHED'}


# ── Value input drawing helper ───────────────────────────────────────────────

def _draw_value_input(layout, attr, vp):
    """Draw the appropriate value widget(s) for the attribute's data type."""
    dtype = attr.data_type

    if dtype == 'FLOAT':
        layout.prop(vp, "val_float", text="Value")

    elif dtype == 'INT':
        layout.prop(vp, "val_int", text="Value")

    elif dtype == 'INT8':
        layout.prop(vp, "val_int8", text="Value  (−128 – 127)")

    elif dtype == 'BOOLEAN':
        layout.prop(vp, "val_bool", text="Value")

    elif dtype == 'STRING':
        layout.prop(vp, "val_string", text="Value")

    elif dtype == 'FLOAT_VECTOR':
        col = layout.column(align=True)
        col.label(text="Value (X Y Z):")
        col.prop(vp, "val_vec3", index=0, text="X")
        col.prop(vp, "val_vec3", index=1, text="Y")
        col.prop(vp, "val_vec3", index=2, text="Z")

    elif dtype == 'FLOAT2':
        col = layout.column(align=True)
        col.label(text="Value (X Y):")
        col.prop(vp, "val_float2", index=0, text="X")
        col.prop(vp, "val_float2", index=1, text="Y")

    elif dtype == 'INT2':
        col = layout.column(align=True)
        col.label(text="Value (X Y):")
        col.prop(vp, "val_int2", index=0, text="X")
        col.prop(vp, "val_int2", index=1, text="Y")

    elif dtype == 'INT16_2D':
        col = layout.column(align=True)
        col.label(text="Value (X Y):")
        col.prop(vp, "val_int16_2", index=0, text="X")
        col.prop(vp, "val_int16_2", index=1, text="Y")

    elif dtype == 'FLOAT_COLOR':
        layout.label(text="Value (RGBA):")
        layout.prop(vp, "val_color",  text="")

    elif dtype == 'BYTE_COLOR':
        layout.label(text="Value (RGBA):")
        layout.prop(vp, "val_bcolor", text="")

    elif dtype == 'QUATERNION':
        col = layout.column(align=True)
        col.label(text="Value (W X Y Z):")
        col.prop(vp, "val_quat", index=0, text="W")
        col.prop(vp, "val_quat", index=1, text="X")
        col.prop(vp, "val_quat", index=2, text="Y")
        col.prop(vp, "val_quat", index=3, text="Z")

    elif dtype == 'FLOAT4X4':
        row = layout.row()
        row.prop(vp, "mat4x4_expanded",
                 icon='TRIA_DOWN' if vp.mat4x4_expanded else 'TRIA_RIGHT',
                 emboss=False, text="4×4 Matrix Value")
        if vp.mat4x4_expanded:
            grid = layout.column(align=True)
            labels = ['C0', 'C1', 'C2', 'C3']
            for r in range(4):
                row4 = grid.row(align=True)
                row4.label(text=f"R{r}:")
                for c in range(4):
                    row4.prop(vp, "val_mat4x4", index=r*4+c, text=labels[c])

    else:
        layout.label(text=f"(no value editor for type {dtype})", icon='INFO')


# ── Panel ────────────────────────────────────────────────────────────────────

class ATTRTOOL_PT_panel(bpy.types.Panel):
    bl_label      = "Attribute Tools"
    bl_idname     = "ATTRTOOL_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category   = "Quick Cmds"

    def draw(self, context):
        layout = self.layout
        scene  = context.scene
        sp     = scene.attrtool
        obj    = context.active_object
        mode   = context.mode

        # ── Guard: need a mesh object ──────────────────────────────────────
        if obj is None or obj.type != 'MESH':
            layout.label(text="Select a mesh object", icon='INFO')
            return

        mesh  = obj.data
        attrs = _get_mesh_attributes(obj)

        # ── Attribute list ─────────────────────────────────────────────────
        list_row = layout.row()
        list_row.template_list(
            "ATTRTOOL_UL_attributes", "",
            mesh, "attributes",
            sp,   "active_index",
            rows=5,
        )

        btn_col = list_row.column(align=True)
        btn_col.operator("attrtool.add_attribute",    icon='ADD',    text="")
        btn_col.operator("attrtool.remove_attribute", icon='REMOVE', text="")

        # ── New-attribute settings (shown when list is focused) ────────────
        new_box = layout.box()
        new_box.label(text="New Attribute Settings", icon='SETTINGS')
        new_box.prop(sp, "attr_domain", text="Domain")
        new_box.prop(sp, "attr_type",   text="Type")

        layout.separator()

        # ── Selected attribute details + value input ───────────────────────
        attr = _active_attr(context)

        if attr is None:
            layout.label(text="No attribute selected", icon='INFO')
            return

        detail_box = layout.box()
        # Header row: name (read-only label) + domain/type badges
        hdr = detail_box.row()
        hdr.label(text=attr.name, icon='SPREADSHEET')
        hdr.label(text=f"{attr.domain}  ·  {attr.data_type}")

        detail_box.separator(factor=0.5)

        # Value input, dynamically drawn per type
        vp = sp.value_props
        _draw_value_input(detail_box, attr, vp)

        layout.separator()

        # ── Assign / Remove / Fill All ─────────────────────────────────────
        in_edit = (mode == 'EDIT_MESH')

        assign_box = layout.box()

        if not in_edit:
            assign_box.label(text="Enter Edit Mode to assign / remove", icon='INFO')

        btn_row = assign_box.row(align=True)
        btn_row.scale_y = 1.4
        btn_row.enabled = in_edit
        btn_row.operator("attrtool.assign",       icon='CHECKMARK', text="Assign")
        btn_row.operator("attrtool.remove_value", icon='X',         text="Remove")

        # Fill All — always available in Object or Edit Mode
        fill_row = assign_box.row()
        fill_row.scale_y = 1.2
        fill_row.operator("attrtool.fill_all", icon='SNAP_FACE', text="Fill All")


# ─────────────────────────────────────────────
#  SCENE AUDIT
# ─────────────────────────────────────────────

class SceneAuditResult(bpy.types.PropertyGroup):
    """Stores a single object name (and optional extra info) for an audit result entry."""
    object_name: bpy.props.StringProperty(name="Object Name", default="")
    extra_info:  bpy.props.StringProperty(name="Extra Info",  default="")


class SceneAuditProps(bpy.types.PropertyGroup):
    # ── Audit options ──────────────────────────────────────────────────────
    check_missing_materials: BoolProperty(
        name="Missing Materials",
        description="Find mesh objects with no material slots, or slots with no material assigned",
        default=True
    )
    check_modifiers: BoolProperty(
        name="Objects with Modifiers",
        description="Find any object that has one or more modifiers",
        default=True
    )
    check_lights: BoolProperty(
        name="Lights",
        description="List all light objects in the scene",
        default=True
    )
    check_unapplied_scale: BoolProperty(
        name="Unapplied Scale",
        description="Find mesh objects whose scale is not (1, 1, 1)",
        default=True
    )
    check_no_uvs: BoolProperty(
        name="No UV Maps",
        description="Find mesh objects with no UV layers",
        default=True
    )
    check_high_poly: BoolProperty(
        name="High Poly",
        description="Find mesh objects exceeding the face count threshold",
        default=True
    )
    high_poly_threshold: IntProperty(
        name="Face Threshold",
        description="Flag meshes with more faces than this value",
        default=5000,
        min=1,
        soft_max=500000
    )

    # ── Results (populated by the audit operator) ──────────────────────────
    results_missing_materials: CollectionProperty(type=SceneAuditResult)
    results_modifiers:         CollectionProperty(type=SceneAuditResult)
    results_lights:            CollectionProperty(type=SceneAuditResult)
    results_unapplied_scale:   CollectionProperty(type=SceneAuditResult)
    results_no_uvs:            CollectionProperty(type=SceneAuditResult)
    results_high_poly:         CollectionProperty(type=SceneAuditResult)

    # ── UI state ───────────────────────────────────────────────────────────
    has_results: BoolProperty(default=False)
    show_options:           BoolProperty(name="Audit Options",        default=True)
    show_missing_materials: BoolProperty(name="Missing Materials",    default=True)
    show_modifiers:         BoolProperty(name="Objects w/ Modifiers", default=True)
    show_lights:            BoolProperty(name="Lights",               default=True)
    show_unapplied_scale:   BoolProperty(name="Unapplied Scale",      default=True)
    show_no_uvs:            BoolProperty(name="No UV Maps",           default=True)
    show_high_poly:         BoolProperty(name="High Poly",            default=True)


class SCENEAUDIT_OT_select_object(Operator):
    """Select a single object in the scene by name."""
    bl_idname = "sceneaudit.select_object"
    bl_label = "Select Object"
    bl_description = "Deselect everything and select this object"

    object_name: StringProperty()

    def execute(self, context):
        obj = bpy.data.objects.get(self.object_name)
        if obj is None:
            self.report({'WARNING'}, f"Object '{self.object_name}' not found in scene")
            return {'CANCELLED'}

        # Deselect all via view_layer (avoids operator context requirements)
        for o in context.view_layer.objects:
            o.select_set(False)

        obj.select_set(True)
        context.view_layer.objects.active = obj
        return {'FINISHED'}


class SCENEAUDIT_OT_select_all_in_category(Operator):
    """Select all objects in an audit result category."""
    bl_idname = "sceneaudit.select_all_in_category"
    bl_label = "Select All"
    bl_description = "Select all objects in this audit category"

    category: StringProperty()

    def execute(self, context):
        audit = context.scene.scene_audit
        results = getattr(audit, f"results_{self.category}", None)
        if results is None:
            return {'CANCELLED'}

        for o in context.view_layer.objects:
            o.select_set(False)

        last = None
        for r in results:
            obj = bpy.data.objects.get(r.object_name)
            if obj:
                obj.select_set(True)
                last = obj

        if last:
            context.view_layer.objects.active = last

        self.report({'INFO'}, f"Selected {len(results)} object(s)")
        return {'FINISHED'}


class SCENEAUDIT_OT_run_audit(Operator):
    """Scan the active scene and populate the audit result lists."""
    bl_idname = "sceneaudit.run_audit"
    bl_label = "Run Scene Audit"
    bl_description = "Scan the scene and populate audit results below"
    bl_options = {'REGISTER'}

    def execute(self, context):
        scene = context.scene
        audit = scene.scene_audit

        # Clear previous results
        audit.results_missing_materials.clear()
        audit.results_modifiers.clear()
        audit.results_lights.clear()
        audit.results_unapplied_scale.clear()
        audit.results_no_uvs.clear()
        audit.results_high_poly.clear()

        for obj in scene.objects:

            # ── Missing materials (mesh only) ──────────────────────────────
            if audit.check_missing_materials and obj.type == 'MESH':
                no_slots    = len(obj.material_slots) == 0
                empty_slots = any(slot.material is None for slot in obj.material_slots)
                if no_slots or empty_slots:
                    r = audit.results_missing_materials.add()
                    r.object_name = obj.name

            # ── Objects with modifiers ─────────────────────────────────────
            if audit.check_modifiers and len(obj.modifiers) > 0:
                r = audit.results_modifiers.add()
                r.object_name = obj.name

            # ── Lights ────────────────────────────────────────────────────
            if audit.check_lights and obj.type == 'LIGHT':
                r = audit.results_lights.add()
                r.object_name = obj.name

            # ── Unapplied scale (mesh only) ────────────────────────────────
            if audit.check_unapplied_scale and obj.type == 'MESH':
                if any(abs(s - 1.0) > 1e-5 for s in obj.scale):
                    r = audit.results_unapplied_scale.add()
                    r.object_name = obj.name
                    r.extra_info  = f"({obj.scale.x:.3f}, {obj.scale.y:.3f}, {obj.scale.z:.3f})"

            # ── No UV maps (mesh only) ─────────────────────────────────────
            if audit.check_no_uvs and obj.type == 'MESH':
                if len(obj.data.uv_layers) == 0:
                    r = audit.results_no_uvs.add()
                    r.object_name = obj.name

            # ── High poly (mesh only) ──────────────────────────────────────
            if audit.check_high_poly and obj.type == 'MESH':
                face_count = len(obj.data.polygons)
                if face_count > audit.high_poly_threshold:
                    r = audit.results_high_poly.add()
                    r.object_name = obj.name
                    r.extra_info  = f"{face_count:,} faces"

        audit.has_results = True

        total = (len(audit.results_missing_materials) +
                 len(audit.results_modifiers) +
                 len(audit.results_lights) +
                 len(audit.results_unapplied_scale) +
                 len(audit.results_no_uvs) +
                 len(audit.results_high_poly))
        self.report({'INFO'}, f"Scene audit complete — {total} item(s) flagged")
        return {'FINISHED'}


class SCENEAUDIT_PT_panel(Panel):
    bl_label = "Scene Audit"
    bl_idname = "SCENEAUDIT_PT_panel"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Quick Cmds"

    # ── Helper: draw a collapsible result section ──────────────────────────
    @staticmethod
    def _draw_result_section(layout, audit, label, icon, results, show_attr, category):
        box = layout.box()

        header = box.row()
        header.prop(
            audit, show_attr,
            icon='TRIA_DOWN' if getattr(audit, show_attr) else 'TRIA_RIGHT',
            emboss=False,
            text=f"{label}  ({len(results)})"
        )

        if not getattr(audit, show_attr):
            return

        if len(results) == 0:
            box.label(text="None found", icon='CHECKMARK')
        else:
            # Select All button
            sel_row = box.row()
            op = sel_row.operator("sceneaudit.select_all_in_category",
                                  text="Select All", icon='RESTRICT_SELECT_OFF')
            op.category = category

            col = box.column(align=True)
            for r in results:
                label_text = f"{r.object_name}  {r.extra_info}" if r.extra_info else r.object_name
                op = col.operator("sceneaudit.select_object", text=label_text, icon=icon)
                op.object_name = r.object_name

    # ── Panel draw ─────────────────────────────────────────────────────────
    def draw(self, context):
        layout = self.layout
        audit  = context.scene.scene_audit

        # ── Options box ───────────────────────────────────────────────────
        opt_box = layout.box()
        opt_header = opt_box.row()
        opt_header.prop(
            audit, "show_options",
            icon='TRIA_DOWN' if audit.show_options else 'TRIA_RIGHT',
            emboss=False,
            text="Audit Options"
        )

        if audit.show_options:
            opt_box.prop(audit, "check_missing_materials")
            opt_box.prop(audit, "check_modifiers")
            opt_box.prop(audit, "check_lights")
            opt_box.prop(audit, "check_unapplied_scale")
            opt_box.prop(audit, "check_no_uvs")

            # High poly with inline threshold field
            hp_row = opt_box.row(align=True)
            hp_row.prop(audit, "check_high_poly")
            sub = hp_row.row(align=True)
            sub.enabled = audit.check_high_poly
            sub.prop(audit, "high_poly_threshold", text="")

        # ── Run button ────────────────────────────────────────────────────
        run_row = layout.row()
        run_row.scale_y = 1.5
        run_row.operator("sceneaudit.run_audit", text="Run Audit", icon='VIEWZOOM')

        if not audit.has_results:
            return

        layout.separator()

        # ── Result sections ───────────────────────────────────────────────
        if audit.check_missing_materials:
            self._draw_result_section(
                layout, audit,
                label="Missing Materials", icon='MATERIAL',
                results=audit.results_missing_materials,
                show_attr="show_missing_materials",
                category="missing_materials"
            )

        if audit.check_modifiers:
            self._draw_result_section(
                layout, audit,
                label="Has Modifiers", icon='MODIFIER',
                results=audit.results_modifiers,
                show_attr="show_modifiers",
                category="modifiers"
            )

        if audit.check_lights:
            self._draw_result_section(
                layout, audit,
                label="Lights", icon='LIGHT',
                results=audit.results_lights,
                show_attr="show_lights",
                category="lights"
            )

        if audit.check_unapplied_scale:
            self._draw_result_section(
                layout, audit,
                label="Unapplied Scale", icon='OBJECT_ORIGIN',
                results=audit.results_unapplied_scale,
                show_attr="show_unapplied_scale",
                category="unapplied_scale"
            )

        if audit.check_no_uvs:
            self._draw_result_section(
                layout, audit,
                label="No UV Maps", icon='UV',
                results=audit.results_no_uvs,
                show_attr="show_no_uvs",
                category="no_uvs"
            )

        if audit.check_high_poly:
            self._draw_result_section(
                layout, audit,
                label="High Poly", icon='MESH_DATA',
                results=audit.results_high_poly,
                show_attr="show_high_poly",
                category="high_poly"
            )


# Registration
classes = (
    QuickCommandLine,
    QuickCommandVariable,
    QuickCommandItem,
    QUICKCMD_OT_execute_command,
    QUICKCMD_OT_add_command,
    QUICKCMD_OT_remove_command,
    QUICKCMD_OT_move_command_up,
    QUICKCMD_OT_move_command_down,
    QUICKCMD_OT_add_line,
    QUICKCMD_OT_remove_line,
    QUICKCMD_OT_move_line_up,
    QUICKCMD_OT_move_line_down,
    QUICKCMD_OT_duplicate_command,
    QUICKCMD_OT_add_variable,
    QUICKCMD_OT_remove_variable,
    QUICKCMD_UL_command_list,
    QUICKCMD_UL_line_list,
    QUICKCMD_PT_main_panel,
    QUICKCMD_OT_clear_materials,
    QUICKCMD_OT_setup_material,
    QUICKCMD_OT_calc_texel_density,
    QUICKCMD_PT_material_tools,
    QUICKCMD_OT_clear_custom_normals,
    QUICKCMD_OT_separate_to_collection,
    QUICKCMD_PT_mesh_tools,
    # Attribute Tools
    ATTRTOOL_AttributeValueProps,
    ATTRTOOL_SceneProps,
    ATTRTOOL_UL_attributes,
    ATTRTOOL_OT_add_attribute,
    ATTRTOOL_OT_remove_attribute,
    ATTRTOOL_OT_assign,
    ATTRTOOL_OT_remove_value,
    ATTRTOOL_OT_fill_all,
    ATTRTOOL_PT_panel,
    # Scene Audit
    SceneAuditResult,
    SceneAuditProps,
    SCENEAUDIT_OT_select_object,
    SCENEAUDIT_OT_select_all_in_category,
    SCENEAUDIT_OT_run_audit,
    SCENEAUDIT_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    bpy.types.Scene.quick_commands = CollectionProperty(type=QuickCommandItem)
    bpy.types.Scene.quick_commands_index = IntProperty(default=0)

    # Material Tools properties
    bpy.types.Scene.qc_mat_texture_size = IntProperty(
        name="Texture Size",
        description="Width and height of the created image texture",
        default=1024,
        min=1,
        max=16384,
        subtype='PIXEL'
    )
    bpy.types.Scene.qc_mat_32bit = BoolProperty(
        name="32-bit Float",
        description="Create a 32-bit float image instead of 8-bit",
        default=False
    )

    # Texel Density properties
    bpy.types.Scene.qc_td_pixels_per_unit = IntProperty(
        name="Pixels Per Unit",
        description="Desired number of texture pixels per Blender unit of surface",
        default=512,
        min=1,
        max=65536,
    )
    bpy.types.Scene.qc_td_result_raw = bpy.props.FloatProperty(
        name="Raw Result",
        default=0.0
    )
    bpy.types.Scene.qc_td_result_pow2 = IntProperty(
        name="Power-of-2 Result",
        default=0
    )

    # Attribute Tools
    bpy.types.Scene.attrtool = bpy.props.PointerProperty(type=ATTRTOOL_SceneProps)

    # Scene Audit
    bpy.types.Scene.scene_audit = bpy.props.PointerProperty(type=SceneAuditProps)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

    del bpy.types.Scene.quick_commands
    del bpy.types.Scene.quick_commands_index
    del bpy.types.Scene.qc_mat_texture_size
    del bpy.types.Scene.qc_mat_32bit
    del bpy.types.Scene.qc_td_pixels_per_unit
    del bpy.types.Scene.qc_td_result_raw
    del bpy.types.Scene.qc_td_result_pow2
    del bpy.types.Scene.attrtool
    del bpy.types.Scene.scene_audit


if __name__ == "__main__":
    register()