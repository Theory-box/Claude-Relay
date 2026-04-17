"""
Node tree → IR walker.

This is the bridge between the Blender-side UI and the pure-Python compiler.
A `GoalNodeTree` containing placed nodes and wired Flow links becomes a
`Graph` IR object that `emitter.compile_graph()` consumes.

Algorithm
---------
1. Find the Entity node (exactly one per tree). If missing or duplicated,
   raise WalkError with a clear message.
2. For each Flow link starting at the Entity's "Attach" output:
   - Target is a Trigger → build a Trigger IR; recurse into the trigger's
     "Fires" output to collect its gated/instant actions.
   - Target is an Action → direct-to-entity action; classify as gated or
     instant based on the Action's IR CATEGORY (CONTINUOUS/TIMED/INSTANT/
     SEQUENCE/WAIT).
3. Classification rule inside a Trigger:
     action.CATEGORY in (CONTINUOUS, TIMED)  → trigger.gated_actions
     action.CATEGORY == INSTANT / SEQUENCE / WAIT → trigger.instant_actions
   (SEQUENCE and WAIT are handled as INSTANT-firing-site for this purpose —
   the emitter routes them correctly via their own logic.)
4. Sequence's 4 "Step N" outputs each become an ordered step. Unwired
   outputs are skipped.

What the walker does NOT do
---------------------------
  - Validation — that's `validate.py`'s job, called inside `compile_graph`.
  - ID uniqueness — we hash node names for stability; collisions surface as
    validation errors downstream.
  - Scene-query resolution — ForEach/ActorSet aren't in Level A.
"""

from . import ir


class WalkError(Exception):
    """Raised when the node tree can't be interpreted as a valid Graph.
    User-visible — the caller displays this in the sidebar panel."""
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    """Turn a Blender node name like 'Rotate.001' into an IR ID."""
    return name.lower().replace(" ", "-").replace(".", "-")


def _socket_value(sock):
    """Get a default_value from a Blender socket. For our unit sockets the
    attribute is always 'default_value'."""
    return getattr(sock, "default_value", 0.0)


def _input_by_name(node, name: str):
    """Find an input socket by its label (name). Raises if missing."""
    for s in node.inputs:
        if s.name == name:
            return s
    raise WalkError(f"Node '{node.name}' missing required input '{name}'")


def _linked_targets(output_sock):
    """Return every Node reached from this output socket via one Flow link."""
    return [link.to_node for link in output_sock.links]


# ---------------------------------------------------------------------------
# Node → Action/Trigger builders
# ---------------------------------------------------------------------------

def _build_action(node) -> ir.Action:
    """Convert one Blender Action node to its IR dataclass."""
    name = _slug(node.name)
    idn  = node.bl_idname

    if idn == 'GoalRotateNode':
        return ir.ActionRotate(
            id=name,
            axis=ir.Axis[node.axis],
            speed=ir.Value(_socket_value(_input_by_name(node, "Speed")), ir.Unit.DEGREES),
        )

    if idn == 'GoalOscillateNode':
        return ir.ActionOscillate(
            id=name,
            axis=ir.Axis[node.axis],
            amplitude=ir.Value(_socket_value(_input_by_name(node, "Amplitude")), ir.Unit.METERS),
            period   =ir.Value(_socket_value(_input_by_name(node, "Period")),    ir.Unit.SECONDS),
        )

    if idn == 'GoalLerpAlongAxisNode':
        return ir.ActionLerpAlongAxis(
            id=name,
            axis=ir.Axis[node.axis],
            distance=ir.Value(_socket_value(_input_by_name(node, "Distance")), ir.Unit.METERS),
            duration=ir.Value(_socket_value(_input_by_name(node, "Duration")), ir.Unit.SECONDS),
        )

    if idn == 'GoalPlaySoundNode':
        return ir.ActionPlaySound(
            id=name,
            sound_name=node.sound_name,
            volume=node.volume,
            positional=node.positional,
        )

    if idn == 'GoalSendEventNode':
        return ir.ActionSendEvent(
            id=name,
            target_name=node.target_name,
            target_mode=ir.AddressMode[node.target_mode],
            event_name=node.event_name,
        )

    if idn == 'GoalKillTargetNode':
        return ir.ActionKillTarget(
            id=name,
            target_name=node.target_name,
            target_mode=ir.AddressMode[node.target_mode],
        )

    if idn == 'GoalDeactivateSelfNode':
        return ir.ActionDeactivateSelf(id=name)

    if idn == 'GoalSetSettingNode':
        return ir.ActionSetSetting(
            id=name,
            setting_key=node.setting_key,
            mode=node.mode,
            value=node.value,
            duration=ir.Value(_socket_value(_input_by_name(node, "Duration")), ir.Unit.SECONDS),
        )

    if idn == 'GoalRawNode':
        return ir.ActionRawGoal(id=name, slot=node.slot, body=node.body)

    if idn == 'GoalWaitNode':
        return ir.ActionWait(
            id=name,
            duration=ir.Value(_socket_value(_input_by_name(node, "Duration")), ir.Unit.SECONDS),
        )

    if idn == 'GoalSequenceNode':
        steps = []
        for i in range(1, 5):
            out = next((o for o in node.outputs if o.name == f"Step {i}"), None)
            if out is None:
                continue
            targets = _linked_targets(out)
            if not targets:
                continue
            if len(targets) > 1:
                raise WalkError(
                    f"Sequence '{node.name}' Step {i} has multiple connections; "
                    f"each step must connect to exactly one action."
                )
            steps.append(_build_action(targets[0]))
        return ir.ActionSequence(id=name, steps=steps)

    raise WalkError(f"Unknown action node type: {idn}")


def _build_trigger(node) -> ir.Trigger:
    """Convert a Trigger node + its wired actions into an IR Trigger."""
    name = _slug(node.name)
    idn  = node.bl_idname

    # Walk the "Fires" output to collect gated + instant actions.
    fires_out = next((o for o in node.outputs if o.name == "Fires"), None)
    if fires_out is None:
        raise WalkError(f"Trigger '{node.name}' has no 'Fires' output — node likely corrupt.")
    gated, instant = _collect_actions(_linked_targets(fires_out))

    if idn == 'GoalOnSpawnNode':
        return ir.TriggerOnSpawn(id=name, gated_actions=gated, instant_actions=instant)

    if idn == 'GoalOnEventNode':
        return ir.TriggerOnEvent(
            id=name, event_name=node.event_name,
            gated_actions=gated, instant_actions=instant,
        )

    if idn == 'GoalOnVolEnteredNode':
        return ir.TriggerOnVolEntered(id=name, gated_actions=gated, instant_actions=instant)

    if idn == 'GoalOnProximityNode':
        return ir.TriggerOnProximity(
            id=name,
            distance=ir.Value(_socket_value(_input_by_name(node, "Distance")), ir.Unit.METERS),
            xz_only=node.xz_only,
            gated_actions=gated, instant_actions=instant,
        )

    if idn == 'GoalOnTimeElapsedNode':
        return ir.TriggerOnTimeElapsed(
            id=name,
            delay=ir.Value(_socket_value(_input_by_name(node, "Delay")), ir.Unit.SECONDS),
            gated_actions=gated, instant_actions=instant,
        )

    if idn == 'GoalOnEveryNFramesNode':
        return ir.TriggerOnEveryNFrames(
            id=name, every_n=node.every_n,
            gated_actions=gated, instant_actions=instant,
        )

    raise WalkError(f"Unknown trigger node type: {idn}")


def _collect_actions(action_nodes) -> tuple[list, list]:
    """Partition a list of reachable action nodes into (gated, instant)
    based on each action's IR CATEGORY."""
    gated, instant = [], []
    for n in action_nodes:
        a = _build_action(n)
        if a.CATEGORY in (ir.ActionCategory.CONTINUOUS, ir.ActionCategory.TIMED):
            gated.append(a)
        else:
            # INSTANT, SEQUENCE, WAIT — all fire-site inline
            instant.append(a)
    return gated, instant


# ---------------------------------------------------------------------------
# Top-level walk
# ---------------------------------------------------------------------------

def tree_to_graph(tree) -> ir.Graph:
    """Entry point — walk a Blender GoalNodeTree into an IR Graph."""
    # 1. Find the Entity node.
    entities = [n for n in tree.nodes if n.bl_idname == 'GoalEntityNode']
    if not entities:
        raise WalkError("No Entity node in graph. Add one via Shift+A → Entity.")
    if len(entities) > 1:
        raise WalkError(
            f"{len(entities)} Entity nodes in graph. A graph must have exactly one."
        )
    entity_node = entities[0]

    if not entity_node.etype.strip():
        raise WalkError("Entity has no Type Name. Fill it in on the Entity node.")

    # 2. Walk the Attach output.
    attach_out = next((o for o in entity_node.outputs if o.name == "Attach"), None)
    if attach_out is None:
        raise WalkError("Entity is missing its Attach output — node likely corrupt.")

    direct_actions: list = []
    triggers: list = []

    for target in _linked_targets(attach_out):
        kind = target.bl_idname
        if kind.startswith('GoalOn'):
            triggers.append(_build_trigger(target))
        else:
            # Direct action. Instant actions go in direct_actions directly.
            # Continuous/timed direct actions also go in direct_actions — they
            # run from frame one.
            direct_actions.append(_build_action(target))

    entity = ir.Entity(
        etype=entity_node.etype.strip(),
        direct_actions=direct_actions,
        triggers=triggers,
    )
    return ir.Graph(entity=entity)
