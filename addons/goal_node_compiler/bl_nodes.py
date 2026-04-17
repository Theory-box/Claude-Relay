"""
Node classes — one Blender bpy.types.Node subclass per IR type.

Shape conventions:
  Entity has no Flow input. Its "Attach" output fires its direct actions
  and wires to triggers.
  Triggers have a "From" Flow input (coming from the Entity) and a "Fires"
  Flow output (going to actions the trigger gates or fires instantly).
  Actions have a "From" Flow input (coming from Entity or a Trigger).
    Continuous/timed actions have no Flow output — they're leaves.
    Instant actions have no Flow output either — they're leaves.
    Sequence is the exception: "Step 1", "Step 2", ..., "Step 4" Flow outputs.
    Wait also has no output; it's only valid as a step inside a Sequence.

Colour convention (draw_color on each node class's bl_icon? no — we use
bl_idname prefixes and let the user-installed theme do the rest. Default
node headers show a colour band set via `use_custom_color` + `color`).
"""

import bpy
from bpy.props import (
    StringProperty, FloatProperty, IntProperty, BoolProperty, EnumProperty,
)


# ============================================================================
# BASE CLASS — poll restricts nodes to GoalNodeTree
# ============================================================================

class GoalNodeBase:
    """Mixin for all nodes in the GOAL tree. Restricts nodes to GoalNodeTree."""
    @classmethod
    def poll(cls, ntree):
        return ntree.bl_idname == 'GoalNodeTreeType'


# ---------------------------------------------------------------------------
# Colour palette — assigned to node headers so categories are visually obvious
# ---------------------------------------------------------------------------
COL_ENTITY = (0.35, 0.35, 0.35)   # grey — structural
COL_TRIGGER = (0.85, 0.65, 0.20)  # amber — "when"
COL_MOTION = (0.25, 0.65, 0.60)   # teal — continuous motion
COL_SIGNAL = (0.85, 0.45, 0.45)   # coral — one-shot signal
COL_FLOW = (0.55, 0.35, 0.75)     # purple — sequence / wait
COL_RAW = (0.45, 0.45, 0.45)      # grey — escape hatch


def _apply_color(node, color):
    node.use_custom_color = True
    node.color = color


# ============================================================================
# ENTITY
# ============================================================================

class GoalEntityNode(GoalNodeBase, bpy.types.Node):
    """Root of every graph. Declares the deftype name."""
    bl_idname = 'GoalEntityNode'
    bl_label  = "Entity"

    etype: StringProperty(
        name="Type Name",
        description=("GOAL deftype name. Lowercase letters, digits, hyphens. "
                     "Matches Blender ACTOR_<etype>_<N> convention."),
        default="my-actor",
    )

    def init(self, context):
        self.outputs.new('GoalFlowSocketType', "Attach")
        _apply_color(self, COL_ENTITY)

    def draw_buttons(self, context, layout):
        layout.prop(self, "etype", text="")


# ============================================================================
# TRIGGERS — each has From (Flow in) and Fires (Flow out)
# ============================================================================

class _TriggerMixin:
    """Shared setup for all Trigger nodes."""
    def _add_flow_sockets(self):
        self.inputs.new('GoalFlowSocketType', "From")
        self.outputs.new('GoalFlowSocketType', "Fires")


class GoalOnSpawnNode(_TriggerMixin, GoalNodeBase, bpy.types.Node):
    """Fires once at entity birth."""
    bl_idname = 'GoalOnSpawnNode'
    bl_label  = "On Spawn"

    def init(self, context):
        self._add_flow_sockets()
        _apply_color(self, COL_TRIGGER)


class GoalOnEventNode(_TriggerMixin, GoalNodeBase, bpy.types.Node):
    """Fires when this entity receives a named event."""
    bl_idname = 'GoalOnEventNode'
    bl_label  = "On Event"

    event_name: StringProperty(
        name="Event",
        description="Event symbol — e.g. trigger, untrigger, touch, attack, die, notify",
        default="trigger",
    )

    def init(self, context):
        self._add_flow_sockets()
        _apply_color(self, COL_TRIGGER)

    def draw_buttons(self, context, layout):
        layout.prop(self, "event_name", text="")


class GoalOnVolEnteredNode(_TriggerMixin, GoalNodeBase, bpy.types.Node):
    """Fires when Jak enters a VOL_ wired to this actor in Blender.
    Semantically a rename of On Event('trigger) for clarity."""
    bl_idname = 'GoalOnVolEnteredNode'
    bl_label  = "On Volume Entered"

    def init(self, context):
        self._add_flow_sockets()
        _apply_color(self, COL_TRIGGER)


class GoalOnProximityNode(_TriggerMixin, GoalNodeBase, bpy.types.Node):
    """Fires when Jak is within `distance` of this entity.
    Polled each frame in :trans."""
    bl_idname = 'GoalOnProximityNode'
    bl_label  = "On Proximity"

    xz_only: BoolProperty(
        name="Ignore Height",
        description="Use XZ-only distance (ignore Y axis).",
        default=False,
    )

    def init(self, context):
        self._add_flow_sockets()
        s = self.inputs.new('GoalMetersSocketType', "Distance")
        s.default_value = 10.0
        _apply_color(self, COL_TRIGGER)

    def draw_buttons(self, context, layout):
        layout.prop(self, "xz_only")


class GoalOnTimeElapsedNode(_TriggerMixin, GoalNodeBase, bpy.types.Node):
    """Fires once `delay` seconds after the entity has existed in this state."""
    bl_idname = 'GoalOnTimeElapsedNode'
    bl_label  = "On Time Elapsed"

    def init(self, context):
        self._add_flow_sockets()
        s = self.inputs.new('GoalSecondsSocketType', "Delay")
        s.default_value = 2.0
        _apply_color(self, COL_TRIGGER)


class GoalOnEveryNFramesNode(_TriggerMixin, GoalNodeBase, bpy.types.Node):
    """Fires every Nth frame (engine throttle pattern).
    N=4 ≈ 15Hz at 60fps; N=30 ≈ twice per second."""
    bl_idname = 'GoalOnEveryNFramesNode'
    bl_label  = "On Every N Frames"

    every_n: IntProperty(
        name="N",
        description="Fire when (frame-count mod N) == 0.",
        default=30, min=1, soft_max=300,
    )

    def init(self, context):
        self._add_flow_sockets()
        _apply_color(self, COL_TRIGGER)

    def draw_buttons(self, context, layout):
        layout.prop(self, "every_n")


# ============================================================================
# ACTIONS — Motion
# ============================================================================

_AXIS_ITEMS = [('X', "X", ""), ('Y', "Y", ""), ('Z', "Z", "")]
_ADDR_MODE_ITEMS = [
    ('LITERAL', "Literal Name", "Hardcoded actor name string"),
    ('LUMP',    "From Lump",    "Read target name from a per-actor lump"),
]


class _ActionMixin:
    """Shared setup for Action nodes — Flow input, optional categorisation."""
    def _add_flow_input(self):
        self.inputs.new('GoalFlowSocketType', "From")


class GoalRotateNode(_ActionMixin, GoalNodeBase, bpy.types.Node):
    """Rotate continuously around an axis. Units: degrees-per-tick."""
    bl_idname = 'GoalRotateNode'
    bl_label  = "Rotate"

    axis: EnumProperty(name="Axis", items=_AXIS_ITEMS, default='Y')

    def init(self, context):
        self._add_flow_input()
        s = self.inputs.new('GoalDegreesSocketType', "Speed")
        s.default_value = 1.0
        _apply_color(self, COL_MOTION)

    def draw_buttons(self, context, layout):
        layout.prop(self, "axis", expand=True)


class GoalOscillateNode(_ActionMixin, GoalNodeBase, bpy.types.Node):
    """Sine-wave oscillate on an axis (bob, pulse, swing)."""
    bl_idname = 'GoalOscillateNode'
    bl_label  = "Oscillate"

    axis: EnumProperty(name="Axis", items=_AXIS_ITEMS, default='Y')

    def init(self, context):
        self._add_flow_input()
        a = self.inputs.new('GoalMetersSocketType', "Amplitude"); a.default_value = 0.5
        p = self.inputs.new('GoalSecondsSocketType', "Period");    p.default_value = 3.0
        _apply_color(self, COL_MOTION)

    def draw_buttons(self, context, layout):
        layout.prop(self, "axis", expand=True)


class GoalLerpAlongAxisNode(_ActionMixin, GoalNodeBase, bpy.types.Node):
    """Smoothly move a relative distance along an axis over a duration.
    Timed action — needs a trigger to restart. Good for doors, platforms."""
    bl_idname = 'GoalLerpAlongAxisNode'
    bl_label  = "Lerp Along Axis"

    axis: EnumProperty(name="Axis", items=_AXIS_ITEMS, default='Y')

    def init(self, context):
        self._add_flow_input()
        d = self.inputs.new('GoalMetersSocketType', "Distance"); d.default_value = 4.0
        t = self.inputs.new('GoalSecondsSocketType', "Duration"); t.default_value = 0.5
        _apply_color(self, COL_MOTION)

    def draw_buttons(self, context, layout):
        layout.prop(self, "axis", expand=True)


# ============================================================================
# ACTIONS — Signal (one-shot)
# ============================================================================

class GoalPlaySoundNode(_ActionMixin, GoalNodeBase, bpy.types.Node):
    """Play a sound by name."""
    bl_idname = 'GoalPlaySoundNode'
    bl_label  = "Play Sound"

    sound_name: StringProperty(name="Sound", default="")
    volume:     FloatProperty(name="Volume", default=100.0, min=0.0, max=100.0)
    positional: BoolProperty(name="Positional (3D)", default=False)

    def init(self, context):
        self._add_flow_input()
        _apply_color(self, COL_SIGNAL)

    def draw_buttons(self, context, layout):
        layout.prop(self, "sound_name")
        layout.prop(self, "volume")
        layout.prop(self, "positional")


class _TargetableMixin:
    """Shared literal-vs-lump target fields for SendEvent / KillTarget."""
    target_name: StringProperty(
        name="Target",
        description=("Literal mode: exact actor lump name. "
                     "Lump mode: the lump KEY to read the name from."),
        default="",
    )
    target_mode: EnumProperty(
        name="Target Mode", items=_ADDR_MODE_ITEMS, default='LITERAL',
    )

    def _draw_target(self, layout):
        layout.prop(self, "target_mode", text="")
        layout.prop(self, "target_name", text="Target")


class GoalSendEventNode(_ActionMixin, _TargetableMixin, GoalNodeBase, bpy.types.Node):
    """Send an event to another actor. Supports literal or lump-mode targets."""
    bl_idname = 'GoalSendEventNode'
    bl_label  = "Send Event"

    event_name: StringProperty(name="Event", default="trigger")

    def init(self, context):
        self._add_flow_input()
        _apply_color(self, COL_SIGNAL)

    def draw_buttons(self, context, layout):
        self._draw_target(layout)
        layout.prop(self, "event_name")


class GoalKillTargetNode(_ActionMixin, _TargetableMixin, GoalNodeBase, bpy.types.Node):
    """Kill + mark dead a target actor (two-step canonical die-relay pattern)."""
    bl_idname = 'GoalKillTargetNode'
    bl_label  = "Kill Target"

    def init(self, context):
        self._add_flow_input()
        _apply_color(self, COL_SIGNAL)

    def draw_buttons(self, context, layout):
        self._draw_target(layout)


class GoalDeactivateSelfNode(_ActionMixin, GoalNodeBase, bpy.types.Node):
    """`(deactivate self)`. In a Sequence, suppresses the automatic tail go-main."""
    bl_idname = 'GoalDeactivateSelfNode'
    bl_label  = "Deactivate Self"

    def init(self, context):
        self._add_flow_input()
        _apply_color(self, COL_SIGNAL)


_SETTING_MODE_ITEMS = [
    ('abs', "Absolute", "Absolute value override"),
    ('rel', "Relative", "Multiplied with defaults"),
]


class GoalSetSettingNode(_ActionMixin, GoalNodeBase, bpy.types.Node):
    """`(set-setting! 'key mode value duration)` — music, volume, bg-a, locks, etc."""
    bl_idname = 'GoalSetSettingNode'
    bl_label  = "Set Setting"

    setting_key: StringProperty(
        name="Key",
        description="Setting symbol e.g. music, music-volume, bg-a, allow-progress",
        default="music",
    )
    mode:  EnumProperty(name="Mode", items=_SETTING_MODE_ITEMS, default='abs')
    value: FloatProperty(name="Value", default=1.0)

    def init(self, context):
        self._add_flow_input()
        s = self.inputs.new('GoalSecondsSocketType', "Duration")
        s.default_value = 0.0
        _apply_color(self, COL_SIGNAL)

    def draw_buttons(self, context, layout):
        layout.prop(self, "setting_key", text="")
        layout.prop(self, "mode", text="")
        layout.prop(self, "value")


# ============================================================================
# FLOW
# ============================================================================

class GoalSequenceNode(_ActionMixin, GoalNodeBase, bpy.types.Node):
    """Runs a linear chain of steps. Must be trigger-gated.
    Fixed 4 step outputs for now — dynamic sockets deferred."""
    bl_idname = 'GoalSequenceNode'
    bl_label  = "Sequence"

    def init(self, context):
        self._add_flow_input()
        for i in range(1, 5):
            self.outputs.new('GoalFlowSocketType', f"Step {i}")
        _apply_color(self, COL_FLOW)


class GoalWaitNode(_ActionMixin, GoalNodeBase, bpy.types.Node):
    """Pause inside a Sequence. Emits (suspend-for). Only valid as a sequence step."""
    bl_idname = 'GoalWaitNode'
    bl_label  = "Wait"

    def init(self, context):
        self._add_flow_input()
        s = self.inputs.new('GoalSecondsSocketType', "Duration")
        s.default_value = 1.0
        _apply_color(self, COL_FLOW)


# ============================================================================
# ESCAPE HATCH
# ============================================================================

_RAW_SLOT_ITEMS = [
    ('trans',     "Per-Frame (:trans)",   ""),
    ('code',      "Main Body (:code)",    ""),
    ('init',      "Init",                 ""),
    ('event',     "Event Branch",         ""),
    ('top_level', "Top-Level Form",       ""),
]


class GoalRawNode(_ActionMixin, GoalNodeBase, bpy.types.Node):
    """Emit raw GOAL source into a chosen slot. The escape hatch for anything
    the vocabulary can't express."""
    bl_idname = 'GoalRawNode'
    bl_label  = "Raw GOAL"

    slot: EnumProperty(name="Slot", items=_RAW_SLOT_ITEMS, default='trans')
    body: StringProperty(
        name="Body",
        description="GOAL source code to inject verbatim.",
        default="",
    )

    def init(self, context):
        self._add_flow_input()
        _apply_color(self, COL_RAW)

    def draw_buttons(self, context, layout):
        layout.prop(self, "slot", text="")
        # Multi-line editing in Blender's node UI is clunky; show as inline
        # and let the sidebar panel offer a "Open in Text Editor" option.
        layout.prop(self, "body", text="")


# ============================================================================
# Registration bundle
# ============================================================================

classes = (
    GoalEntityNode,
    # Triggers
    GoalOnSpawnNode, GoalOnEventNode, GoalOnVolEnteredNode,
    GoalOnProximityNode, GoalOnTimeElapsedNode, GoalOnEveryNFramesNode,
    # Motion actions
    GoalRotateNode, GoalOscillateNode, GoalLerpAlongAxisNode,
    # Signal actions
    GoalPlaySoundNode, GoalSendEventNode, GoalKillTargetNode,
    GoalDeactivateSelfNode, GoalSetSettingNode,
    # Flow
    GoalSequenceNode, GoalWaitNode,
    # Escape
    GoalRawNode,
)
