"""
Sidebar panel for the GOAL Node Editor.

Location: Node Editor → sidebar (press N) → "GOAL" tab.

Contents:
  - Compile button
  - Target text block picker (optional override)
  - Status line (OK / ERROR counts)
  - Error list (if any)
  - Show Output button (opens compiled text in Text Editor)
"""

import bpy


class GOAL_PT_main(bpy.types.Panel):
    bl_idname      = "GOAL_PT_main"
    bl_label       = "GOAL Compiler"
    bl_space_type  = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category    = "GOAL"

    @classmethod
    def poll(cls, context):
        t = context.space_data.edit_tree if context.space_data else None
        return bool(t and t.bl_idname == 'GoalNodeTreeType')

    def draw(self, context):
        layout = self.layout
        tree = context.space_data.edit_tree

        # --- Compile ---------------------------------------------------------
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("goal.compile_graph", icon='PLAY')

        # --- Target text block -----------------------------------------------
        box = layout.box()
        box.label(text="Output Destination", icon='TEXT')
        box.prop_search(tree, "target_text_block",
                        bpy.data, "texts", text="Text Block")
        if not tree.target_text_block:
            box.label(text="(auto: <etype>-goal-code)", icon='BLANK1')

        # --- Status ----------------------------------------------------------
        status = tree.last_compile_status
        if not status:
            return   # nothing compiled yet

        layout.separator()
        box = layout.box()
        if status == "OK":
            row = box.row()
            row.label(text="OK", icon='CHECKMARK')
            row.label(text=tree.last_compile_output)
            box.operator("goal.open_output", icon='FILE_TEXT')
        else:
            box.label(text=status, icon='ERROR')
            if tree.last_compile_errors:
                # Lines get wrapped in a scrollable column — Blender has no
                # built-in text area widget, so we split the error text on
                # newlines and show each as its own label row.
                for line in tree.last_compile_errors.split("\n"):
                    # Wrap long lines naively — Blender labels don't wrap.
                    while len(line) > 70:
                        box.label(text=line[:70])
                        line = "    " + line[70:]
                    box.label(text=line)


class GOAL_PT_help(bpy.types.Panel):
    """Brief cheat-sheet for what a valid graph looks like."""
    bl_idname      = "GOAL_PT_help"
    bl_label       = "Quick Reference"
    bl_space_type  = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category    = "GOAL"
    bl_options     = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        t = context.space_data.edit_tree if context.space_data else None
        return bool(t and t.bl_idname == 'GoalNodeTreeType')

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        lines = [
            "Every graph needs exactly 1 Entity.",
            "Wire Entity.Attach to triggers or actions.",
            "Triggers have From and Fires Flow sockets.",
            "Actions only have a From Flow socket.",
            "Rotate/Oscillate/Lerp: continuous motion.",
            "Send Event / Kill Target / Play Sound: one-shot.",
            "Sequence must be wired from a trigger's Fires.",
            "Wait is only valid inside a Sequence step.",
            "Use Raw GOAL as an escape hatch.",
        ]
        for line in lines:
            col.label(text=line)


classes = (
    GOAL_PT_main,
    GOAL_PT_help,
)
