"""
GOAL Node Compiler — graph → Lisp source compiler for Level-A scope.

This package is DUAL-PURPOSE:

  1. As a pure Python library — import ir/emitter/validate for testing
     and headless compilation. `python -m goal_node_compiler.tests.test_emitter`
     works without Blender installed.

  2. As a Blender addon — installable via Edit → Preferences → Add-ons →
     Install. When bpy is importable, register() wires up a custom
     NodeTree type, its sockets and nodes, the Shift+A menu, the Compile
     operator, and the sidebar panel.

The split is achieved by a single try/except at import time. If bpy isn't
available, the bl_* modules are skipped and only the pure-Python compiler
API is exposed.
"""

# --- Pure-Python compiler API (always exported) ----------------------------

from .ir import (
    Graph, Entity, Axis, Unit, Value, AddressMode,
    ActionRotate, ActionOscillate, ActionLerpAlongAxis,
    ActionPlaySound, ActionSendEvent, ActionKillTarget,
    ActionDeactivateSelf, ActionSetSetting, ActionRawGoal,
    ActionWait, ActionSequence,
    TriggerOnSpawn, TriggerOnEvent, TriggerOnVolEntered,
    TriggerOnProximity, TriggerOnTimeElapsed, TriggerOnEveryNFrames,
)
from .emitter import compile_graph, CompileError

__all__ = [
    "Graph", "Entity", "Axis", "Unit", "Value", "AddressMode",
    "ActionRotate", "ActionOscillate", "ActionLerpAlongAxis",
    "ActionPlaySound", "ActionSendEvent", "ActionKillTarget",
    "ActionDeactivateSelf", "ActionSetSetting", "ActionRawGoal",
    "ActionWait", "ActionSequence",
    "TriggerOnSpawn", "TriggerOnEvent", "TriggerOnVolEntered",
    "TriggerOnProximity", "TriggerOnTimeElapsed", "TriggerOnEveryNFrames",
    "compile_graph", "CompileError",
]


# --- Blender addon manifest (only meaningful when installed in Blender) ----

bl_info = {
    "name":        "GOAL Node Compiler",
    "author":      "Theory-box + Claude",
    "version":     (0, 1, 0),
    "blender":     (4, 4, 0),
    "location":    "Node Editor → GOAL Nodes tree type",
    "description": ("Visual node editor for authoring GOAL source for "
                    "Jak 1 custom levels (OpenGOAL). Level-A scope: 20 "
                    "node types covering entity/trigger/action primitives."),
    "category":    "Node",
}


# --- Blender-side registration ---------------------------------------------

try:
    import bpy  # noqa: F401

    from . import bl_sockets, bl_tree, bl_nodes, bl_menu, bl_operators, bl_panels

    _BL_AVAILABLE = True

    # Registration order matters: sockets before nodes (nodes reference socket
    # bl_idnames), menu submenus before the top-level append, panels last.
    _CLASSES = (
        bl_sockets.classes
        + bl_tree.classes
        + bl_nodes.classes
        + bl_menu.classes
        + bl_operators.classes
        + bl_panels.classes
    )

    def register():
        for cls in _CLASSES:
            bpy.utils.register_class(cls)
        bl_menu.register_menu()

    def unregister():
        bl_menu.unregister_menu()
        for cls in reversed(_CLASSES):
            bpy.utils.unregister_class(cls)

except ImportError:
    _BL_AVAILABLE = False

    def register():
        raise RuntimeError(
            "Blender bpy module not available — this addon must be installed "
            "into Blender to register. For pure-Python use, import "
            "goal_node_compiler.ir / .emitter directly."
        )

    def unregister():
        pass
