"""
GOAL Node Compiler — Emitter

Walks an IR `Graph` and produces a GOAL source string ready for injection
into a level's `<name>-obs.gc`.

Passes:
  1. Normalise   — assign unique field prefixes to actions that need them
  2. Accumulate  — walk graph, collect per-slot contributions
  3. Gate        — wrap continuous/timed actions' trans bodies in gate-flag
                   `when` forms if their trigger requires it
  4. Render      — format everything into deftype/defstate/defmethod strings
"""

from __future__ import annotations
from .ir import (
    Graph, Entity, Action, Trigger,
    ActionCategory,
    ActionRawGoal, ActionSendEvent, ActionKillTarget,
    ActionSequence, ActionWait, ActionDeactivateSelf,
    AddressMode,
    TriggerOnSpawn, TriggerOnEvent, TriggerOnVolEntered,
    TriggerOnProximity, TriggerOnTimeElapsed, TriggerOnEveryNFrames,
)
from .templates import Contributions, contrib_for, site_for


# ============================================================================
# COMPILE ERROR
# ============================================================================

class CompileError(Exception):
    pass


# ============================================================================
# PASS 1 — NORMALISE
# ============================================================================

def _all_actions(e: Entity) -> list[Action]:
    out = list(e.direct_actions)
    for t in e.triggers:
        out.extend(t.gated_actions)
        out.extend(t.instant_actions)
    return out


def normalise(g: Graph) -> None:
    """Assigns a stable `index` to every action so field names are unique.
    In-place mutation. Safe to call multiple times (idempotent by sort order).
    """
    actions = _all_actions(g.entity)
    # Stable ordering: direct_actions first in list order, then trigger-by-trigger
    for i, a in enumerate(actions):
        a.index = i


def _field_prefix(a: Action, etype: str) -> str:
    """Stable prefix for fields owned by this action.

    Using the action's IR id keeps names meaningful (e.g. 'rot-a-angle');
    using index keeps them guaranteed unique across renamings.
    Current policy: `{id_slug}-{index}`.
    """
    slug = a.id.replace(" ", "-").lower()
    return f"{slug}-{a.index}"


def _gate_flag_name(t: Trigger) -> str:
    slug = t.id.replace(" ", "-").lower()
    return f"gate-{slug}"


# ============================================================================
# PASS 2 — ACCUMULATE
# ============================================================================

class _Accumulator:
    """Collects contributions per slot, plus bookkeeping."""

    def __init__(self, etype: str):
        self.etype = etype
        self.fields:    list[str]             = []
        self.init:      list[str]             = []
        self.trans:     list[str]             = []
        # event_name -> body lines
        self.event:     dict[str, list[str]]  = {}
        self.code:      list[str]             = []
        self.post:      str | None            = None
        self.top_level: list[str]             = []
        # Extra states generated from sequences. {state_name: [:code body lines]}
        self.extra_states: dict[str, list[str]] = {}
        # Base state — actions live here. Sequences don't.
        self.main_state = f"{etype}-main"

    # ---- slot merging helpers ----

    def merge_fields(self, c: Contributions):
        self.fields.extend(c.fields)

    def merge_init(self, c: Contributions):
        self.init.extend(c.init)

    def merge_trans(self, c: Contributions):
        self.trans.extend(c.trans)

    def merge_code(self, c: Contributions):
        self.code.extend(c.code)

    def merge_post(self, c: Contributions):
        # Last wins; transform-post has priority if any action requires it.
        if c.post:
            self.post = c.post

    def merge_top(self, c: Contributions):
        self.top_level.extend(c.top_level)

    def add_event_branch(self, event_name: str, body_lines: list[str]):
        self.event.setdefault(event_name, []).extend(body_lines)


def _body_of(contrib: Contributions) -> list[str]:
    """Extract the inline body of an instant-action contribution."""
    body = getattr(contrib, "_body", None)
    if body is None:
        # fallback: treat trans lines as body (shouldn't happen for instant)
        return list(contrib.trans)
    return list(body)


def _register_sequence_state(
    acc: "_Accumulator",
    state_name: str,
    seq: ActionSequence,
    etype: str,
) -> None:
    """Build a defstate for a Sequence. Walks steps, inlining instant-action
    bodies and Waits as (suspend-for ...). At the end, returns to main state
    unless a step ends the process (DeactivateSelf)."""
    code_lines: list[str] = []
    deactivates_self = False
    for step in seq.steps:
        if isinstance(step, ActionDeactivateSelf):
            # This step terminates the process — don't emit the (go main) tail.
            code_lines.append("(deactivate self)")
            deactivates_self = True
            break
        if isinstance(step, ActionSequence):
            # Nested sequences not supported in Level A — validator catches
            # this; here we just no-op defensively.
            continue
        c = contrib_for(step, _field_prefix(step, etype))
        body = _body_of(c)
        code_lines.extend(body)
        # For Raw GOAL with slot != "event", still include its slot contribution
        # (e.g. a raw-goal step with slot="code" should still show up here).
        if isinstance(step, ActionRawGoal) and step.slot == "code":
            code_lines.extend(c.code)
    if not deactivates_self:
        code_lines.append(f"(go {acc.main_state})")
    acc.extra_states[state_name] = code_lines


def _collect_lumps(g: Graph) -> dict[str, str]:
    """Find all LUMP-mode action targets. Returns {lump_key: goal_type}.
    For now only string lumps supported (target names). Extension point later
    for float / meters / vector lumps read by other actions.
    """
    lumps: dict[str, str] = {}
    for a in _all_actions(g.entity):
        if isinstance(a, (ActionSendEvent, ActionKillTarget)):
            if a.target_mode == AddressMode.LUMP and a.target_name:
                # Two actions referencing the same lump key share the field.
                existing = lumps.get(a.target_name)
                if existing and existing != "string":
                    raise CompileError(
                        f"lump '{a.target_name}' referenced with conflicting types"
                    )
                lumps[a.target_name] = "string"
    return lumps


def accumulate(g: Graph) -> _Accumulator:
    acc = _Accumulator(g.entity.etype)

    # -- Lumps used by LUMP-mode actions: add as fields + init reads --
    lumps = _collect_lumps(g)
    for lump_key, goal_type in lumps.items():
        acc.fields.append(f"({lump_key} {goal_type})")
        if goal_type == "string":
            acc.init.append(
                f"(set! (-> this {lump_key}) "
                f"(res-lump-struct arg0 '{lump_key} string))"
            )

    # -- Direct actions (no gate) --
    for a in g.entity.direct_actions:
        c = contrib_for(a, _field_prefix(a, g.entity.etype))
        # Raw GOAL is special: its slot decides routing, not its category.
        if isinstance(a, ActionRawGoal):
            acc.merge_fields(c)
            acc.merge_init(c)
            acc.merge_trans(c)
            acc.merge_code(c)
            acc.merge_top(c)
            for ev, body in c.event.items():
                acc.add_event_branch(ev, body)
            continue
        if a.CATEGORY == ActionCategory.INSTANT:
            # Instant action attached directly to Entity: runs once at spawn.
            # Route to init.
            acc.init.extend(_body_of(c))
        else:
            acc.merge_fields(c)
            acc.merge_init(c)
            acc.merge_trans(c)
        acc.merge_post(c)
        acc.merge_top(c)

    # -- Triggers --
    for t in g.entity.triggers:
        site = site_for(t)

        # Fields + init for gated actions (continuous/timed) — they need
        # accumulator state even when their gate is off.
        for a in t.gated_actions:
            c = contrib_for(a, _field_prefix(a, g.entity.etype))
            acc.merge_fields(c)
            acc.merge_init(c)
            # Wrap trans body in (when (-> self GATE-FLAG) ...)
            if c.trans:
                gate = _gate_flag_name(t)
                acc.merge_fields(Contributions(fields=[f"({gate} symbol)"]))
                # Init gate flag to #f (unless trigger is on-spawn)
                if t.kind.value != "on_spawn":
                    acc.init.append(f"(set! (-> this {gate}) #f)")
                else:
                    acc.init.append(f"(set! (-> this {gate}) #t)")
                wrapped = [f"(when (-> self {gate})"]
                wrapped.extend(f"  {ln}" for ln in c.trans)
                wrapped.append(")")
                acc.trans.extend(wrapped)
            acc.merge_post(c)
            acc.merge_top(c)

        # Firing body = instant actions' bodies inlined + gate flips for gated.
        # Sequences in the instant_actions list get special routing: a trigger
        # firing a Sequence emits (go seq-<id>), and the sequence itself is
        # registered as an extra defstate.
        firing_body: list[str] = []
        for a in t.instant_actions:
            if isinstance(a, ActionSequence):
                seq_state = f"{g.entity.etype}-seq-{a.id}"
                # Register the extra state containing the sequence's :code body
                _register_sequence_state(
                    acc, seq_state, a, g.entity.etype,
                )
                firing_body.append(f"(go {seq_state})")
                continue
            c = contrib_for(a, _field_prefix(a, g.entity.etype))
            firing_body.extend(_body_of(c))
            acc.merge_top(c)
            acc.merge_fields(c)    # raw-goal may add fields
            acc.merge_init(c)
        if t.gated_actions:
            gate = _gate_flag_name(t)
            firing_body.append(f"(set! (-> self {gate}) #t)")
            # Also, for timed actions inside a trigger, flip their 'active' field
            for a in t.gated_actions:
                from .ir import ActionLerpAlongAxis
                if isinstance(a, ActionLerpAlongAxis):
                    prefix = _field_prefix(a, g.entity.etype)
                    firing_body.append(f"(set! (-> self {prefix}-t) 0.0)")
                    firing_body.append(f"(set! (-> self {prefix}-active) #t)")

        # Route firing_body to the right site
        if site["site"] == "event":
            acc.add_event_branch(site["event_name"], firing_body)
        elif site["site"] == "trans":
            cond = site["cond"]
            block = [f"(when {cond}"]
            block.extend(f"  {ln}" for ln in firing_body)
            block.append(")")
            acc.trans.extend(block)
        elif site["site"] == "init":
            acc.init.extend(firing_body)
        else:
            raise CompileError(f"unknown trigger site: {site}")

    return acc


# ============================================================================
# PASS 4 — RENDER
# ============================================================================

_INDENT = "  "


def _indent(lines: list[str], levels: int) -> list[str]:
    pad = _INDENT * levels
    return [pad + ln for ln in lines]


def render_deftype(acc: _Accumulator) -> str:
    # All states: main plus every extra state
    all_states = [acc.main_state] + list(acc.extra_states.keys())
    states_src = " ".join(all_states)

    # Build the fields list. If empty, use `()`; otherwise multi-line.
    if acc.fields:
        type_body = ("(" + "\n   ".join(acc.fields) + ")") if len(acc.fields) > 1 \
                    else f"({acc.fields[0]})"
    else:
        type_body = "()"
    return (
        f"(deftype {acc.etype} (process-drawable)\n"
        f"  {type_body}\n"
        f"  (:states {states_src}))"
    )


def render_extra_state(acc: _Accumulator, state_name: str, body: list[str]) -> str:
    """Render a sequence-generated defstate — :code only, no :trans/:event."""
    out = [f"(defstate {state_name} ({acc.etype})"]
    out.append("  :code")
    out.append("  (behavior ()")
    for ln in body:
        out.append(f"    {ln}")
    out.append("  )")
    out.append(")")
    return "\n".join(out)


def render_defstate(acc: _Accumulator) -> str:
    out = [f"(defstate {acc.main_state} ({acc.etype})"]

    # :event
    if acc.event:
        out.append("  :event")
        out.append("  (behavior ((proc process) (argc int) (message symbol) "
                   "(block event-message-block))")
        out.append("    (case message")
        for event_name, body in acc.event.items():
            out.append(f"      (('{event_name})")
            for ln in body:
                out.append(f"       {ln}")
            out.append("      )")
        out.append("    ))")

    # :trans
    if acc.trans:
        out.append("  :trans")
        out.append("  (behavior ()")
        for ln in acc.trans:
            out.append(f"    {ln}")
        out.append("  )")

    # :code — must exist (the coroutine body). Include extras then loop-suspend.
    out.append("  :code")
    out.append("  (behavior ()")
    for ln in acc.code:
        out.append(f"    {ln}")
    out.append("    (loop (suspend)))")

    # :post
    if acc.post:
        out.append(f"  :post {acc.post}")

    out.append(")")
    return "\n".join(out)


def render_defmethod(acc: _Accumulator) -> str:
    out = [
        f"(defmethod init-from-entity! ((this {acc.etype}) (arg0 entity-actor))",
        "  (set! (-> this root) (new 'process 'trsqv))",
        "  (process-drawable-from-entity! this arg0)",
    ]
    for ln in acc.init:
        out.append(f"  {ln}")
    out.append(f"  (go {acc.main_state})")
    out.append("  (none))")
    return "\n".join(out)


def render(acc: _Accumulator) -> str:
    sections = [
        ";;-*-Lisp-*-",
        "(in-package goal)",
        "",
    ]
    if acc.top_level:
        sections.extend(acc.top_level)
        sections.append("")
    sections.append(render_deftype(acc))
    sections.append("")
    sections.append(render_defstate(acc))
    # Additional defstates generated from Sequences
    for state_name, body in acc.extra_states.items():
        sections.append("")
        sections.append(render_extra_state(acc, state_name, body))
    sections.append("")
    sections.append(render_defmethod(acc))
    return "\n".join(sections) + "\n"


# ============================================================================
# PUBLIC ENTRY POINT
# ============================================================================

def compile_graph(g: Graph, strict: bool = True) -> str:
    """Compile a Graph IR to a GOAL source string.

    Validation runs first. If any ERROR-level issues are found, raises
    CompileError with all issues concatenated. WARN-level issues are
    printed to stderr (caller can suppress via strict=False to silence).
    """
    from .validate import validate, has_errors, Level
    import sys
    issues = validate(g)
    errors = [i for i in issues if i.level == Level.ERROR]
    warns  = [i for i in issues if i.level == Level.WARN]
    if errors:
        msg = "Graph has compile errors:\n" + "\n".join(f"  {i}" for i in issues)
        raise CompileError(msg)
    if warns and strict:
        for w in warns:
            print(f"  WARN: {w}", file=sys.stderr)
    normalise(g)
    acc = accumulate(g)
    return render(acc)
