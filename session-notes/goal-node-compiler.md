# GOAL Node Compiler — Session Notes

**Branch:** `feature/goal-node-compiler`
**Started:** April 17, 2026
**Status:** Prototype compiler + validation complete. Ready for UI discussion.

## Goal

Build a node-graph → GOAL source compiler that can express the Level-A recipe-assembler scope. User plugs actions into Entity (continuous) or into Triggers (gated). Emitter walks the graph and produces a valid `deftype` + `defstate` + `defmethod init-from-entity!` block that matches the hand-written patterns in `knowledge-base/opengoal/goal-code-examples.md`.

UI is deliberately out of scope for this phase. The emitter is validated against a JSON-serialisable intermediate representation (IR) that a later UI pass can populate from actual Blender nodes.

## What shipped

### Code
- `addons/goal_node_compiler/ir.py` — Blender-independent IR dataclasses
- `addons/goal_node_compiler/templates.py` — per-node-type contribution functions
- `addons/goal_node_compiler/emitter.py` — graph walker + GOAL source renderer
- `addons/goal_node_compiler/validate.py` — 20 validation rules
- `addons/goal_node_compiler/tests/test_emitter.py` — 13 end-to-end compile tests
- `addons/goal_node_compiler/tests/test_validate.py` — 20 validation tests

### Knowledge docs
- `knowledge-base/blender/goal-node-compiler-design.md` — complete mental model, compilation algorithm, integration with `opengoal_tools`, limitations
- `knowledge-base/blender/goal-node-vocabulary.md` — every node type documented with parameters, emissions, validation

### Test pass status
- 13/13 emitter tests produce reasonable GOAL
- 20/20 validation tests pass

## What the compiler covers

Node vocabulary (20 types):
- 1 Entity
- 6 Triggers (OnSpawn / OnEvent / OnVolEntered / OnProximity / OnTimeElapsed / OnEveryNFrames)
- 11 Actions
  - Motion: Rotate, Oscillate, LerpAlongAxis, (SetPosition)
  - Signal: PlaySound, SendEvent, KillTarget, DeactivateSelf, SetSetting
  - Flow: Sequence, Wait
  - Escape: RawGoal

Features:
- Gate-flag wiring for trigger-gated continuous/timed actions
- Unit-typed values (Meters/Degrees/Seconds) prevent the 2.4mm footgun
- Lump-mode targeting for multi-instance reuse of a single deftype
- Sequence → dedicated defstate with (suspend-for) Waits
- Integration with existing `og_goal_code_ref` pipeline — no changes to `write_gc` required

Validation catches: missing/invalid/reserved etypes, unit mismatches, name collisions, missing required parameters, sequence containment rules, wait-outside-sequence.

## What's deferred

Documented in `goal-node-compiler-design.md §10`:
- Multi-state machines beyond sequences (Level B)
- Skeletal animation
- Waypoint paths
- Child-process spawn for concurrent behaviour during sequences
- Cross-actor etype deduplication
- `:enter` / `:exit` state hooks
- Richer lump types beyond string

## Not yet built (intentional)

- Blender-side `GoalNodeTree` class (the earlier skeleton file is disconnected from this compiler)
- The Blender tree → IR adapter
- Pre-export hook that runs `compile_graph` for each actor with a graph and writes the output to a generated text block

These come after UI/flow decisions, which is the next conversation.

## Progress log

- [x] Session 1: IR, templates, emitter core, 12 emitter tests passing
- [x] Session 1: LUMP-mode target support
- [x] Session 2: 20-rule validator, 15 validation tests
- [x] Session 2: Sequence + Wait (dedicated defstates, suspend-for between steps)
- [x] Session 2: Sequence containment validation (5 more validation tests)
- [x] Session 2: Design doc
- [x] Session 2: Vocabulary catalogue
- [ ] Blender-side adapter (after UI discussion)
- [ ] End-to-end compile-and-build against a real level (after adapter)
