"""
Validation tests — make sure the validator catches bad graphs before
the emitter produces bad GOAL.

Each test constructs a known-bad graph and asserts the expected error
category surfaces. If validation ever regresses, these fail loudly.
"""

from goal_node_compiler import (
    Graph, Entity, Axis, Unit, Value, AddressMode,
    ActionRotate, ActionOscillate, ActionLerpAlongAxis,
    ActionPlaySound, ActionSendEvent, ActionKillTarget,
    ActionDeactivateSelf, ActionSetSetting, ActionRawGoal,
    ActionWait, ActionSequence,
    TriggerOnSpawn, TriggerOnEvent, TriggerOnVolEntered,
    TriggerOnProximity, TriggerOnTimeElapsed, TriggerOnEveryNFrames,
)
from goal_node_compiler.validate import validate, Level


def _expect_error_containing(g: Graph, substring: str, label: str):
    issues = validate(g)
    errors = [i for i in issues if i.level == Level.ERROR]
    found = any(substring.lower() in i.message.lower() for i in errors)
    if not found:
        print(f"FAIL [{label}]: expected error containing {substring!r}")
        for i in issues:
            print(f"  got: {i}")
    else:
        print(f"PASS [{label}]: {substring!r} surfaced")


def _expect_warn_containing(g: Graph, substring: str, label: str):
    issues = validate(g)
    warns = [i for i in issues if i.level == Level.WARN]
    found = any(substring.lower() in i.message.lower() for i in warns)
    if not found:
        print(f"FAIL [{label}]: expected warning containing {substring!r}")
        for i in issues:
            print(f"  got: {i}")
    else:
        print(f"PASS [{label}]: {substring!r} warned")


def _expect_clean(g: Graph, label: str):
    issues = validate(g)
    errors = [i for i in issues if i.level == Level.ERROR]
    if errors:
        print(f"FAIL [{label}]: expected clean graph, got errors:")
        for i in errors:
            print(f"  {i}")
    else:
        print(f"PASS [{label}]: clean")


# ============================================================================
# ENTITY-LEVEL FAILURES
# ============================================================================

def test_missing_etype():
    g = Graph(entity=Entity(etype=""))
    _expect_error_containing(g, "no etype", "missing etype")


def test_invalid_etype():
    g = Graph(entity=Entity(etype="MyDoor"))  # uppercase + no hyphen style
    _expect_error_containing(g, "lowercase", "uppercase etype")


def test_reserved_etype():
    g = Graph(entity=Entity(
        etype="plat-eco",
        direct_actions=[ActionRotate(id="r", axis=Axis.Y,
                                     speed=Value(1.0, Unit.DEGREES))],
    ))
    _expect_error_containing(g, "built-in", "reserved etype shadowing")


def test_empty_entity_warns():
    g = Graph(entity=Entity(etype="do-nothing"))
    _expect_warn_containing(g, "no actions", "empty entity warns")


# ============================================================================
# UNIT-SYSTEM FAILURES — the footgun from goal-code-runtime.md
# ============================================================================

def test_oscillate_raw_amplitude_rejected():
    """The 'value 10.0 = ~2.4mm' bug documented in runtime doc."""
    g = Graph(entity=Entity(
        etype="bad-bob",
        direct_actions=[
            ActionOscillate(
                id="bob",
                amplitude=Value(0.5, Unit.RAW),     # WRONG
                period=Value(3.0, Unit.SECONDS),
            ),
        ],
    ))
    _expect_error_containing(g, "meters", "oscillate raw amplitude rejected")


def test_proximity_raw_distance_rejected():
    g = Graph(entity=Entity(
        etype="bad-prox",
        triggers=[
            TriggerOnProximity(
                id="p",
                distance=Value(5.0, Unit.RAW),      # WRONG
                instant_actions=[ActionDeactivateSelf(id="dc")],
            ),
        ],
    ))
    _expect_error_containing(g, "meters", "proximity raw distance rejected")


def test_lerp_bad_duration_unit():
    g = Graph(entity=Entity(
        etype="bad-lerp",
        triggers=[
            TriggerOnEvent(id="ev", event_name="trigger",
                gated_actions=[
                    ActionLerpAlongAxis(
                        id="lerp",
                        distance=Value(4.0, Unit.METERS),
                        duration=Value(0.5, Unit.RAW),   # WRONG
                    ),
                ],
            ),
        ],
    ))
    _expect_error_containing(g, "seconds", "lerp raw duration rejected")


# ============================================================================
# NAME-COLLISION FAILURES
# ============================================================================

def test_duplicate_action_ids():
    g = Graph(entity=Entity(
        etype="dupe-actions",
        direct_actions=[
            ActionRotate(id="same", axis=Axis.Y, speed=Value(1.0, Unit.DEGREES)),
            ActionRotate(id="same", axis=Axis.X, speed=Value(2.0, Unit.DEGREES)),
        ],
    ))
    _expect_error_containing(g, "unique", "duplicate action IDs")


def test_duplicate_trigger_ids():
    g = Graph(entity=Entity(
        etype="dupe-triggers",
        triggers=[
            TriggerOnEvent(id="t", event_name="trigger",
                instant_actions=[ActionDeactivateSelf(id="a1")]),
            TriggerOnEvent(id="t", event_name="untrigger",
                instant_actions=[ActionDeactivateSelf(id="a2")]),
        ],
    ))
    _expect_error_containing(g, "used 2 times", "duplicate trigger IDs")


def test_multiple_oscillates_same_axis_warns():
    """Two Oscillates fighting on same axis — last write wins."""
    g = Graph(entity=Entity(
        etype="two-bobs",
        direct_actions=[
            ActionOscillate(id="b1", axis=Axis.Y,
                amplitude=Value(0.5, Unit.METERS),
                period=Value(3.0, Unit.SECONDS)),
            ActionOscillate(id="b2", axis=Axis.Y,
                amplitude=Value(1.0, Unit.METERS),
                period=Value(2.0, Unit.SECONDS)),
        ],
    ))
    _expect_warn_containing(g, "write", "two oscillates same axis warns")


# ============================================================================
# ACTION-PARAM FAILURES
# ============================================================================

def test_play_sound_missing_name():
    g = Graph(entity=Entity(
        etype="silent",
        triggers=[TriggerOnSpawn(id="s",
            instant_actions=[ActionPlaySound(id="snd", sound_name="")])],
    ))
    _expect_error_containing(g, "no sound name", "play sound empty name")


def test_kill_target_missing():
    g = Graph(entity=Entity(
        etype="bad-kill",
        triggers=[TriggerOnEvent(id="ev", event_name="trigger",
            instant_actions=[ActionKillTarget(id="k", target_name="")])],
    ))
    _expect_error_containing(g, "target", "kill missing target")


def test_raw_goal_bad_slot():
    g = Graph(entity=Entity(
        etype="bad-raw",
        direct_actions=[
            ActionRawGoal(id="raw", slot="banana", body="(+ 1 2)"),
        ],
    ))
    _expect_error_containing(g, "slot", "bad raw goal slot")


# ============================================================================
# SEQUENCE + WAIT FAILURES
# ============================================================================

def test_sequence_direct_to_entity_rejected():
    g = Graph(entity=Entity(
        etype="orphan-seq",
        direct_actions=[
            ActionSequence(id="seq", steps=[
                ActionPlaySound(id="p", sound_name="ding"),
            ]),
        ],
    ))
    _expect_error_containing(g, "gated by a trigger", "sequence direct to entity")


def test_wait_outside_sequence_rejected():
    g = Graph(entity=Entity(
        etype="bad-wait",
        triggers=[TriggerOnEvent(id="e", event_name="trigger",
            instant_actions=[ActionWait(id="w", duration=Value(1.0, Unit.SECONDS))])],
    ))
    _expect_error_containing(g, "outside a Sequence", "wait outside sequence")


def test_sequence_with_continuous_step_rejected():
    g = Graph(entity=Entity(
        etype="bad-seq",
        triggers=[TriggerOnEvent(id="e", event_name="trigger",
            instant_actions=[ActionSequence(id="s", steps=[
                ActionRotate(id="rot", axis=Axis.Y, speed=Value(1.0, Unit.DEGREES)),
            ])])],
    ))
    _expect_error_containing(g, "continuous action", "rotate inside sequence")


def test_nested_sequences_rejected():
    g = Graph(entity=Entity(
        etype="nested-bad",
        triggers=[TriggerOnEvent(id="e", event_name="trigger",
            instant_actions=[
                ActionSequence(id="outer", steps=[
                    ActionSequence(id="inner", steps=[
                        ActionPlaySound(id="p", sound_name="ding"),
                    ]),
                ]),
            ])],
    ))
    _expect_error_containing(g, "Nested sequences", "nested sequences rejected")


def test_clean_scripted_sequence():
    g = Graph(entity=Entity(
        etype="scripted-sequence",
        triggers=[TriggerOnProximity(id="prox",
            distance=Value(5.0, Unit.METERS),
            instant_actions=[ActionSequence(id="run", steps=[
                ActionPlaySound(id="sfx", sound_name="ding"),
                ActionWait(id="w", duration=Value(1.0, Unit.SECONDS)),
                ActionDeactivateSelf(id="dc"),
            ])])],
    ))
    _expect_clean(g, "clean scripted-sequence")


# ============================================================================
# CLEAN GRAPHS — should pass validation
# ============================================================================

def test_clean_spin_prop():
    g = Graph(entity=Entity(
        etype="spin-prop",
        direct_actions=[
            ActionRotate(id="r", axis=Axis.Y, speed=Value(1.0, Unit.DEGREES)),
        ],
    ))
    _expect_clean(g, "clean spin-prop")


def test_clean_die_relay():
    g = Graph(entity=Entity(
        etype="die-relay",
        triggers=[
            TriggerOnVolEntered(id="v",
                instant_actions=[
                    ActionKillTarget(id="k",
                        target_name="target-name",
                        target_mode=AddressMode.LUMP),
                    ActionDeactivateSelf(id="dc"),
                ],
            ),
        ],
    ))
    _expect_clean(g, "clean die-relay (lump mode)")


# ============================================================================
# RUN
# ============================================================================

if __name__ == "__main__":
    print("Entity-level")
    test_missing_etype()
    test_invalid_etype()
    test_reserved_etype()
    test_empty_entity_warns()
    print()
    print("Unit system (the footgun)")
    test_oscillate_raw_amplitude_rejected()
    test_proximity_raw_distance_rejected()
    test_lerp_bad_duration_unit()
    print()
    print("Name collisions")
    test_duplicate_action_ids()
    test_duplicate_trigger_ids()
    test_multiple_oscillates_same_axis_warns()
    print()
    print("Action params")
    test_play_sound_missing_name()
    test_kill_target_missing()
    test_raw_goal_bad_slot()
    print()
    print("Sequence + Wait containment")
    test_sequence_direct_to_entity_rejected()
    test_wait_outside_sequence_rejected()
    test_sequence_with_continuous_step_rejected()
    test_nested_sequences_rejected()
    test_clean_scripted_sequence()
    print()
    print("Clean graphs")
    test_clean_spin_prop()
    test_clean_die_relay()
