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
- [x] Session 2: Pushed to origin (commit 98a87b2)
- [x] Session 3: Comprehensive brainstorm of advanced vocabulary
      — `knowledge-base/blender/goal-node-advanced-vocabulary-brainstorm.md`
- [x] Session 3: 22 T1-candidate IR skeletons added to ir.py (no templates yet)
- [x] Session 3: T3 research notes on cam-spline, cam-string, particle effects,
      battlecontroller — `knowledge-base/blender/goal-node-t3-research-notes.md`
- [x] Session 3: User-journey walkthroughs across 6 modding scenarios
      — `knowledge-base/blender/goal-node-user-journeys.md`
- [ ] Blender-side adapter (after UI discussion)
- [ ] End-to-end compile-and-build against a real level (after adapter)

## Session 3 outputs

### Brainstorm doc
23 sections covering categories the Level-A vocabulary doesn't touch:
- Scene-query & iteration (the critical gap — collections, ForEach, scene metadata)
- Level & world control (loading, checkpoints, screen effects, mood, time-of-day)
- Game state & progression (perm-status, game tasks, pickup spawning)
- Entity lifecycle (spawn, birth, child processes)
- Conditionals, variables, data flow
- Motion beyond Rotate/Oscillate/Lerp (look-at, path-follow, Jak interactions)
- Expanded camera (cam-spline, cam-string flagged in future-research.md)
- Animation, sound, particle, enemy AI, water, doors-wiring
- Dialogue/HUD, debug/authoring, advanced flow control
- Subgraphs (reusable node groups)
- "What haven't we thought of" section — novel categories worth exploring

### IR skeleton additions
22 new action types as dataclasses (declarations only, no templates):
- ActorSet, ActionForEach (scene iteration)
- ActionSetPermFlag, ActionCheckPermFlag (game state)
- ActionBlackout, ActionFadeToBlack/FromBlack (screen effects)
- ActionCameraSwitchToMarker, ActionCameraClear, ActionCameraTeleport
- ActionLookAtTarget, ActionLookAtJak, ActionPathFollow
- ActionLaunchJak, ActionResetJakHeight
- ActionCueEnemyChase, ActionCueEnemyPatrol, ActionFreezeEnemy
- ActionPlayMusicTrack, ActionStopMusic
- ActionDebugPrint, ActionComment (debug/authoring)
- ActionBirthEntity, ActionMarkEntityDead (level-flow commands)
- ActionIf, ActionRandomChance (conditionals)
- ActorSetSource enum

None have templates yet — attempting to compile a graph with one of these
will raise NotImplementedError from `contrib_for`. That's by design: the
skeleton makes the IR shape tangible before we commit to template bodies.

## Open questions from Session 3 brainstorm (§21)

Need user input before more implementation:
1. Scope ceiling — ~45-node polished Level-A or ~100+ ambitious platform?
2. Subgraphs (Blender node groups) — yes/no?
3. Runtime iteration vs compile-time unrolling for ForEach?
4. Full data-flow graph (variables) or stay pure control-flow?
5. Per-node validation-warning suppression?
6. Graph integration with existing Blender Actor Links / Volume Links panels — own or coexist?
7. ActorsByType prefix matching vs exact match?

## Session 3 T3 research findings

Critical insight from the T3 deep-dive: **cam-spline, cam-string,
particle effects, and battlecontroller are primarily *addon-side* features,
not graph features**. The graph only adds a handful of convenience wrappers
once the addon's scene-authoring surface is extended. This promotes these
items from T3 ("research first") to T2 ("well-scoped, serious modding")
with an addon-first implementation path.

Effort estimates:
- cam-string: ~1 day (2 new lumps, 0 graph nodes)
- battlecontroller: ~4-5 days (new entity type, 9 lumps, 0-2 convenience nodes)
- cam-spline: ~2-3 days (4 lumps + curve export, blocked on knot
  parameterisation research in `cam-states.gc`)
- Particle effects: ~1 week for preset-based approach (15 pre-tuned effects,
  `<level>-part.gc` generator, `EFFECT_` entity category)

None requires compiler work beyond IR skeletons already in place.

## Session 3 user-journey findings

Stress-tested the proposed vocabulary against 6 realistic modding scenarios:
A) Power-cell quest (kill-all-enemies → door → reward)
B) 3-switch puzzle door
C) Boss arena with multi-wave + cinematic reward
D) Timed platforming section with failure reset
E) Cinematic level intro (fade/pan/subtitle/fade)
F) Secret chamber revealed by stomp

Genuinely new T1 nodes uncovered by walkthroughs:
  - CheckAllComplete(actor_set) — critical for kill-all / press-all gating
  - CountInPermState — for partial-completion gating
  - OnVolLeft — relabel of OnEvent('untrigger) for clarity
  - GetCurrentTime, DeclareVariable/SetVariable/GetVariable — Scenario D
    timer pattern cannot work without these

Compiler fixes identified:
  - Auto-allow Sequence under OnSpawn via hidden self-trigger
  - Flag-name enum must include bit-0..bit-10
  - $CURRENT template substitution in ForEach emitter — confirm validated

Strong arguments for T2 features:
  - Subgraphs — cutscene + intro reusability (Scenarios C, E)
  - Variables / data flow — Scenario D blocked without them
  - battlecontroller, cam-spline, particles, subtitles — confirmed needed

Open question 8 raised by walkthroughs:
  "Scene-level graphs" — should logic live on a scene-wide invisible
  director actor rather than tied to a particular ACTOR_ empty? Every
  scenario had at least one 'ghost director' actor. UX concern, not
  compiler concern.

Most-used-across-scenarios ranking (T1 critical subset):
  1. ActorSet (4 scenarios)
  2. SendEvent with variable target + ForEach (4)
  3. SetPermFlag / ClearPermFlag (3)
  4. CameraSwitchToMarker (3)
  5. FadeToBlack / FadeFromBlack (2)
  6. CheckAllComplete (2, but critical)
  7. Variables (1, but blocking)

These are the demo-compelling set.
