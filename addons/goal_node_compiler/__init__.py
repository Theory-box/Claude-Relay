"""GOAL Node Compiler — graph → Lisp source compiler for Level-A scope."""

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
