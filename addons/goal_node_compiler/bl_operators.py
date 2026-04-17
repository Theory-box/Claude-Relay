"""
Compile operator — the button that turns a node tree into GOAL source.

Flow:
  1. Read the active tree from the Node Editor context.
  2. Walk the tree → IR Graph (raises WalkError on structural problems).
  3. compile_graph(graph) → GOAL source string (raises CompileError on
     validation failures).
  4. Write the source to a Blender text block. If the tree's
     target_text_block is set, reuse it; otherwise create one named
     `<etype>-goal-code`.
  5. Stash status on the tree (last_compile_status / _errors / _output) so
     the sidebar panel can display them.

On success, also sets the active text block so the user sees the result
immediately in the Text Editor.
"""

import bpy

from . import emitter, validate
from .bl_walker import tree_to_graph, WalkError


class GOAL_OT_compile(bpy.types.Operator):
    bl_idname  = "goal.compile_graph"
    bl_label   = "Compile Graph"
    bl_description = ("Walk the current GOAL node tree and produce GOAL "
                      "source in a text block")
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        if not context.space_data or context.space_data.type != 'NODE_EDITOR':
            return False
        t = context.space_data.edit_tree
        return bool(t and t.bl_idname == 'GoalNodeTreeType')

    def execute(self, context):
        tree = context.space_data.edit_tree

        # --- 1-2. Tree → IR ------------------------------------------------
        try:
            graph = tree_to_graph(tree)
        except WalkError as e:
            tree.last_compile_status = "STRUCTURE ERROR"
            tree.last_compile_errors = str(e)
            tree.last_compile_output = ""
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # --- 3. Compile ----------------------------------------------------
        try:
            goal_source = emitter.compile_graph(graph)
        except validate.CompileError as e:
            # e.issues is a list of Issue objects. Format them for display.
            msg_lines = [f"{i.level.value.upper()}  {i.where}: {i.message}"
                         for i in e.issues]
            full = "\n".join(msg_lines)
            tree.last_compile_status = f"VALIDATION FAILED ({len(e.issues)})"
            tree.last_compile_errors = full
            tree.last_compile_output = ""
            self.report({'ERROR'}, f"Validation failed — {len(e.issues)} issue(s). See sidebar.")
            return {'CANCELLED'}
        except NotImplementedError as e:
            tree.last_compile_status = "UNSUPPORTED NODE"
            tree.last_compile_errors = (
                f"{e}\n\nThis node type isn't implemented by the compiler yet. "
                "See knowledge-base/blender/goal-node-advanced-vocabulary-brainstorm.md."
            )
            tree.last_compile_output = ""
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}

        # --- 4. Write text block -------------------------------------------
        block_name = tree.target_text_block or f"{graph.entity.etype}-goal-code"
        tb = bpy.data.texts.get(block_name)
        if tb is None:
            tb = bpy.data.texts.new(block_name)
        tb.clear()
        tb.write(goal_source)
        tree.target_text_block = block_name  # remember for next time

        # --- 5. Report -----------------------------------------------------
        tree.last_compile_status = "OK"
        tree.last_compile_errors = ""
        tree.last_compile_output = block_name

        line_count = goal_source.count("\n")
        self.report({'INFO'},
                    f"Compiled {graph.entity.etype} → '{block_name}' "
                    f"({line_count} lines).")
        return {'FINISHED'}


class GOAL_OT_open_output(bpy.types.Operator):
    """Open the last compile output in the Text Editor."""
    bl_idname  = "goal.open_output"
    bl_label   = "Show Output"
    bl_description = "Open the most recently compiled text block in the Text Editor"

    @classmethod
    def poll(cls, context):
        t = context.space_data.edit_tree if context.space_data else None
        return bool(t and t.bl_idname == 'GoalNodeTreeType' and t.last_compile_output)

    def execute(self, context):
        tree = context.space_data.edit_tree
        name = tree.last_compile_output
        tb = bpy.data.texts.get(name)
        if tb is None:
            self.report({'WARNING'}, f"Text block '{name}' no longer exists.")
            return {'CANCELLED'}
        # Find an existing Text Editor area; if present, set its text.
        # Otherwise leave it to the user — we don't rearrange their layout.
        for area in context.screen.areas:
            if area.type == 'TEXT_EDITOR':
                area.spaces.active.text = tb
                self.report({'INFO'}, f"Opened '{name}'.")
                return {'FINISHED'}
        # No Text Editor open. We still "activated" the text via the API
        # so a newly-opened Text Editor will see it as a recent option.
        context.window_manager.popup_menu(
            lambda self, ctx: self.layout.label(
                text=f"Open a Text Editor and pick '{name}' from the datablock list.",
            ),
            title="Output Ready", icon='INFO',
        )
        return {'FINISHED'}


classes = (
    GOAL_OT_compile,
    GOAL_OT_open_output,
)
