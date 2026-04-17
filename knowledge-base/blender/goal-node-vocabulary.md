# GOAL Node Vocabulary

> Every node in the Level-A vocabulary documented as implemented in `addons/goal_node_compiler/`. Partner document to `goal-node-compiler-design.md` which covers the compiler architecture.
> Each entry lists: parameters, what it emits to which slots, example input/output, validation rules.
> Confidence levels per entry reflect how thoroughly the pattern has been tested against the hand-written examples in `knowledge-base/opengoal/`.

---

## Entity

**IR:** `Entity(etype: str, direct_actions: list[Action], triggers: list[Trigger])`
**Role:** Root of every graph. Names the `deftype` and binds (on the Blender side) to an `ACTOR_` empty.

**Parameters:**
- `etype` (str, required) — lowercase letters/digits/hyphens; matches the Custom Type Spawner rules. Example: `spin-prop`, `die-relay`.

**Validation:**
- Missing etype → ERROR
- Uppercase, underscores, special chars → ERROR
- Matches a reserved built-in (`plat-eco`, `camera-marker`, `vol-trigger`, `babak`, etc.) → ERROR
- No actions and no triggers → WARN ("will spawn and sit idle forever")

**Emits:** `deftype <etype> (process-drawable) ...`, plus the `defmethod init-from-entity!` boilerplate with the standard `trsqv` root and `process-drawable-from-entity!` call.

---

## Triggers

Triggers detect *when*. Each one has a detection site (`:event` branch or `:trans` polling block) and fires the Actions plugged into it.

### OnSpawn

**IR:** `TriggerOnSpawn(id, gated_actions, instant_actions)`
**When:** Once, during `init-from-entity!`.
**Instant actions:** inlined directly into `init`.
**Gated actions:** their gate flag is initialised `#t` instead of `#f` so they run from frame one.

```
Entity(spin-at-start)
  └─ OnSpawn
       ├─ ActionPlaySound("chime")
       └─ gated Rotate (axis=Y, 1°/tick)
```

Emits (excerpt):
```lisp
(defmethod init-from-entity! ((this spin-at-start) (arg0 entity-actor))
  ...
  (sound-play "chime")
  (set! (-> this gate-onspawn) #t)   ; note: #t, not #f
  (go spin-at-start-main))
```

### OnEvent

**IR:** `TriggerOnEvent(id, event_name, gated_actions, instant_actions)`
**When:** Entity receives a specific event (`'trigger`, `'untrigger`, `'touch`, `'attack`, `'die`, `'notify`, or a custom symbol).

Emits a `case` branch in `:event`:
```lisp
:event
(behavior ((proc process) (argc int) (message symbol) (block event-message-block))
  (case message
    (('trigger)
     <instant bodies inlined>
     (set! (-> self gate-<id>) #t))))
```

**Validation:** event name required.

### OnVolEntered

**IR:** `TriggerOnVolEntered(id, gated_actions, instant_actions)`
**When:** Jak enters a VOL_ volume wired to this actor in Blender.

Internally identical to `OnEvent('trigger)` — the existing `vol-trigger` subsystem (`addons/opengoal_tools/export.py:463`) automatically sends `'trigger` on enter and `'untrigger` on exit. Provided as a separate node for UX clarity — users shouldn't need to know which event name the vol-trigger uses.

**Note:** an explicit `OnEvent('trigger)` coexisting with `OnVolEntered` on the same entity produces a WARN (multiple triggers fighting over the same case branch).

### OnProximity

**IR:** `TriggerOnProximity(id, distance: Value, xz_only: bool, gated_actions, instant_actions)`
**When:** Jak's position is within `distance` of the entity.

**Parameters:**
- `distance` — must be `Unit.METERS` (ERROR if RAW — the 2.4mm bug)
- `xz_only` — use `vector-vector-xz-distance` instead of `vector-vector-distance`

Polled in `:trans`:
```lisp
(when (and *target* (< (vector-vector-distance
                          (-> self root trans)
                          (-> *target* control trans))
                       (meters 10.0)))
  <instant bodies>)
```

**Note:** this polls every frame by default. Wrap in an `OnEveryNFrames` + `OnProximity` combination if you need throttling — but that would need a combined node; currently not directly expressible. Workaround: use `Raw GOAL` with the frame-mod pattern from `goal-code-runtime.md §Detection`.

### OnTimeElapsed

**IR:** `TriggerOnTimeElapsed(id, delay: Value, gated_actions, instant_actions)`
**When:** `delay` seconds have passed since the entity spawned.

Emits a `:trans` poll using the built-in `state-time` field:
```lisp
(when (time-elapsed? (-> self state-time) (seconds 2.0))
  <instant bodies>)
```

**Validation:** delay must be `Unit.SECONDS`, must be ≥ 0.
**Note:** Fires every frame after the delay passes. Pair with a fire-once action or `DeactivateSelf` to prevent re-firing.

### OnEveryNFrames

**IR:** `TriggerOnEveryNFrames(id, every_n: int, gated_actions, instant_actions)`
**When:** Every Nth frame. Used for throttled continuous checks.

Emits:
```lisp
(when (zero? (mod (-> *display* base-frame-counter) 4))
  <instant bodies>)
```

Matches the pattern the engine uses for aggro-trigger, camera-trigger, and checkpoint-trigger (runtime doc §Detection). `N=4` ≈ 15Hz at 60fps, a common choice.

**Validation:** N ≥ 1 (ERROR); N > 300 warns ("fires less than once per second — intended?").

---

## Actions — Motion (CONTINUOUS / TIMED)

### Rotate — CONTINUOUS

**IR:** `ActionRotate(id, axis: Axis, speed: Value)`
**Purpose:** Rotate continuously around an axis.

**Parameters:**
- `axis` — X, Y, or Z (the vector triple emitted as `1.0 0.0 0.0` etc.)
- `speed` — `Unit.DEGREES` per tick (WARN if other unit)

**Fields added:** `<prefix>-angle float`
**Init:** `(set! (-> this <prefix>-angle) 0.0)`
**Per frame:**
```lisp
(+! (-> self <prefix>-angle) (degrees 1.0))
(quaternion-axis-angle! (-> self root quat) 0.0 1.0 0.0 (-> self <prefix>-angle))
```
**Post handler:** `transform-post` (required for anything that moves)

**Confidence:** High. Matches `goal-code-examples.md §1` exactly.

### Oscillate — CONTINUOUS

**IR:** `ActionOscillate(id, axis: Axis, amplitude: Value, period: Value)`
**Purpose:** Sine-wave oscillate on an axis (bob, pulse, swing).

**Parameters:**
- `axis` — X/Y/Z field of `trans`
- `amplitude` — `Unit.METERS` (ERROR if not)
- `period` — `Unit.SECONDS` (ERROR if not), must be > 0

**Fields added:**
- `<prefix>-base float` — captures the axis value at spawn
- `<prefix>-timer float` — tick accumulator

**Init:** base captured from `(-> this root trans <axis>)`, timer → 0.
**Per frame:**
```lisp
(+! (-> self <prefix>-timer) 1.0)
(let ((_frac (/ (-> self <prefix>-timer) (the float (seconds 3.0)))))
  (set! (-> self root trans y)
        (+ (-> self <prefix>-base) (* (meters 0.5) (sin (* 65536.0 _frac))))))
```

**Note on units:** `(sin x)` in GOAL takes rotation units where 65536 = 2π. `_frac = timer / period_ticks` ranges 0→1 each cycle, so `(* 65536.0 _frac)` sweeps a full sine wave. Timer in raw ticks, period converted via `(the float (seconds N))`.

**Confidence:** High. Matches `goal-code-examples.md §2`.

### LerpAlongAxis — TIMED

**IR:** `ActionLerpAlongAxis(id, axis, distance: Value, duration: Value)`
**Purpose:** Smoothly move a relative distance along an axis over a duration. Good for door slides, platform movements.

**Parameters:**
- `axis` — trans axis
- `distance` — `Unit.METERS` (signed — negative reverses direction)
- `duration` — `Unit.SECONDS`, > 0

**Fields added:**
- `<prefix>-base float` — start position on this axis
- `<prefix>-t float` — 0..1 progress
- `<prefix>-active symbol` — whether currently animating

**Init:** base captured, t→0, active→#f.
**Per frame (when active):**
```lisp
(when (-> self <prefix>-active)
  (set! (-> self <prefix>-t)
        (fmin 1.0 (+ (-> self <prefix>-t) (/ (seconds-per-frame) 0.5))))
  (set! (-> self root trans y)
        (+ (-> self <prefix>-base) (* (meters 4.0) (-> self <prefix>-t))))
  (when (>= (-> self <prefix>-t) 1.0)
    (set! (-> self <prefix>-active) #f)))
```

**Firing from a trigger:** trigger's body includes `(set! (-> self <prefix>-t) 0.0)` + `(set! (-> self <prefix>-active) #t)` to restart the lerp. Supports retriggering — firing again resets t to 0 and replays.

**Confidence:** Medium-high. Works; the "closing a door" case in `goal-code-examples.md §3` is modelled as a SECOND LerpAlongAxis with negative distance and a separate trigger (since we lack multi-state machines).

---

## Actions — Signal (INSTANT)

All INSTANT actions emit a short body inlined at their fire site. Direct-to-Entity instants go into `init-from-entity!`.

### PlaySound — INSTANT

**IR:** `ActionPlaySound(id, sound_name: str, volume: float, positional: bool)`

**Emits:** `(sound-play "name" :vol 80.0 :position #f)` with optional kwargs depending on parameters.

**Validation:** sound_name required; volume ∈ 0..100.
**Confidence:** Medium — the sound_name has to exist in the loaded SBK; compiler doesn't verify.

### SendEvent — INSTANT

**IR:** `ActionSendEvent(id, target_name: str, target_mode: AddressMode, event_name: str)`

**LITERAL mode** (default):
```lisp
(let ((_t (process-by-ename "plat-eco-0")))
  (when _t (send-event _t 'trigger)))
```

**LUMP mode:**
```lisp
(let ((_t (process-by-ename (-> self target-name))))
  (when _t (send-event _t 'trigger)))
```
When LUMP mode is used, the entity gets `<target-name> string` field + a `res-lump-struct` init read for it. Lump key = the `target_name` field (e.g. `"target-name"`, `"alt-actor"`).

**Validation:** target + event name required.
**Confidence:** High. Matches the pattern from `goal-code-runtime.md §Process Lifecycle`.

### KillTarget — INSTANT

**IR:** `ActionKillTarget(id, target_name: str, target_mode: AddressMode)`

Emits the two-step kill pattern from `goal-code-runtime.md`:
```lisp
(let ((_t (process-by-ename "plat-eco-0")))
  (when _t
    (process-entity-status! _t (entity-perm-status dead) #t)
    (deactivate _t)))
```

Both parts are important: `perm-status dead` prevents respawn on level re-entry, `deactivate` kills the running process now. Do NOT use `(send-event tgt 'die)` — plat-eco ignores it.

LITERAL vs LUMP mode as above.
**Confidence:** High. Matches the canonical `die-relay` pattern.

### DeactivateSelf — INSTANT

**IR:** `ActionDeactivateSelf(id)`
**Emits:** `(deactivate self)`

In sequences, suppresses the automatic `(go <main>)` tail (the process is gone — no state to transition to). This is detected structurally in the sequence-rendering pass.

### SetSetting — INSTANT

**IR:** `ActionSetSetting(id, setting_key: str, mode: str ("abs"|"rel"), value: float, duration: Value)`
**Purpose:** Call `(set-setting! ...)` for music, volume, camera behaviour, etc. See `goal-scripting.md §13` for valid keys.

Emission depends on setting type:
- Volume settings (music-volume, sfx-volume, ambient-volume, dialog-volume, bg-a) take mode:
  `(set-setting! 'bg-a 'abs 1.0 (seconds 0.5))`
- Others use a simpler form:
  `(set-setting! 'allow-progress #f 0.0 0)`

**Confidence:** Medium-high. The "simpler form" branch handles most other keys; edge cases (`'music`, `'sound-flava`) have different argument shapes in the engine and may need their own emission variants.

### RawGoal — ESCAPE HATCH

**IR:** `ActionRawGoal(id, slot: str, body: str)`
**Slots:** `"trans"`, `"code"`, `"init"`, `"event"`, `"top_level"`.
**Emits:** `body` verbatim into the named slot.

The release valve. Anything the vocabulary can't express — unusual math, animations, the `ja` macro, child-process spawning — goes here. Validator just checks the slot name is one of the five accepted values.

**Confidence:** High. It's just string concatenation.

---

## Flow

### Sequence — SEQUENCE

**IR:** `ActionSequence(id, steps: list[Action])`
**Purpose:** Run a linear chain of steps with time-based waits.

**Must be trigger-gated** (validator rejects direct-to-entity sequences).
**Steps must be INSTANT or WAIT** (validator rejects CONTINUOUS/TIMED steps — they'd block the chain).
**No nesting** (validator rejects `ActionSequence` inside a Sequence's steps).

Emits a dedicated `defstate`:
```lisp
(defstate <etype>-seq-<id> (<etype>)
  :code
  (behavior ()
    <step 1 body>
    (suspend-for (seconds 1.0))     ; if step 2 was a Wait
    <step 3 body>
    ...
    (go <etype>-main)))             ; terminal; omitted if DeactivateSelf
```

The triggering firing body becomes `(go <etype>-seq-<id>)`. Sequence state list is automatically added to the deftype's `:states` declaration.

**Tradeoff:** while entity is in seq-state, main state's `:trans` doesn't run. Continuous actions on the same entity effectively pause during a sequence. Level A acceptable; child-process pattern would fix it but adds complexity.

**Confidence:** Medium-high. Tested against `scripted-sequence` pattern from `goal-scripting.md §17`. Not tested in-game; needs real run-through before claiming high confidence.

### Wait — WAIT

**IR:** `ActionWait(id, duration: Value)`
**Emits:** `(suspend-for (seconds N))`
**Only valid inside a Sequence.** Validator rejects Waits used anywhere else (direct-to-entity, or as a trigger's instant_action) because `suspend-for` is coroutine-only — it would fail goalc typecheck.

**Validation:** duration must be `Unit.SECONDS`, > 0.
**Confidence:** High.

---

## Quick reference: what each node contributes

| Node                | fields | init | trans | event | code | post | extra state |
|---                  |:---:   |:---: |:---:  |:---:  |:---: |:---: |:---:         |
| Entity              | –      | –    | –     | –     | –    | –    | –            |
| OnSpawn             | gate¹  | gate init + firing body | – | – | – | – | – |
| OnEvent             | gate¹  | gate init | – | branch body | – | – | – |
| OnVolEntered        | gate¹  | gate init | – | branch body (event='trigger) | – | – | – |
| OnProximity         | gate¹  | gate init | poll block + firing | – | – | – | – |
| OnTimeElapsed       | gate¹  | gate init | poll block + firing | – | – | – | – |
| OnEveryNFrames      | gate¹  | gate init | poll block + firing | – | – | – | – |
| Rotate              | angle  | clear | rotate | – | – | transform-post | – |
| Oscillate           | base, timer | capture, clear | oscillate | – | – | transform-post | – |
| LerpAlongAxis       | base, t, active | capture, clear | lerp-when-active | – | – | transform-post | – |
| SetPosition²        | –      | – | – | – | – | transform-post | – |
| PlaySound           | –      | body (if direct) | – | body (if trigger) | – | – | – |
| SendEvent           | lump³  | body + lump read³ | – | body | – | – | – |
| KillTarget          | lump³  | body + lump read³ | – | body | – | – | – |
| DeactivateSelf      | –      | body | – | body | (deactivate self) in sequences | – | – |
| SetSetting          | –      | body (if direct) | – | body (if trigger) | – | – | – |
| RawGoal             | –      | slot=init | slot=trans | slot=event | slot=code | – | top-level if slot=top_level |
| Wait                | –      | –  | – | – | (suspend-for ...) in sequence | – | – |
| Sequence            | –      | –  | – | – | – | – | new defstate per sequence |

¹ Only when the trigger gates CONTINUOUS or TIMED actions. Pure-instant triggers don't need a gate flag — their firing body runs once and then is done.
² SetPosition is in the IR but not fully exercised by tests.
³ Only in LUMP mode.
