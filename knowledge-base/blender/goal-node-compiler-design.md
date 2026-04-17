# GOAL Node Compiler — Design

> Complete mental model for the graph-to-GOAL compiler implemented in `addons/goal_node_compiler/`.
> Reflects what actually works, tested end-to-end against 13 patterns from `goal-code-examples.md` and `goal-scripting.md`.
> **Status:** Prototype complete, Blender-independent. UI bindings and Blender-side graph→IR adapter not yet built — intentionally. This doc describes the compiler; the UI will be designed after it, informed by what we learned here.

---

## 1. Mental model

Every entity graph decomposes into three roles:

| Role      | Purpose                                                               | Count per graph |
|---        |---                                                                    |---              |
| Entity    | Root node — declares the `deftype` name, binds to an `ACTOR_` empty   | Exactly 1       |
| Trigger   | Detects *when* something fires                                        | 0..N            |
| Action    | Describes *what* to do                                                | 0..N            |

Actions stack. Multiple continuous Actions attached directly to the Entity all run every frame in parallel. A Trigger wraps Actions — its Actions only run when it fires. Actions are categorised by execution shape:

| Category    | Examples                              | Where code lives             |
|---          |---                                    |---                           |
| INSTANT     | PlaySound, SendEvent, KillTarget      | Inlined at fire site         |
| CONTINUOUS  | Rotate, Oscillate                     | `:trans` body every frame    |
| TIMED       | LerpAlongAxis                         | `:trans` with internal timer |
| SEQUENCE    | Sequence                              | Dedicated `defstate` in `:code` |
| WAIT        | Wait (only valid inside a Sequence)   | `(suspend-for ...)` inline   |

The critical observation that makes this tractable: every action type is a small fixed template. Composition is just string concatenation into the right slot.

---

## 2. Compilation algorithm

Four passes on the IR, in order:

### Pass 1 — Validation (fail fast, in Python)

`validate(graph)` runs 20 checks (see [Validation categories](#9-validation-categories) below). Returns a list of `Issue(level, where, message)`. If any `ERROR` issues, `compile_graph` raises `CompileError` with all issues attached — no emit.

This pass is the *entire reason* the compiler exists in Python instead of being a text template. Catching `meters`-vs-raw-float mixups at graph time is dramatically better than finding them in the goalc build log.

### Pass 2 — Normalise

Every Action gets a stable `index`, used for unique field name generation. Field prefix policy: `{id_slug}-{index}`. So two Rotate nodes named `r1` and `r2` never collide; their angle fields are `r1-0-angle` and `r2-1-angle`.

### Pass 3 — Accumulate

Walks the graph. For each node, calls its template contribution function, which returns a `Contributions` record with per-slot code fragments:

```python
@dataclass
class Contributions:
    fields:    list[str]                      # inside deftype
    init:      list[str]                      # inside init-from-entity!
    trans:     list[str]                      # inside :trans body
    event:     dict[str, list[str]]           # :event case branches
    code:      list[str]                      # inside main state's :code body
    post:      str | None                     # :post handler override
    top_level: list[str]                      # extra top-level forms
```

Instant actions return a special `_body` attribute that the accumulator routes based on context:
- Direct-to-Entity instants → `init` slot
- Trigger-fired instants → firing site (event branch or polled-trans block)
- Sequence steps → dedicated state's `:code` body

Gated continuous/timed actions get their `trans` body wrapped in `(when (-> self gate-<trigger-id>) ...)`. The gate flag is a `symbol` field added to the entity, initialised `#f` (or `#t` if the trigger is OnSpawn), and flipped by the trigger's firing body.

Sequences get special handling: they register a dedicated state in `acc.extra_states` rather than contributing to the main state. The firing trigger emits `(go <etype>-seq-<id>)` as its body.

### Pass 4 — Render

Assembles accumulated slots into Lisp:

```
(deftype <etype> (process-drawable)
  (<fields>)
  (:states <main-state> <seq-states...>))

(defstate <main-state> (<etype>)
  :event ...         ; if any triggers are event-based
  :trans ...         ; if any polled triggers or continuous actions
  :code (loop (suspend))
  :post <post-handler>)   ; if any action requires transform-post

(defstate <seq-state> (<etype>)   ; repeated per sequence
  :code (behavior () <steps...>))

(defmethod init-from-entity! ((this <etype>) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  <init slot>
  (go <main-state>)
  (none))
```

---

## 3. IR shape

Blender-independent dataclasses (`ir.py`). JSON-serialisable. The Blender adapter — not yet written — will walk a `GoalNodeTree` and produce a `Graph` instance.

Key types:

- **`Graph`** — wraps one `Entity`. One graph = one compilation unit = one `deftype`.
- **`Entity`** — `etype`, `direct_actions`, `triggers`.
- **`Action`** — base with `id` + `index` (assigned by normalise). Concrete types: `ActionRotate`, `ActionOscillate`, `ActionLerpAlongAxis`, `ActionPlaySound`, `ActionSendEvent`, `ActionKillTarget`, `ActionDeactivateSelf`, `ActionSetSetting`, `ActionRawGoal`, `ActionWait`, `ActionSequence`.
- **`Trigger`** — base with `id` + `kind`, two action lists: `gated_actions` (continuous/timed that activate when the trigger fires) and `instant_actions` (one-shots that run inline when the trigger fires). Concrete types: `TriggerOnSpawn`, `TriggerOnEvent`, `TriggerOnVolEntered`, `TriggerOnProximity`, `TriggerOnTimeElapsed`, `TriggerOnEveryNFrames`.
- **`Value`** — a float + `Unit` (`RAW`, `METERS`, `DEGREES`, `SECONDS`). `.emit()` wraps with the correct GOAL macro.
- **`AddressMode`** — `LITERAL` (hardcode target string) or `LUMP` (read from actor lump at init). See [Lump-mode targets](#8-lump-mode-vs-literal-mode-targets).

Why not use Blender node tree objects directly as IR? Three reasons: (a) the emitter is unit-testable without Blender, (b) a future non-Blender frontend stays possible, (c) the IR normalises graph topology so the emitter doesn't care about socket connections — only resolved action lists.

---

## 4. Integration with `opengoal_tools`

The compiler does NOT modify `write_gc`. Instead, it integrates via the existing `og_goal_code_ref` pipeline:

```
[Blender-side, one day]
  graph on ACTOR_*.og_goal_graph_ref    # future PointerProperty
              │
              ▼
  walker (TBD) produces Graph IR
              │
              ▼
  compile_graph(graph)                   # this compiler
              │
              ▼
  GOAL source string
              │
              ▼
  writes/updates a bpy.types.Text block named "<etype>-goal-code-generated"
              │
              ▼
  sets ACTOR_*.og_goal_code_ref.text_block = that block
              │
              ▼
  existing write_gc picks it up unchanged   # export.py:1024-1062
              │
              ▼
  appended to <level>-obs.gc
```

This means **zero changes to the existing export pipeline**. The compiler is a pre-pass before export. The generated text block is visible in Blender's Text Editor — doubling as a "see what the graph compiled to" debug view, which matters because compiler errors surface in the goalc build log with line numbers pointing at generated code the user didn't write.

**Entity-name convention matches existing behaviour:** `ACTOR_<etype>_<uid>` → entity lump name `<etype>-<uid>`. The compiler emits `deftype <etype>` and the addon's existing spawner creates the `ACTOR_<etype>_<uid>` empties.

**VOL_ wiring already works:** the `TriggerOnVolEntered` node is a `:event 'trigger` handler. The existing `collect_custom_triggers` path in `export.py:463` auto-generates the `vol-trigger` actor that sends `'trigger` to our entity. The compiler does not need to know about VOL_ meshes — it just declares the event handler.

---

## 5. Unit-typed sockets — not cosmetic

`goal-code-runtime.md §Unit System` documents that `(meters 10.0)` stores `40960.0` raw units (× 4096), while a raw float `10.0` stored in a lump reads back as `10.0` — roughly 2.4 millimeters in game space. Mixing the two silently breaks distance checks, giving a "proximity trigger fires immediately on spawn and never makes sense" bug that's hard to debug without knowing the convention.

The IR represents this with `Unit.METERS` / `Unit.DEGREES` / `Unit.SECONDS` / `Unit.RAW`. The validator rejects `Unit.RAW` where a unit-qualified value is expected (Oscillate amplitude, Proximity distance, Lerp duration, etc.). At the socket level (once bound to Blender), distinct socket types + distinct colours make mis-wiring physically impossible without an explicit conversion.

**This is the single best feature of the node approach over text editing.** The text editor has no way to enforce this. Graph typing eliminates the whole class of bug.

---

## 6. Gate-flag mechanics

How Rotate-plugged-into-OnEvent compiles:

1. Rotate contributes `rot-0-angle float` to fields and an init clear.
2. Trigger registers a gate flag field `gate-<trigger-id> symbol`, init `#f`.
3. Rotate's `:trans` body is wrapped: `(when (-> self gate-<id>) <rotate-body>)`.
4. Trigger's firing body (in `:event`) is `(set! (-> self gate-<id>) #t)`.

When the trigger fires, the gate flips, and next frame Rotate's body runs. This keeps everything in the single main state — no state transitions needed for simple gating.

Timed actions (LerpAlongAxis) also get a per-action `active: symbol` field that resets on trigger fire and clears when the lerp completes. Two levels of gating: the trigger's `gate-<id>` + the action's own `<prefix>-active`. Firing body for timed actions: `(set! ... gate) #t`, `(set! ... t) 0.0`, `(set! ... active) #t`.

---

## 7. Sequence mechanics

Waits inside an event handler fail goalc typecheck — `(suspend-for)` is coroutine-only (`:code` body only). So sequences *can't* be inlined in the event branch. They compile to a dedicated `defstate` whose `:code` body runs the step chain.

**Compiled shape:**
- `deftype` `:states` list includes `<etype>-main` plus one `<etype>-seq-<id>` per Sequence.
- Trigger firing body: `(go <etype>-seq-<id>)`.
- Sequence state's `:code`: instants inlined, Waits as `(suspend-for (seconds N))`, terminal is `(go <main>)` unless a step is `DeactivateSelf` (in which case `(deactivate self)` terminates).

**Tradeoff:** while the entity is in a seq-state, the main state's `:trans` doesn't run. Continuous actions on the same entity pause during sequence playback. For Level A this is acceptable — most sequence-driven entities are one-shot scripted events. Long-term, the child-process pattern from `goal-scripting.md §16` would fix this but adds non-trivial complexity.

Validation enforces:
- Sequence steps must be INSTANT or WAIT (no CONTINUOUS/TIMED — they'd never complete)
- No nested sequences
- No sequences direct-to-Entity (must be trigger-gated)
- No Waits outside a Sequence

---

## 8. Lump-mode vs literal-mode targets

Problem: two actors in the same scene share an etype but should target different things. Hardcoded string targets produce ONE `deftype` body — they can't both be right.

Solution: `AddressMode.LUMP`. When `ActionSendEvent` or `ActionKillTarget` uses `LUMP` mode, the `target_name` field is interpreted as a **lump KEY** rather than a literal. The emitter:
1. Declares `<lump-key> string` field on the entity.
2. Emits `(set! (-> this <lump-key>) (res-lump-struct arg0 '<lump-key> string))` in `init-from-entity!`.
3. Action bodies read `(-> self <lump-key>)` instead of a string literal.

Users set the lump value per-actor via the existing Custom Lumps panel. One deftype, many actors, different targets. Matches the canonical hand-written `die-relay` pattern from `goal-code-system.md §4` exactly.

Multiple actions referencing the same lump key share the field (dedup).

**Default is still LITERAL** — simpler for the common single-instance case. LUMP is opt-in per action.

---

## 9. Validation categories

20 checks, implemented in `validate.py`. Every one exists because of a specific failure mode documented in the source research docs or discovered building this.

| Category            | Check |
|---                  |--- |
| Entity              | Missing etype; invalid etype format; reserved etype (plat-eco, camera-marker…); empty entity warns |
| Units               | Oscillate amplitude must be Meters; Proximity distance must be Meters; Lerp duration must be Seconds; Wait duration must be Seconds |
| Numeric ranges      | Oscillate period > 0; Lerp duration > 0; Proximity distance > 0 (warn); every-N ≥ 1; every-N > 300 warns; PlaySound volume in 0..100 |
| Name collisions     | Duplicate action IDs; duplicate trigger IDs; multiple triggers on same event name (warn); multiple motion actions on same axis (warn) |
| Required params     | PlaySound has sound name; SendEvent has target + event; KillTarget has target; RawGoal slot valid |
| Sequence/Wait       | Sequence direct-to-Entity rejected; Wait outside Sequence rejected; continuous step in Sequence rejected; nested Sequences rejected; empty Sequence warns |

`ERROR`-level issues abort compilation. `WARN`-level issues print to stderr and continue.

---

## 10. Known limitations (Level A scope)

What this compiler deliberately does NOT do:

1. **Multi-state machines beyond sequences.** The `toggle-door`-style 4-state pattern (closed/opening/open/closing) is faked with two gated lerps. Works, but less idiomatic than hand-written. Real multi-state needs Level B (multiple `defstate` with `(go)` transitions between them) — ~300 more lines of compiler work.
2. **Skeletal animation.** No `defskelgroup`, no `ja` macro support. Requires art assets in the DGO anyway — not a pure-code feature.
3. **Waypoint paths.** `path-control` init and `eval-path-curve!` are undocumented at the graph level. Follow-up work.
4. **Parent/child processes.** Sequences pause other behaviour because they don't spawn children. Child-process spawn pattern from `goal-scripting.md §16` would enable concurrent behaviour but adds considerable complexity.
5. **Cross-actor dedup.** Two actors sharing an etype must have IDENTICAL graphs. The compiler doesn't yet detect when two actors have different graphs for the same etype — it'll produce two conflicting deftypes. Needs a scene-level pre-pass.
6. **Richer lump types.** Only `string` lumps supported for LUMP-mode targets. `meters` / `vector` / `float` lumps for arbitrary parameterisation are a straightforward extension.
7. **`:enter` / `:exit` handlers.** Currently no way to express state entry/exit hooks. Sequences transition via `(go)` but don't run enter/exit logic. The `scripted-sequence` docs example uses `:enter` to set controls-lock; we skip that for now.

---

## 11. Files

```
addons/goal_node_compiler/
├── __init__.py              exports public API
├── ir.py                    IR dataclasses (blender-free)
├── templates.py             per-node-type contribution functions
├── emitter.py               graph walker + renderer
├── validate.py              20 validation rules
└── tests/
    ├── test_emitter.py      13 end-to-end compile tests
    └── test_validate.py     20 validation tests
```

Not yet written:
- Blender-side `GoalNodeTree` subclass (earlier skeleton in `goal_nodes_skeleton.py` is deliberately disconnected)
- Blender tree → IR adapter (walks nodes + links, produces `Graph`)
- Pre-export hook that runs compile for each actor with a graph

Those come after UI/flow decisions.

---

## 12. Sanity-checked against the docs

13 end-to-end tests in `test_emitter.py` produce GOAL that matches the hand-written patterns in `knowledge-base/opengoal/` within the Level A scope. The matches are structural — exact whitespace and field names differ, but the emitted Lisp should compile through goalc and behave equivalently:

| Test                        | Source pattern                    | Match quality |
|---                          |---                                |---            |
| spin-prop                   | `goal-code-examples.md §1`        | near-identical |
| float-bob                   | `goal-code-examples.md §2`        | near-identical |
| spin + bob stacked          | (graph-native, no docs precedent) | structural (shows stacking win) |
| die-relay (literal)         | `goal-code-system.md §4`          | identical shape, target hardcoded |
| die-relay (lump mode)       | `goal-code-system.md §4`          | identical |
| proximity-relay             | `goal-code-system.md §5`          | near-identical |
| prox-sound-trigger          | `goal-scripting.md §17 Ex.1`      | simplified (no camera cam-name lump) |
| on-spawn play-sound         | (novel, trivial)                  | expected |
| rotator-on-cue              | (novel, demonstrates gating)      | expected |
| toggle-door                 | `goal-code-examples.md §3`        | approximate (Level A, no states) |
| raw-weird                   | escape hatch                      | verbatim |
| scripted-sequence           | `goal-scripting.md §17 Ex.4`      | approximate (no :enter/:exit) |
| throttled-checker           | `goal-code-runtime.md §Detection` | identical pattern |
