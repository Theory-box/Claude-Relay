"""
End-to-end tests for the emitter.

Each test constructs an IR graph by hand for a pattern documented in
knowledge-base/opengoal/goal-code-examples.md or goal-code-system.md,
compiles it, and prints the result side-by-side with commentary.

Run: python3 -m goal_node_compiler.tests.test_emitter
"""

from goal_node_compiler import (
    Graph, Entity, Axis, Unit, Value, AddressMode,
    ActionRotate, ActionOscillate, ActionLerpAlongAxis,
    ActionPlaySound, ActionSendEvent, ActionKillTarget,
    ActionDeactivateSelf, ActionSetSetting, ActionRawGoal,
    ActionWait, ActionSequence,
    TriggerOnSpawn, TriggerOnEvent, TriggerOnVolEntered,
    TriggerOnProximity, TriggerOnTimeElapsed, TriggerOnEveryNFrames,
    compile_graph,
)


def _header(title):
    return "=" * 70 + f"\n{title}\n" + "=" * 70


# ============================================================================
# Example 1: spin-prop — continuous rotation
# ============================================================================

def test_spin_prop():
    g = Graph(entity=Entity(
        etype="spin-prop",
        direct_actions=[
            ActionRotate(id="rot", axis=Axis.Y, speed=Value(1.0, Unit.DEGREES)),
        ],
    ))
    print(_header("Example 1: spin-prop (continuous rotation)"))
    print(compile_graph(g))


# ============================================================================
# Example 2: float-bob — sine oscillation
# ============================================================================

def test_float_bob():
    g = Graph(entity=Entity(
        etype="float-bob",
        direct_actions=[
            ActionOscillate(
                id="bob",
                axis=Axis.Y,
                amplitude=Value(0.5, Unit.METERS),
                period=Value(3.0, Unit.SECONDS),
            ),
        ],
    ))
    print(_header("Example 2: float-bob (sine wave oscillation)"))
    print(compile_graph(g))


# ============================================================================
# Stacked continuous actions — NEW: spin + bob on same entity
# ============================================================================

def test_spin_and_bob():
    """This is a genuine advantage of the node graph: a user can stack
    continuous actions trivially. Hand-writing this means merging two deftypes
    manually. The graph just does it."""
    g = Graph(entity=Entity(
        etype="twirling-bobber",
        direct_actions=[
            ActionRotate(id="rot", axis=Axis.Y, speed=Value(1.0, Unit.DEGREES)),
            ActionOscillate(
                id="bob", axis=Axis.Y,
                amplitude=Value(0.5, Unit.METERS),
                period=Value(2.0, Unit.SECONDS),
            ),
        ],
    ))
    print(_header("Stacked: spin + bob on one entity"))
    print(compile_graph(g))


# ============================================================================
# die-relay — VOL_ trigger kills a target
# ============================================================================

def test_die_relay_via_event():
    """Same shape as goal-code-system.md §4. VOL_ trigger from the addon's
    vol-trigger subsystem sends 'trigger to us. We kill a target + self."""
    g = Graph(entity=Entity(
        etype="die-relay",
        triggers=[
            TriggerOnVolEntered(
                id="vol",
                instant_actions=[
                    ActionKillTarget(id="kill", target_name="plat-eco-0"),
                    ActionDeactivateSelf(id="dc"),
                ],
            ),
        ],
    ))
    print(_header("die-relay — On VOL_ Entered → kill target + self"))
    print(compile_graph(g))


def test_die_relay_with_lump():
    """Same as die-relay, but target is read from a lump on the actor.
    This lets many actors share this etype and kill different targets —
    the fix for the cross-instance-conflict issue from last session."""
    g = Graph(entity=Entity(
        etype="die-relay",
        triggers=[
            TriggerOnVolEntered(
                id="vol",
                instant_actions=[
                    ActionKillTarget(
                        id="kill",
                        target_name="target-name",   # lump KEY, not literal
                        target_mode=AddressMode.LUMP,
                    ),
                    ActionDeactivateSelf(id="dc"),
                ],
            ),
        ],
    ))
    print(_header("die-relay (lump mode) — reusable across many actors"))
    print(compile_graph(g))


# ============================================================================
# proximity-relay — poll proximity to Jak, kill target when close
# ============================================================================

def test_proximity_relay():
    g = Graph(entity=Entity(
        etype="proximity-relay",
        triggers=[
            TriggerOnProximity(
                id="prox",
                distance=Value(10.0, Unit.METERS),
                xz_only=False,
                instant_actions=[
                    ActionKillTarget(id="kill", target_name="plat-eco-0"),
                    ActionDeactivateSelf(id="dc"),
                ],
            ),
        ],
    ))
    print(_header("proximity-relay — proximity check → kill target + self"))
    print(compile_graph(g))


# ============================================================================
# Prox → sound + camera switch
# ============================================================================

def test_prox_sound_trigger():
    g = Graph(entity=Entity(
        etype="prox-sound-trigger",
        triggers=[
            TriggerOnProximity(
                id="prox",
                distance=Value(5.0, Unit.METERS),
                instant_actions=[
                    ActionPlaySound(id="sfx", sound_name="power-on"),
                    ActionSendEvent(
                        id="cam",
                        target_name="*camera*",  # camera global
                        event_name="change-to-entity-by-name",
                    ),
                    ActionDeactivateSelf(id="dc"),
                ],
            ),
        ],
    ))
    print(_header("prox-sound-trigger — proximity → sound + camera + self-kill"))
    print(compile_graph(g))


# ============================================================================
# On-spawn one-shot — demonstrates ON_SPAWN trigger vs direct-action
# ============================================================================

def test_on_spawn_play_sound():
    g = Graph(entity=Entity(
        etype="jingle-marker",
        triggers=[
            TriggerOnSpawn(
                id="spawn",
                instant_actions=[
                    ActionPlaySound(id="sfx", sound_name="secret-found", positional=False),
                ],
            ),
        ],
    ))
    print(_header("jingle-marker — play a sound on spawn"))
    print(compile_graph(g))


# ============================================================================
# Gated continuous action — rotate starts only on trigger
# ============================================================================

def test_trigger_gates_rotation():
    """Rotate wired THROUGH a trigger instead of directly to Entity.
    Expected: rotate code is wrapped in (when (-> self gate-X) ...) and the
    trigger body flips the gate flag."""
    g = Graph(entity=Entity(
        etype="rotator-on-cue",
        triggers=[
            TriggerOnEvent(
                id="go",
                event_name="trigger",
                gated_actions=[
                    ActionRotate(id="rot", axis=Axis.Y, speed=Value(2.0, Unit.DEGREES)),
                ],
            ),
        ],
    ))
    print(_header("rotator-on-cue — rotation starts when 'trigger received"))
    print(compile_graph(g))


# ============================================================================
# toggle-door — the known-hard Level A case
# ============================================================================

def test_toggle_door():
    """The tricky one. In Level B this is a 4-state machine.
    Level A approximation: two gated lerps, one per event.
    Expected output will work for the simple open-on-trigger case but
    re-triggering won't close (closing would be a SEPARATE lerp with
    opposite distance). Documents the limitation."""
    g = Graph(entity=Entity(
        etype="toggle-door",
        triggers=[
            TriggerOnEvent(
                id="open",
                event_name="trigger",
                gated_actions=[
                    ActionLerpAlongAxis(
                        id="go-up",
                        axis=Axis.Y,
                        distance=Value(4.0, Unit.METERS),
                        duration=Value(0.5, Unit.SECONDS),
                    ),
                ],
            ),
            TriggerOnEvent(
                id="close",
                event_name="untrigger",
                gated_actions=[
                    ActionLerpAlongAxis(
                        id="go-dn",
                        axis=Axis.Y,
                        distance=Value(-4.0, Unit.METERS),
                        duration=Value(0.5, Unit.SECONDS),
                    ),
                ],
            ),
        ],
    ))
    print(_header("toggle-door — open on 'trigger, close on 'untrigger"))
    print(compile_graph(g))


# ============================================================================
# Raw GOAL escape hatch — arbitrary custom code
# ============================================================================

def test_raw_goal():
    """The escape valve. User drops Lisp directly into the :trans slot."""
    g = Graph(entity=Entity(
        etype="raw-weird",
        direct_actions=[
            ActionRawGoal(
                id="raw",
                slot="trans",
                body="(format 0 \"weird entity tick~%\")",
            ),
        ],
    ))
    print(_header("raw-weird — Raw GOAL escape hatch emits verbatim"))
    print(compile_graph(g))


# ============================================================================
# On-every-N-frames — throttled trigger
# ============================================================================

def test_scripted_sequence():
    """The Example 4 pattern from goal-scripting.md §17.
    Proximity → sequence of (fade out, sound, camera switch, wait, revert,
    fade in, self-kill). Covers Sequence, Wait, and the sequence-state emit."""
    g = Graph(entity=Entity(
        etype="scripted-sequence",
        triggers=[
            TriggerOnProximity(
                id="prox",
                distance=Value(5.0, Unit.METERS),
                instant_actions=[
                    ActionSequence(
                        id="run",
                        steps=[
                            ActionSetSetting(
                                id="fade-out",
                                setting_key="bg-a",
                                mode="abs",
                                value=1.0,
                                duration=Value(0.5, Unit.SECONDS),
                            ),
                            ActionWait(id="w1", duration=Value(0.5, Unit.SECONDS)),
                            ActionPlaySound(id="sfx", sound_name="secret-found", positional=False),
                            ActionSendEvent(
                                id="cam-in",
                                target_name="*camera*",
                                event_name="change-to-entity-by-name",
                            ),
                            ActionWait(id="w2", duration=Value(2.0, Unit.SECONDS)),
                            ActionSendEvent(
                                id="cam-out",
                                target_name="*camera*",
                                event_name="clear-entity",
                            ),
                            ActionSetSetting(
                                id="fade-in",
                                setting_key="bg-a",
                                mode="abs",
                                value=0.0,
                                duration=Value(0.5, Unit.SECONDS),
                            ),
                            ActionDeactivateSelf(id="done"),
                        ],
                    ),
                ],
            ),
        ],
    ))
    print(_header("scripted-sequence — Proximity → multi-step timed Sequence"))
    print(compile_graph(g))


def test_every_n_frames():



    """Matches the frame-throttled pattern from goal-code-runtime.md §Detection."""
    g = Graph(entity=Entity(
        etype="throttled-checker",
        triggers=[
            TriggerOnEveryNFrames(
                id="tick",
                every_n=4,
                instant_actions=[
                    ActionRawGoal(
                        id="log",
                        slot="event",   # not used for every_n; bodies go inline
                        body="(format 0 \"tick~%\")",
                    ),
                ],
            ),
        ],
    ))
    print(_header("throttled-checker — fires every 4 frames"))
    print(compile_graph(g))


# ============================================================================
# RUN ALL
# ============================================================================

if __name__ == "__main__":
    tests = [
        test_spin_prop,
        test_float_bob,
        test_spin_and_bob,
        test_die_relay_via_event,
        test_die_relay_with_lump,
        test_proximity_relay,
        test_prox_sound_trigger,
        test_on_spawn_play_sound,
        test_trigger_gates_rotation,
        test_toggle_door,
        test_raw_goal,
        test_scripted_sequence,
        test_every_n_frames,
    ]
    for t in tests:
        t()
        print()
