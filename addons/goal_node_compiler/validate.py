"""
GOAL Node Compiler — Validation Pass

Catches categories of errors at compile time rather than letting them surface
as cryptic goalc errors referencing generated code. Every validation rule
here is justified by a real failure mode documented in:
  - goal-code-system.md (§7 GOAL Code Rules, §8 Bug Fix History)
  - goal-code-runtime.md (units, event handler typing, entity lookup)
  - goal-code-examples.md (edge cases in the worked examples)

The validator returns a list of `Issue` records. Issues at level=ERROR abort
compilation; level=WARN are reported but compilation continues.

Call `validate(graph)` early — before normalise/accumulate — so users see
problems at their source in the graph rather than in generated Lisp.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .ir import (
    Graph, Entity, Action, Trigger, Unit, Value,
    ActionCategory, AddressMode,
    ActionRotate, ActionOscillate, ActionLerpAlongAxis,
    ActionPlaySound, ActionSendEvent, ActionKillTarget,
    ActionDeactivateSelf, ActionSetSetting, ActionRawGoal,
    ActionWait, ActionSequence,
    TriggerOnSpawn, TriggerOnEvent, TriggerOnVolEntered,
    TriggerOnProximity, TriggerOnTimeElapsed, TriggerOnEveryNFrames,
)


class Level(str, Enum):
    ERROR = "error"
    WARN  = "warn"


@dataclass
class Issue:
    level:   Level
    where:   str            # "<entity>:<node-id>" or similar
    message: str

    def __str__(self) -> str:
        return f"[{self.level.value.upper()}] {self.where}: {self.message}"


# ============================================================================
# ENTITY-LEVEL RULES
# ============================================================================

# Built-in Jak 1 entity type names we should refuse to shadow. Partial list;
# covers the common collision cases. Not exhaustive — the engine has hundreds.
# Source: observed spawner rejection logic + knowledge-base/opengoal/jak1-enemy-definitions.json
_RESERVED_ETYPES = {
    # Camera / trigger / checkpoint — addon generates these itself
    "camera-marker", "camera-trigger", "checkpoint-trigger",
    "aggro-trigger", "vol-trigger",
    # Common platforms
    "plat-eco", "plat-button", "baseplat", "drop-plat",
    # Common enemies (partial — real list is huge)
    "babak", "lurker-crab", "hopper", "snow-bunny", "kermit",
    "yeti", "bully", "mother-spider", "junglesnake",
    # Structural
    "target", "camera", "process", "process-drawable",
}


def _valid_etype(etype: str) -> bool:
    """Must match the addon's spawner rules: lowercase letters, digits, hyphens."""
    if not etype:
        return False
    return all(c.islower() or c.isdigit() or c == "-" for c in etype)


def _validate_entity(e: Entity, issues: list[Issue]) -> None:
    where = f"entity:{e.etype or '<unnamed>'}"
    if not e.etype:
        issues.append(Issue(Level.ERROR, where,
            "Entity has no etype — can't generate a deftype."))
        return
    if not _valid_etype(e.etype):
        issues.append(Issue(Level.ERROR, where,
            f"Invalid etype '{e.etype}' — must be lowercase letters, digits, "
            f"and hyphens only (matches the Custom Type Spawner rules)."))
    if e.etype in _RESERVED_ETYPES:
        issues.append(Issue(Level.ERROR, where,
            f"etype '{e.etype}' conflicts with a built-in engine type."))
    # A useful entity has at least one action somewhere
    if not e.direct_actions and not any(
        t.gated_actions or t.instant_actions for t in e.triggers
    ):
        issues.append(Issue(Level.WARN, where,
            "Entity has no actions — will spawn and sit idle forever."))


# ============================================================================
# ACTION-LEVEL RULES
# ============================================================================

def _validate_action(a: Action, entity: Entity, gated_by: Trigger | None,
                     issues: list[Issue]) -> None:
    where = f"{entity.etype}:{a.id}"

    # --- parameter sanity ---
    if isinstance(a, ActionRotate):
        if a.speed.unit != Unit.DEGREES:
            issues.append(Issue(Level.WARN, where,
                f"Rotate speed should be Degrees, got {a.speed.unit.value} "
                f"— emitter will still emit (degrees N) but result may be "
                f"wrong if values were intended as another unit."))

    elif isinstance(a, ActionOscillate):
        if a.amplitude.unit != Unit.METERS:
            issues.append(Issue(Level.ERROR, where,
                f"Oscillate amplitude must be Meters (was "
                f"{a.amplitude.unit.value}) — raw floats here caused the "
                f"'10.0 = 2.4mm' bug documented in goal-code-runtime.md."))
        if a.period.unit != Unit.SECONDS:
            issues.append(Issue(Level.ERROR, where,
                f"Oscillate period must be Seconds (was {a.period.unit.value})."))
        if a.period.n <= 0:
            issues.append(Issue(Level.ERROR, where,
                "Oscillate period must be > 0 — divide-by-zero otherwise."))

    elif isinstance(a, ActionLerpAlongAxis):
        if a.distance.unit != Unit.METERS:
            issues.append(Issue(Level.ERROR, where,
                f"LerpAlongAxis distance must be Meters "
                f"(was {a.distance.unit.value})."))
        if a.duration.unit != Unit.SECONDS:
            issues.append(Issue(Level.ERROR, where,
                f"LerpAlongAxis duration must be Seconds "
                f"(was {a.duration.unit.value})."))
        if a.duration.n <= 0:
            issues.append(Issue(Level.ERROR, where,
                "LerpAlongAxis duration must be > 0."))

    elif isinstance(a, ActionPlaySound):
        if not a.sound_name:
            issues.append(Issue(Level.ERROR, where,
                "PlaySound has no sound name."))
        if not (0.0 <= a.volume <= 100.0):
            issues.append(Issue(Level.ERROR, where,
                f"PlaySound volume {a.volume} out of 0..100 range."))

    elif isinstance(a, ActionSendEvent):
        if not a.target_name:
            issues.append(Issue(Level.ERROR, where,
                "SendEvent has no target name."))
        if not a.event_name:
            issues.append(Issue(Level.ERROR, where,
                "SendEvent has no event name."))

    elif isinstance(a, ActionKillTarget):
        if not a.target_name:
            issues.append(Issue(Level.ERROR, where,
                "KillTarget has no target."))

    elif isinstance(a, ActionRawGoal):
        if not a.body.strip():
            issues.append(Issue(Level.WARN, where,
                "RawGoal body is empty — node has no effect."))
        if a.slot not in ("trans", "code", "init", "event", "top_level"):
            issues.append(Issue(Level.ERROR, where,
                f"RawGoal slot '{a.slot}' not recognised. "
                f"Use one of: trans, code, init, event, top_level."))

    elif isinstance(a, ActionWait):
        if a.duration.unit != Unit.SECONDS:
            issues.append(Issue(Level.ERROR, where,
                f"Wait duration must be Seconds (was {a.duration.unit.value})."))
        if a.duration.n <= 0:
            issues.append(Issue(Level.ERROR, where,
                "Wait duration must be > 0."))
        # Wait outside a sequence is useless — (suspend-for) in :event context
        # produces a goalc typecheck error.
        # The flag we check: if this action is attached directly to entity or
        # is the direct target of a trigger (not nested in a Sequence), that's
        # the bug. Caller context tracks this via `gated_by`.
        # NOTE: we can't detect the "inside a Sequence" case from gated_by alone;
        # the sequence-embedded Waits are handled by a separate pass
        # (_validate_sequence_steps below) which skips this check.
        pass  # actual containment check happens in sequence validation

    elif isinstance(a, ActionSequence):
        if not a.steps:
            issues.append(Issue(Level.WARN, where,
                "Sequence has no steps — trigger will fire into an empty state."))
        for step in a.steps:
            step_where = f"{entity.etype}:{a.id}/{step.id}"
            # Steps must be instant or wait — continuous/timed never complete
            if step.CATEGORY == ActionCategory.CONTINUOUS:
                issues.append(Issue(Level.ERROR, step_where,
                    f"{type(step).__name__} is a continuous action — it would "
                    f"run forever and block the sequence. Sequences only "
                    f"support Instant and Wait steps."))
            elif step.CATEGORY == ActionCategory.TIMED:
                issues.append(Issue(Level.ERROR, step_where,
                    f"{type(step).__name__} is a timed action — it would "
                    f"block the sequence until its timer finishes. Use Wait "
                    f"+ Set Position instead, or split into multiple triggers."))
            elif isinstance(step, ActionSequence):
                issues.append(Issue(Level.ERROR, step_where,
                    "Nested sequences are not supported."))
            # Otherwise: instant or wait, fine

    # --- gating sanity ---
    if gated_by is not None and a.CATEGORY == ActionCategory.INSTANT:
        # Instant actions plugged into a gated slot still work (they fire once
        # when the trigger fires) — but they belong in the INSTANT list, not
        # gated_actions, because they don't need a gate flag.
        if gated_by.gated_actions and a in gated_by.gated_actions:
            issues.append(Issue(Level.WARN, where,
                "Instant action in gated_actions list — should be in "
                "instant_actions instead. Will still work; the gate flag is "
                "a no-op for one-shot bodies."))


# ============================================================================
# TRIGGER-LEVEL RULES
# ============================================================================

def _validate_trigger(t: Trigger, entity: Entity, issues: list[Issue]) -> None:
    where = f"{entity.etype}:{t.id}"

    if not t.gated_actions and not t.instant_actions:
        issues.append(Issue(Level.WARN, where,
            f"Trigger '{t.id}' fires but has no actions plugged in."))

    # Specific trigger checks
    if isinstance(t, TriggerOnProximity):
        if t.distance.unit != Unit.METERS:
            issues.append(Issue(Level.ERROR, where,
                f"Proximity distance must be Meters (was {t.distance.unit.value}) "
                f"— mixing raw floats with vector-vector-distance is the "
                f"'2.4mm' bug."))
        if t.distance.n <= 0:
            issues.append(Issue(Level.WARN, where,
                f"Proximity distance is {t.distance.n}m — trigger will never fire."))

    elif isinstance(t, TriggerOnTimeElapsed):
        if t.delay.unit != Unit.SECONDS:
            issues.append(Issue(Level.ERROR, where,
                f"TimeElapsed delay must be Seconds (was {t.delay.unit.value})."))
        if t.delay.n < 0:
            issues.append(Issue(Level.ERROR, where,
                "TimeElapsed delay can't be negative."))

    elif isinstance(t, TriggerOnEveryNFrames):
        if t.every_n < 1:
            issues.append(Issue(Level.ERROR, where,
                f"OnEveryNFrames requires N >= 1 (got {t.every_n})."))
        if t.every_n > 300:
            issues.append(Issue(Level.WARN, where,
                f"OnEveryNFrames N={t.every_n} fires less than once per second. "
                f"Intended?"))

    elif isinstance(t, TriggerOnEvent):
        if not t.event_name:
            issues.append(Issue(Level.ERROR, where,
                "OnEvent has no event name."))


# ============================================================================
# CROSS-CUTTING RULES — NAME COLLISIONS, DUPLICATE EVENT HANDLERS
# ============================================================================

def _validate_cross_cutting(e: Entity, issues: list[Issue]) -> None:
    where = f"entity:{e.etype}"

    # Sequences attached directly to Entity — not gated by a trigger. Level A
    # requires sequences to be trigger-fired because sequences transition to a
    # dedicated state; a direct-attached sequence would need init-phase
    # handling which is its own can of worms.
    for a in e.direct_actions:
        if isinstance(a, ActionSequence):
            issues.append(Issue(Level.ERROR,
                f"{e.etype}:{a.id}",
                "Sequence attached directly to Entity — must be gated by a "
                "trigger (use OnSpawn if you want it to run at start)."))

    # Waits outside sequences — (suspend-for ...) is coroutine-only and will
    # fail goalc typecheck in :event / :trans contexts.
    def _action_is_top_level(a: Action, in_sequence: bool) -> list[Issue]:
        out: list[Issue] = []
        if isinstance(a, ActionWait) and not in_sequence:
            out.append(Issue(Level.ERROR,
                f"{e.etype}:{a.id}",
                "Wait used outside a Sequence — suspend-for is coroutine-only, "
                "goalc will reject this. Put it inside a Sequence."))
        return out
    # Direct actions
    for a in e.direct_actions:
        issues.extend(_action_is_top_level(a, in_sequence=False))
    # Trigger actions (not in a sequence — sequence steps are OK)
    for t in e.triggers:
        for a in t.gated_actions:
            issues.extend(_action_is_top_level(a, in_sequence=False))
        for a in t.instant_actions:
            issues.extend(_action_is_top_level(a, in_sequence=False))

    # All action IDs must be unique. Duplicates → duplicate field names.
    all_action_ids: list[str] = []
    for a in e.direct_actions:
        all_action_ids.append(a.id)
    for t in e.triggers:
        for a in t.gated_actions:
            all_action_ids.append(a.id)
        for a in t.instant_actions:
            all_action_ids.append(a.id)

    seen: dict[str, int] = {}
    for aid in all_action_ids:
        seen[aid] = seen.get(aid, 0) + 1
    for aid, count in seen.items():
        if count > 1:
            issues.append(Issue(Level.ERROR, where,
                f"Action ID '{aid}' used {count} times — IDs must be unique "
                f"for deterministic field naming."))

    # All trigger IDs must be unique too.
    trigger_ids = [t.id for t in e.triggers]
    seen.clear()
    for tid in trigger_ids:
        seen[tid] = seen.get(tid, 0) + 1
    for tid, count in seen.items():
        if count > 1:
            issues.append(Issue(Level.ERROR, where,
                f"Trigger ID '{tid}' used {count} times — gate-flag fields "
                f"would collide."))

    # Multiple OnEvent triggers with the same event name = ambiguous case branch.
    event_names: dict[str, list[str]] = {}
    for t in e.triggers:
        if isinstance(t, TriggerOnEvent):
            event_names.setdefault(t.event_name, []).append(t.id)
        elif isinstance(t, TriggerOnVolEntered):
            # VOL listens for 'trigger — conflicts with an OnEvent('trigger)
            event_names.setdefault("trigger", []).append(t.id)
    for event_name, tids in event_names.items():
        if len(tids) > 1:
            issues.append(Issue(Level.WARN, where,
                f"Multiple triggers listen for event '{event_name}': "
                f"{tids}. Case branches will be merged in source order — "
                f"this works but is confusing. Consider merging into one trigger."))

    # Writers-to-same-field detection (simple heuristic: two non-axis-X Rotates,
    # or two Oscillates on the same axis, or two LerpAlongAxis on same axis
    # unless they're gated by mutually-exclusive triggers).
    motion_writers: dict[str, list[str]] = {}
    all_actions_with_triggers: list[tuple[Action, Trigger | None]] = []
    for a in e.direct_actions:
        all_actions_with_triggers.append((a, None))
    for t in e.triggers:
        for a in t.gated_actions + t.instant_actions:
            all_actions_with_triggers.append((a, t))
    for a, _t in all_actions_with_triggers:
        key = None
        if isinstance(a, ActionOscillate):
            key = f"trans.{a.axis.field()}"
        elif isinstance(a, ActionLerpAlongAxis):
            key = f"trans.{a.axis.field()}"
        if key:
            motion_writers.setdefault(key, []).append(a.id)
    for field_path, aids in motion_writers.items():
        if len(aids) > 1:
            issues.append(Issue(Level.WARN, where,
                f"Actions {aids} all write to {field_path} — last write per "
                f"frame wins. If they should run at different times, make "
                f"sure they're gated by mutually-exclusive triggers."))


# ============================================================================
# ENTRY POINT
# ============================================================================

def validate(g: Graph) -> list[Issue]:
    issues: list[Issue] = []
    e = g.entity
    _validate_entity(e, issues)
    for a in e.direct_actions:
        _validate_action(a, e, None, issues)
    for t in e.triggers:
        _validate_trigger(t, e, issues)
        for a in t.gated_actions:
            _validate_action(a, e, t, issues)
        for a in t.instant_actions:
            _validate_action(a, e, t, issues)
    _validate_cross_cutting(e, issues)
    return issues


def has_errors(issues: Iterable[Issue]) -> bool:
    return any(i.level == Level.ERROR for i in issues)
