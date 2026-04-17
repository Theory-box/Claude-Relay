"""
GOAL Node Compiler — Template Library

Each function here takes an action or trigger instance and returns a
Contributions dict — the per-slot code fragments that get assembled into
the final deftype/defstate/defmethod.

Contributions slots:
  fields     list[str]   lines to add inside deftype ((field-name type))
  init       list[str]   lines to add inside init-from-entity! body
  trans      list[str]   lines to add inside :trans body (per-frame)
  event      dict[str, list[str]]  event_name -> case-branch body
                         (e.g. 'trigger -> ["(go foo)", ...])
  code       list[str]   lines to add inside :code body (before the terminal loop)
  post       str | None  override for :post handler (usually transform-post)
  top_level  list[str]   extra top-level forms (defun, defmethod, etc.)

Gate flags are applied by the emitter, not the templates — templates emit
unconditional bodies, the emitter wraps them in `(when (-> self gate-X) ...)`
when a trigger gates the action.

Unique field naming is the emitter's job too — templates reference
"self.angle" abstractly, emitter substitutes "self angle-0", "angle-1", etc.
Every template uses `f'{a.id}-NAME'` placeholder that gets normalized upstream.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from .ir import (
    Action, Axis, Value, AddressMode,
    ActionRotate, ActionOscillate, ActionLerpAlongAxis,
    ActionPlaySound, ActionSendEvent, ActionKillTarget,
    ActionDeactivateSelf, ActionSetSetting, ActionRawGoal,
    ActionWait, ActionSequence,
    Trigger, TriggerKind,
    TriggerOnSpawn, TriggerOnEvent, TriggerOnVolEntered,
    TriggerOnProximity, TriggerOnTimeElapsed, TriggerOnEveryNFrames,
)


@dataclass
class Contributions:
    fields:    list[str]                        = field(default_factory=list)
    init:      list[str]                        = field(default_factory=list)
    trans:     list[str]                        = field(default_factory=list)
    event:     dict[str, list[str]]             = field(default_factory=dict)
    code:      list[str]                        = field(default_factory=list)
    post:      str | None                       = None
    top_level: list[str]                        = field(default_factory=list)


# ============================================================================
# ACTION TEMPLATES — continuous
# ============================================================================

def rotate_contrib(a: ActionRotate, field_prefix: str) -> Contributions:
    """Continuous rotation around an axis.

    Emits an angle accumulator field, inits to 0, increments each frame,
    applies as quaternion-axis-angle!.

    Matches spin-prop pattern from goal-code-examples.md §1.
    """
    angle_name = f"{field_prefix}-angle"
    axis_vec   = a.axis.vec_triple()
    speed      = a.speed.emit()
    return Contributions(
        fields = [f"({angle_name} float)"],
        init   = [f"(set! (-> this {angle_name}) 0.0)"],
        trans  = [
            f"(+! (-> self {angle_name}) {speed})",
            f"(quaternion-axis-angle! (-> self root quat) {axis_vec} (-> self {angle_name}))",
        ],
        post = "transform-post",
    )


def oscillate_contrib(a: ActionOscillate, field_prefix: str) -> Contributions:
    """Sine-wave oscillate along an axis.

    Needs:
      base-N float    captured on init (the axis component of trans at spawn)
      timer-N float   ticks accumulator

    Per frame:
      timer++
      offset = amplitude * sin(65536 * (timer / period_ticks))
      trans.{axis} = base + offset

    period_ticks = period_seconds * 300 (engine runs at 300 ticks/sec).
    """
    base_name  = f"{field_prefix}-base"
    timer_name = f"{field_prefix}-timer"
    axis_field = a.axis.field()
    amp        = a.amplitude.emit()
    period     = a.period.emit()
    return Contributions(
        fields = [
            f"({base_name}  float)",
            f"({timer_name} float)",
        ],
        init = [
            f"(set! (-> this {base_name})  (-> this root trans {axis_field}))",
            f"(set! (-> this {timer_name}) 0.0)",
        ],
        trans = [
            f"(+! (-> self {timer_name}) 1.0)",
            f"(let ((_frac (/ (-> self {timer_name}) (the float {period}))))",
            f"  (set! (-> self root trans {axis_field})",
            f"        (+ (-> self {base_name}) (* {amp} (sin (* 65536.0 _frac))))))",
        ],
        post = "transform-post",
    )


# ============================================================================
# ACTION TEMPLATES — timed
# ============================================================================

def lerp_along_axis_contrib(a: ActionLerpAlongAxis, field_prefix: str) -> Contributions:
    """Lerp a relative distance along an axis over duration.

    Fields:
      base-N     float  (start position on that axis)
      t-N        float  (0..1 progress)
      active-N   symbol (#t while lerping)

    When gate goes true, active flips #t, t starts at 0.
    Each frame while active: t += delta, trans.axis = base + distance * t.
    When t >= 1, active flips back #f.

    The emitter handles the gate-flag wiring and the "active" field is set
    by the gate itself — template just references it by name.
    """
    base_name = f"{field_prefix}-base"
    t_name    = f"{field_prefix}-t"
    active    = f"{field_prefix}-active"
    axis_f    = a.axis.field()
    dist      = a.distance.emit()
    # Duration as a raw float seconds for the per-frame step math.
    # delta_t_per_frame = seconds-per-frame / duration_seconds
    # Convert Value (which could be (seconds N)) to raw float N by reading .n.
    dur_sec   = a.duration.n
    return Contributions(
        fields = [
            f"({base_name} float)",
            f"({t_name}    float)",
            f"({active}    symbol)",
        ],
        init = [
            f"(set! (-> this {base_name}) (-> this root trans {axis_f}))",
            f"(set! (-> this {t_name})    0.0)",
            f"(set! (-> this {active})    #f)",
        ],
        trans = [
            f"(when (-> self {active})",
            f"  (set! (-> self {t_name})",
            f"        (fmin 1.0 (+ (-> self {t_name}) (/ (seconds-per-frame) {dur_sec}))))",
            f"  (set! (-> self root trans {axis_f})",
            f"        (+ (-> self {base_name}) (* {dist} (-> self {t_name}))))",
            f"  (when (>= (-> self {t_name}) 1.0)",
            f"    (set! (-> self {active}) #f)))",
        ],
        post = "transform-post",
    )


# ============================================================================
# ACTION TEMPLATES — instant
# ============================================================================
# Instant actions emit a list of GOAL forms that get inlined wherever they're
# fired from (event branch, code body, init body). The returned Contributions
# puts them in `trans` as a placeholder; the emitter routes them by context.
# We use a special key "_body" to be unambiguous.

def _body(*lines: str) -> Contributions:
    """Helper: build a Contributions whose body we'll inline elsewhere.
    The actual routing (event vs init vs code) is done by the emitter based on
    where the trigger firing this action sits."""
    c = Contributions()
    c._body = list(lines)  # type: ignore[attr-defined]
    return c


def play_sound_contrib(a: ActionPlaySound, _field_prefix: str) -> Contributions:
    name = a.sound_name or "no-sound"
    opts = []
    if a.volume != 100.0:
        opts.append(f":vol {a.volume}")
    if not a.positional:
        opts.append(":position #f")
    opts_str = (" " + " ".join(opts)) if opts else ""
    return _body(f'(sound-play "{name}"{opts_str})')


def send_event_contrib(a: ActionSendEvent, _field_prefix: str) -> Contributions:
    # LITERAL: bake the string into the compiled code.
    # LUMP:    read from (-> self LUMP-FIELD) — emitter will add the field.
    if a.target_mode == AddressMode.LITERAL:
        target_expr = f'"{a.target_name}"'
    else:  # LUMP
        # Field name matches lump key (GOAL convention). Hyphens kept.
        target_expr = f"(-> self {a.target_name})"
    return _body(
        f"(let ((_t (process-by-ename {target_expr})))",
        f"  (when _t (send-event _t '{a.event_name})))",
    )


def kill_target_contrib(a: ActionKillTarget, _field_prefix: str) -> Contributions:
    """Kill a named target permanently this session.

    Matches die-relay pattern from goal-code-examples.md and goal-code-runtime.md:
      perm-status dead (prevents respawn)
      deactivate       (kills process now)
    Documented failure mode: do NOT use (send-event tgt 'die) — plat-eco ignores it.
    """
    if a.target_mode == AddressMode.LITERAL:
        target_expr = f'"{a.target_name}"'
    else:
        target_expr = f"(-> self {a.target_name})"
    return _body(
        f"(let ((_t (process-by-ename {target_expr})))",
        "  (when _t",
        "    (process-entity-status! _t (entity-perm-status dead) #t)",
        "    (deactivate _t)))",
    )


def deactivate_self_contrib(_a: ActionDeactivateSelf, _field_prefix: str) -> Contributions:
    return _body("(deactivate self)")


def set_setting_contrib(a: ActionSetSetting, _field_prefix: str) -> Contributions:
    dur = a.duration.emit()
    if a.setting_key in ("music-volume", "sfx-volume", "ambient-volume",
                         "dialog-volume", "bg-a"):
        # mode is meaningful for these
        return _body(f"(set-setting! '{a.setting_key} '{a.mode} {a.value} {dur})")
    # Most other settings: mode slot holds the value, fourth arg is 0
    return _body(f"(set-setting! '{a.setting_key} {a.value} {dur} 0)")


def raw_goal_contrib(a: ActionRawGoal, _field_prefix: str) -> Contributions:
    """Verbatim raw body. Routed to whichever slot `a.slot` names."""
    c = Contributions()
    if a.slot == "trans":
        c.trans = a.body.splitlines()
    elif a.slot == "init":
        c.init = a.body.splitlines()
    elif a.slot == "code":
        c.code = a.body.splitlines()
    elif a.slot == "top_level":
        c.top_level = a.body.splitlines()
    elif a.slot == "event":
        # stored as inline-able body; trigger decides the event name
        c._body = a.body.splitlines()  # type: ignore[attr-defined]
    else:
        # Fallback: treat as trans body
        c.trans = a.body.splitlines()
    return c


def wait_contrib(a: ActionWait, _field_prefix: str) -> Contributions:
    """Wait emits suspend-for. Only valid inside a Sequence's :code body —
    the emitter handles that context. Outside a sequence this will compile
    but will fail goalc typecheck because suspend-for is coroutine-only."""
    return _body(f"(suspend-for {a.duration.emit()})")


def sequence_contrib(_a: ActionSequence, _field_prefix: str) -> Contributions:
    """Sequence generates a dedicated defstate — it doesn't contribute to
    the main state. The emitter handles it via a separate pass that walks
    the steps and builds the new state's :code body. This function exists
    so the dispatch table doesn't NotImplementedError."""
    return Contributions()


# ============================================================================
# DISPATCH: action -> contrib function
# ============================================================================

_ACTION_DISPATCH = {
    ActionRotate:          rotate_contrib,
    ActionOscillate:       oscillate_contrib,
    ActionLerpAlongAxis:   lerp_along_axis_contrib,
    ActionPlaySound:       play_sound_contrib,
    ActionSendEvent:       send_event_contrib,
    ActionKillTarget:      kill_target_contrib,
    ActionDeactivateSelf:  deactivate_self_contrib,
    ActionSetSetting:      set_setting_contrib,
    ActionRawGoal:         raw_goal_contrib,
    ActionWait:            wait_contrib,
    ActionSequence:        sequence_contrib,
}


def contrib_for(action: Action, field_prefix: str) -> Contributions:
    fn = _ACTION_DISPATCH.get(type(action))
    if fn is None:
        raise NotImplementedError(f"No template for action type {type(action).__name__}")
    return fn(action, field_prefix)


# ============================================================================
# TRIGGER — detection templates
# ============================================================================
# Triggers contribute differently from actions. They produce:
#   - a "detection site" where the firing logic lives (event case branch,
#     trans polling block, or init/enter inline)
#   - optional fields (e.g. proximity trigger might want a 'fired' flag to
#     prevent re-firing for one-shot cases — not done automatically, user
#     can pair with their own logic)
# Gated action activation (flipping a gate flag) is done by the emitter
# when it composes the trigger's detection site with its gated_actions list.

def trigger_on_spawn_site(t: TriggerOnSpawn) -> dict:
    """On-spawn fires in init-from-entity!. Detection is trivial — just 'always'.
    Returns a dict describing where/how the firing code goes."""
    return {"site": "init", "wrap": None}


def trigger_on_event_site(t: TriggerOnEvent) -> dict:
    return {"site": "event", "event_name": t.event_name, "wrap": None}


def trigger_on_vol_site(_t: TriggerOnVolEntered) -> dict:
    """VOL_ Entered listens for 'trigger (the vol-trigger subsystem sends it)."""
    return {"site": "event", "event_name": "trigger", "wrap": None}


def trigger_on_proximity_site(t: TriggerOnProximity) -> dict:
    """Polled in :trans — distance check."""
    dist_fn = "vector-vector-xz-distance" if t.xz_only else "vector-vector-distance"
    # Inner check condition; emitter wraps firing body in (when COND ...)
    cond = (f"(and *target* "
            f"(< ({dist_fn} (-> self root trans) (-> *target* control trans)) "
            f"{t.distance.emit()}))")
    return {"site": "trans", "cond": cond, "wrap": None}


def trigger_on_time_site(t: TriggerOnTimeElapsed) -> dict:
    """Polled in :trans — time since spawn."""
    # state-time is built-in on process; set during init to current-time.
    # Condition: state-time has elapsed by `delay`.
    cond = f"(time-elapsed? (-> self state-time) {t.delay.emit()})"
    return {"site": "trans", "cond": cond, "wrap": None}


def trigger_on_every_n_site(t: TriggerOnEveryNFrames) -> dict:
    cond = f"(zero? (mod (-> *display* base-frame-counter) {t.every_n}))"
    return {"site": "trans", "cond": cond, "wrap": None}


_TRIGGER_DISPATCH = {
    TriggerOnSpawn:         trigger_on_spawn_site,
    TriggerOnEvent:         trigger_on_event_site,
    TriggerOnVolEntered:    trigger_on_vol_site,
    TriggerOnProximity:     trigger_on_proximity_site,
    TriggerOnTimeElapsed:   trigger_on_time_site,
    TriggerOnEveryNFrames:  trigger_on_every_n_site,
}


def site_for(trigger: Trigger) -> dict:
    fn = _TRIGGER_DISPATCH.get(type(trigger))
    if fn is None:
        raise NotImplementedError(f"No site for trigger type {type(trigger).__name__}")
    return fn(trigger)
