"""
NodeTree subclass — the datablock that holds a graph.

Users create one by opening the Node Editor, clicking the tree-type selector
(the icon to the left of the "new tree" dropdown), and picking "GOAL Nodes".

One tree = one entity graph = one compilation unit = one deftype.
"""

import bpy


class GoalNodeTree(bpy.types.NodeTree):
    """A visual graph that compiles to GOAL source for one custom actor."""
    bl_idname  = 'GoalNodeTreeType'
    bl_label   = "GOAL Nodes"
    bl_icon    = 'NODETREE'

    # When set, Compile writes to this text block. Otherwise creates one.
    target_text_block: bpy.props.StringProperty(
        name="Target Text Block",
        description=("Blender text block to receive generated GOAL source. "
                     "If blank, a new one named <etype>-goal-code is created."),
        default="",
    )

    # Populated by the Compile operator. Displayed in the sidebar panel.
    last_compile_status: bpy.props.StringProperty(default="")
    last_compile_errors: bpy.props.StringProperty(default="")
    last_compile_output: bpy.props.StringProperty(default="")


classes = (GoalNodeTree,)
