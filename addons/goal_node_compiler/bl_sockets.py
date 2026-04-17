"""
Blender NodeSocket subclasses for the GOAL node editor.

Four socket kinds:
  GoalFlowSocket  — carries the attach/fire relationship (Entity → action,
                    trigger → action, sequence → step). Drawn in near-white.
  GoalMetersSocket    — float in meters. Blue. Compiler emits (meters N).
  GoalDegreesSocket   — float in degrees. Amber. Compiler emits (degrees N).
  GoalSecondsSocket   — float in seconds. Green. Compiler emits (seconds N).

The unit-typed sockets are the single most important design decision — they
physically prevent the raw-float-vs-meters bug documented in
goal-code-runtime.md by refusing to connect to non-matching sockets.

Other scalar / vector inputs use Blender's built-in NodeSocketFloat,
NodeSocketVector, NodeSocketString, NodeSocketBool, NodeSocketInt.
"""

import bpy


class GoalFlowSocket(bpy.types.NodeSocket):
    """Attach/fire relationship — entity→action, trigger→action, seq→step."""
    bl_idname = 'GoalFlowSocketType'
    bl_label  = "Flow"

    def draw(self, context, layout, node, text):
        layout.label(text=text)

    def draw_color(self, context, node):
        return (0.85, 0.85, 0.85, 1.0)   # near-white


class GoalMetersSocket(bpy.types.NodeSocket):
    """Distance in meters. Compiler wraps with (meters N) on emit."""
    bl_idname = 'GoalMetersSocketType'
    bl_label  = "Meters"

    default_value: bpy.props.FloatProperty(
        name="Meters", default=1.0, soft_min=-1000.0, soft_max=1000.0,
        description="Distance in meters. Emits (meters N).",
    )

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    def draw_color(self, context, node):
        return (0.25, 0.55, 0.95, 1.0)   # blue


class GoalDegreesSocket(bpy.types.NodeSocket):
    """Rotation in degrees. Compiler wraps with (degrees N) on emit."""
    bl_idname = 'GoalDegreesSocketType'
    bl_label  = "Degrees"

    default_value: bpy.props.FloatProperty(
        name="Degrees", default=0.0, soft_min=-360.0, soft_max=360.0,
        description="Rotation in degrees. Emits (degrees N).",
    )

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    def draw_color(self, context, node):
        return (0.95, 0.65, 0.15, 1.0)   # amber


class GoalSecondsSocket(bpy.types.NodeSocket):
    """Time in seconds. Compiler wraps with (seconds N) on emit."""
    bl_idname = 'GoalSecondsSocketType'
    bl_label  = "Seconds"

    default_value: bpy.props.FloatProperty(
        name="Seconds", default=1.0, soft_min=0.0, soft_max=300.0,
        description="Time in seconds. Emits (seconds N).",
    )

    def draw(self, context, layout, node, text):
        if self.is_output or self.is_linked:
            layout.label(text=text)
        else:
            layout.prop(self, "default_value", text=text)

    def draw_color(self, context, node):
        return (0.40, 0.80, 0.35, 1.0)   # green


classes = (
    GoalFlowSocket,
    GoalMetersSocket,
    GoalDegreesSocket,
    GoalSecondsSocket,
)
