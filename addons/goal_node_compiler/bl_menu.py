"""
Shift+A "Add" menu for the GOAL Node Editor.

Uses the Blender 3.4+ NODE_MT_add.append pattern. `nodeitems_utils` is
deprecated and emits a warning on every Blender startup if used.

Hierarchy:
  Add → Entity
  Add → Triggers → (6 triggers)
  Add → Actions → Motion → (Rotate, Oscillate, Lerp Along Axis)
  Add → Actions → Signal → (Play Sound, Send Event, Kill Target, Deactivate Self, Set Setting)
  Add → Flow   → (Sequence, Wait)
  Add → Escape → (Raw GOAL)

Only shown when the active NodeTree is a GoalNodeTreeType.
"""

import bpy


def _add_node_op(layout, bl_idname, label):
    """Add a 'create node' button that Blender wires up for us."""
    op = layout.operator("node.add_node", text=label)
    op.type = bl_idname
    op.use_transform = True   # lets the user place it with mouse movement


# --- Submenus ---------------------------------------------------------------

class GOAL_MT_add_triggers(bpy.types.Menu):
    bl_idname = "GOAL_MT_add_triggers"
    bl_label  = "Triggers"

    def draw(self, context):
        layout = self.layout
        _add_node_op(layout, 'GoalOnSpawnNode',        "On Spawn")
        _add_node_op(layout, 'GoalOnEventNode',        "On Event")
        _add_node_op(layout, 'GoalOnVolEnteredNode',   "On Volume Entered")
        _add_node_op(layout, 'GoalOnProximityNode',    "On Proximity")
        _add_node_op(layout, 'GoalOnTimeElapsedNode',  "On Time Elapsed")
        _add_node_op(layout, 'GoalOnEveryNFramesNode', "On Every N Frames")


class GOAL_MT_add_motion(bpy.types.Menu):
    bl_idname = "GOAL_MT_add_motion"
    bl_label  = "Motion"

    def draw(self, context):
        layout = self.layout
        _add_node_op(layout, 'GoalRotateNode',        "Rotate")
        _add_node_op(layout, 'GoalOscillateNode',     "Oscillate")
        _add_node_op(layout, 'GoalLerpAlongAxisNode', "Lerp Along Axis")


class GOAL_MT_add_signal(bpy.types.Menu):
    bl_idname = "GOAL_MT_add_signal"
    bl_label  = "Signal"

    def draw(self, context):
        layout = self.layout
        _add_node_op(layout, 'GoalPlaySoundNode',      "Play Sound")
        _add_node_op(layout, 'GoalSendEventNode',      "Send Event")
        _add_node_op(layout, 'GoalKillTargetNode',     "Kill Target")
        _add_node_op(layout, 'GoalDeactivateSelfNode', "Deactivate Self")
        _add_node_op(layout, 'GoalSetSettingNode',     "Set Setting")


class GOAL_MT_add_actions(bpy.types.Menu):
    bl_idname = "GOAL_MT_add_actions"
    bl_label  = "Actions"

    def draw(self, context):
        layout = self.layout
        layout.menu("GOAL_MT_add_motion")
        layout.menu("GOAL_MT_add_signal")


class GOAL_MT_add_flow(bpy.types.Menu):
    bl_idname = "GOAL_MT_add_flow"
    bl_label  = "Flow"

    def draw(self, context):
        layout = self.layout
        _add_node_op(layout, 'GoalSequenceNode', "Sequence")
        _add_node_op(layout, 'GoalWaitNode',     "Wait")


class GOAL_MT_add_escape(bpy.types.Menu):
    bl_idname = "GOAL_MT_add_escape"
    bl_label  = "Escape"

    def draw(self, context):
        layout = self.layout
        _add_node_op(layout, 'GoalRawNode', "Raw GOAL")


# --- Top-level append -------------------------------------------------------

def _goal_add_menu(self, context):
    """Appended to NODE_MT_add; only shows entries in a GOAL tree."""
    tree = context.space_data.edit_tree if context.space_data else None
    if not tree or tree.bl_idname != 'GoalNodeTreeType':
        return
    layout = self.layout
    layout.separator()
    _add_node_op(layout, 'GoalEntityNode', "Entity")
    layout.menu("GOAL_MT_add_triggers")
    layout.menu("GOAL_MT_add_actions")
    layout.menu("GOAL_MT_add_flow")
    layout.menu("GOAL_MT_add_escape")


classes = (
    GOAL_MT_add_triggers,
    GOAL_MT_add_motion,
    GOAL_MT_add_signal,
    GOAL_MT_add_actions,
    GOAL_MT_add_flow,
    GOAL_MT_add_escape,
)


def register_menu():
    bpy.types.NODE_MT_add.append(_goal_add_menu)


def unregister_menu():
    bpy.types.NODE_MT_add.remove(_goal_add_menu)
