# GOAL Nodes — User Journey Walkthroughs

> Partner doc to `goal-node-advanced-vocabulary-brainstorm.md` and `goal-node-t3-research-notes.md`.
> Stress-tests the proposed node vocabulary against 6 realistic modding scenarios to find gaps, friction points, and missing primitives the category-by-category brainstorm didn't catch.
> Each walkthrough annotates with `[GAP]` / `[FRICTION]` / `[T?]` tags so we can triage afterwards.

---

## Scenario A — Custom power cell quest

**Narrative:** Arena with 3 enemies. Player kills all enemies. A closed door opens. Behind the door is a power cell pickup.

### Graph structure

```
ACTOR_arena-gate (a door)
  Entity(etype=my-gate)
    OnEvent('all-clear')
      ActionLerpAlongAxis(Y, +4m, 0.5s)       // open

ACTOR_arena-counter (an invisible tracker)
  Entity(etype=arena-counter)
    direct_actions:
      ActorSet(source=BY_ETYPE, etype_filter="babak", id="enemies")
        // resolves at compile time to a list like ["babak-1","babak-2","babak-3"]
    OnEveryNFrames(n=30)                       // poll twice a second
      ActionCheckAllComplete(actor_set="enemies", id="all-done")
        [GAP] "CheckAllComplete" isn't in my vocabulary yet — needed
      If(condition="all-done")
        SendEvent("arena-gate-0", 'all-clear)
        DeactivateSelf

ACTOR_power-cell (spawned on demand, or hidden until gate opens)
  // Handled by existing fuel-cell entity with perm-status gating
```

### Gaps found
- **`[GAP] CheckAllComplete`** — iterate an actor set and test if every member has perm-status `complete` (or `dead`). Emits something like `(and (foreach ...) ...)`. Essential primitive for "kill all" style gating.  **[T1]**
- **`[GAP] CountInPermState`** — count how many in a set have a flag. Enables "kill 5 of 8" partial gating. **[T2]**
- **[FRICTION]** Power-cell placement interacts with the game-task system. Not a node problem — but the graph needs to play nicely with the addon's existing task-wiring UI. **Open question 6** from the brainstorm.

### Alternative: use the engine's built-in battlecontroller
Once `battlecontroller` lands (T2 after T3 research), this becomes one battlecontroller entity with 3 enemies + door as trigger-actor. Much cleaner — no custom `arena-counter` needed. Suggests **battlecontroller should be the recommended pattern** for this class of scenario; the "custom-counter" approach is the power-user fallback.

---

## Scenario B — 3-switch puzzle door

**Narrative:** Three switch-pads in a room. All three must be pressed to open a door. Order doesn't matter. Pressing resets if the player leaves the room (optional).

### Graph structure

```
ACTOR_switch-1, ACTOR_switch-2, ACTOR_switch-3 (each a basebutton)
  // Uses the existing basebutton — no custom graph per switch
  // Button sets its own 'complete' perm-status on press

ACTOR_puzzle-door
  Entity(etype=puzzle-door)
    OnEveryNFrames(n=15)
      ActorSet(source=EXPLICIT, names=["switch-1","switch-2","switch-3"], id="switches")
      If(condition=CheckAllComplete("switches"))
        ActionLerpAlongAxis(Y, +4m, 0.5s)
        // Mark self complete so we don't re-open on later check passes
        MarkComplete(self)
        DeactivateSelf
```

### Gaps found
- **`[GAP] MarkComplete(self)`** — shortcut for "set my own perm-status complete." Already in T1 list, just confirming it's needed.
- **[FRICTION] Polling every 15 frames** — would be cleaner as an event-driven update: "when any switch fires complete, re-check." That means triggers that fire on OTHER actors' perm-status changes, which doesn't exist as an engine primitive cleanly. Polling is acceptable.
- **[NICE] ActorSet with explicit picker by clicking objects in Blender** — user doesn't type object names, they shift-select actors and the list populates. **UX concern, not emission concern.** **[T1 UX]**

### Optional: reset on leaving the room

```
  OnVolLeft(id="room-vol")
    ActionForEach(actor_set="switches")
      ClearPermFlag($current, complete)
```

- **`[GAP] OnVolLeft`** — we have `OnVolEntered` but not `OnVolLeft`. The vol-trigger subsystem sends `'untrigger` on exit; the existing `OnEvent('untrigger')` works but is semantically murky. A dedicated node is clearer. **[T1]**
- **`[GAP] ClearPermFlag`** — T1-listed. Confirmed needed.

---

## Scenario C — Boss arena with multi-wave battle and cutscene reward

**Narrative:** Player enters arena. Camera locks. Wave 1 (3 grunts). Cleared → wave 2 (5 grunts + 1 heavy). Cleared → wave 3 (boss). Boss dies → camera flies around boss's body → dialogue → power cell spawns → camera returns.

### Graph structure

This is mostly scene-authoring + battlecontroller wiring, not a graph-intensive problem.

```
battlecontroller_wave1 (new entity type from §4 of T3 research)
  lumps: num-lurkers=3, lurker-type=[babak], camera-name="boss-cam"
  trigger-actor: battlecontroller_wave2

battlecontroller_wave2
  lumps: num-lurkers=6, lurker-type=[babak,hopper], percent=[0.83,0.17]
  trigger-actor: battlecontroller_wave3

battlecontroller_wave3 (the boss)
  lumps: num-lurkers=1, lurker-type=[...boss...]
  trigger-actor: cutscene-director
```

All three are wired via the existing addon lump system. No graph yet.

Now the cutscene:

```
ACTOR_cutscene-director
  Entity(etype=cutscene-director)
    OnEvent('trigger')
      Sequence(id="finale")
        steps:
          // Lock controls
          SetSetting('allow-progress, false, 0)
          SetSetting('allow-look-around, false, 0)
          // Camera fly-around
          CameraSwitchToMarker("boss-cam-1")
          Wait(1.5s)
          CameraSwitchToMarker("boss-cam-2")
          Wait(2.0s)
          CameraSwitchToMarker("boss-cam-3")
          Wait(1.5s)
          // Dialogue
          [GAP] ShowSubtitle("You have proven yourself.", 3s)
          Wait(3.0s)
          // Reward
          [GAP] SpawnFuelCell(position=[x,y,z], task=N)
          Wait(1.0s)
          // Restore camera and controls
          CameraClear()
          SetSetting('allow-progress, true, 0)
          SetSetting('allow-look-around, true, 0)
          DeactivateSelf
```

### Gaps found
- **`[GAP] ShowSubtitle`** — text display primitive. T3 research item, but modders will scream for it for cutscenes. Needs investigation of subtitle engine hooks. **[T2 after research]**
- **`[GAP] SpawnFuelCell`** — T3 listed; tricky because of task-slot management. **[T3]**
- **[FRICTION] Sequence has 11 steps** — vocabulary works but the graph is long. This is where **Subgraphs** (brainstorm open question 2) would shine: a reusable "Lock-Controls-Do-Stuff-Unlock-Controls" subgraph. Clear argument for Subgraphs in T2.
- **[FRICTION] Camera positions hardcoded by name** — user has to carefully name their `CAMERA_` empties. `CameraPoseRef` / pick-object picker would be friendlier.
- **[FRICTION] Wait durations are guesswork** — 1.5s, 2.0s, 1.5s. In real cutscene authoring you'd want a playable preview. **Out of node-vocab scope; addon-UI concern.**

### Insight

The cutscene pattern is the strongest argument for Subgraphs. Without them, every modder rewrites the same 6-step "lock → do → unlock" skeleton. With them, one well-tuned subgraph becomes a library primitive.

---

## Scenario D — Timed platforming section with failure reset

**Narrative:** Player pulls a lever. A door opens. Three platforms extend. Player has 30 seconds to cross. If time runs out, platforms retract, door closes, player falls or respawns.

### Graph structure

```
ACTOR_timer-controller
  Entity(etype=timer-controller)
    DeclareVariable(name="running", type=symbol, default=#f)
    DeclareVariable(name="start-time", type=time-frame, default=0)

    OnEvent('start')
      SetVariable("running", #t)
      SetVariable("start-time", "current-time")         // new primitive
      // Open door
      SendEvent("gate-0", 'trigger)
      // Extend platforms
      ActorSet(source=BY_NAME_GLOB, name_pattern="ACTOR_plat-*", id="plats")
      ForEach(actor_set="plats")
        SendEvent($current, 'extend)
        [GAP] SendEvent to $current needs the emitter to treat $current as
              a lump-name template substitution during unrolling

    OnEveryNFrames(n=4)
      If(condition="(and (-> self running) (time-elapsed? (-> self start-time) (seconds 30)))")
        // Time's up — reset
        ForEach(actor_set="plats")
          SendEvent($current, 'retract)
        SendEvent("gate-0", 'untrigger)                   // close door
        SetVariable("running", #f)
        [GAP] "TeleportJak" back to safe position — T2, exists in brainstorm

ACTOR_start-lever (basebutton)
  notify-actor: timer-controller
  // When pressed, sends 'trigger (basebutton default) or custom 'start
```

### Gaps found
- **`[GAP] GetCurrentTime`** — read `(current-time)` into a variable. **[T1]**
- **`[FRICTION]` Variables cross the data-flow threshold.** The `start-time` variable is read by an If condition in a different node. My current IR has Values as *static inputs*, not *data flow between nodes*. This is **open question 4** from the brainstorm, now with a concrete use case demanding an answer.
- **`[GAP] ForEach with $current` — the interpolation story.** My current IR says the emitter unrolls and substitutes `$CURRENT$` at unroll time. For `SendEvent` with `target_name=$CURRENT$`, unrolling means emitting N copies of the send-event, each with a different literal name. That works but I need to explicitly validate that substitution is done correctly.
- **`[GAP] "time-elapsed?"` with a self-stored timestamp** — `state-time` works for per-state timers, but an explicit variable is needed for cross-state timing. Engine supports it via `(-> self my-field)`. **Covered by DeclareVariable + GetCurrentTime.**

### Insight

This scenario is the strongest argument for **data-flow nodes / variables**. Without them, the graph would require a single massive Raw GOAL block for the entire timer logic. With them, the graph is readable. Confirms that open question 4 needs a "yes" answer if we want the vocabulary to handle timers.

---

## Scenario E — Cinematic level intro

**Narrative:** On level load, screen is black. Fade in on a wide shot. Pan camera 90° over 3 seconds. Text appears: "DESERT OF PELTA." Fade to player spawn. Gameplay begins.

### Graph structure

```
ACTOR_intro-director
  Entity(etype=intro-director)
    OnSpawn
      // Start with black screen
      SetSetting('bg-a, 'abs, 1.0, 0.0)
      SetSetting('allow-progress, #f, 0.0, 0)
      SetSetting('allow-look-around, #f, 0.0, 0)
      // Lock camera to wide shot
      CameraSwitchToMarker("intro-wide")
      // Kick off the sequence
      SendEvent(self, 'run)            // needed because OnSpawn can't host Sequence

    OnEvent('run')
      Sequence(id="intro")
        steps:
          FadeFromBlack(2.0s)           // 0→1 bg-a
          Wait(1.0s)
          CameraSwitchToMarker("intro-pan")    // pans via cam-spline on marker
          ShowSubtitle("DESERT OF PELTA", 2.5s)
          Wait(3.0s)
          FadeToBlack(0.5s)
          Wait(0.5s)
          CameraClear()
          SetSetting('bg-a, 'abs, 0.0, 1.0)    // fade back in gameplay
          SetSetting('allow-progress, #t, 0.0, 0)
          SetSetting('allow-look-around, #t, 0.0, 0)
          DeactivateSelf
```

### Gaps found

- **`[GAP] Self-trigger pattern`** — to get a Sequence to run on spawn, I have to self-send an event because `OnSpawn` is an init-time trigger and Sequences need a coroutine context. This is a real friction point. Two solutions:
  - (a) Auto-allow Sequences under `OnSpawn` by generating a one-shot self-event. Hidden compiler trick.
  - (b) Add a `SequenceOnSpawn` node that handles the transition cleanly.
  - **My recommendation:** (a). Transparent to the user.  **[T1 compiler fix]**
- **[FRICTION] "intro-pan" camera switch needs cam-spline for the pan to actually move** — without cam-spline support, "intro-pan" would just be a fixed marker. Cam-spline lands in T2; this cutscene is degraded until then.
- **[GAP] Camera-focus control** — during a spline pan the camera should NOT aim at Jak (it should aim at the pan target). That's `flags 0x8000` on the camera entity. **Addon-side, not graph.**

### Insight

Intro cutscenes work reasonably well with the current proposed vocabulary + cam-spline. No major missing nodes beyond what other scenarios already flagged.

---

## Scenario F — Secret chamber revealed by stomp

**Narrative:** Hidden room. The floor above it has a "break-on-stomp" tile. Player ground-pounds the tile → floor shatters → player falls into secret room → chest awaits.

### Graph structure

```
ACTOR_fragile-floor
  Entity(etype=fragile-floor)
    OnEvent('attack')                    // Jak ground-pounds
      // Visual: fragment particles
      SpawnParticleAt("debris", self.position)      [T2 after particle research]
      PlaySound("smash")
      // Reveal hidden room — visual mesh disappears
      SetPermFlag(self, dead, #t)         // the visual actor stays dead
      DeactivateSelf
      // Trigger secondary: unhide the treasure chest below
      SetPermFlag("treasure-chest-0", complete, #t)   // "complete" used as "show"
      SendEvent("treasure-chest-0", 'trigger)         // wake chest
```

### Gaps found

- **[FRICTION] "Make an actor visible that was hidden"** — the pattern is to spawn the actor with `perm-status bit-7` set (hidden), then clear it on reveal. But our `SetPermFlag` interface uses flag *names* — do we support `bit-7` as a name? Needs the flag enum to include all 11 bits plus the named ones. **[T1 — extend flag_name enum]**
- **[NICE] A `RevealActor` shortcut** — wraps "clear perm-status bit-7 + send 'trigger." Sugar, not necessary. **[T2 UX]**
- **[CONFIRMED] OnEvent('attack')** is all we need for stomp detection. No special primitive.

---

## Summary of gaps found across all 6 scenarios

### Genuinely new nodes needed (add to T1 roadmap)

| Node | Reason | Scenarios |
|---|---|---|
| `CheckAllComplete(actor_set)` | Test perm-status across a set | A, B |
| `CountInPermState(actor_set, flag)` | Partial-completion gating | A |
| `OnVolLeft` (or relabel existing) | Clearer than `OnEvent('untrigger')` for VOL volumes | B |
| `GetCurrentTime` → variable | Cross-state timing | D |
| `DeclareVariable` / `SetVariable` / `GetVariable` | Data flow for timers and counters | D |
| `$CURRENT` substitution in `ForEach` | Already in IR; confirm validation is done | D |

### Compiler fixes

| Fix | Why |
|---|---|
| Auto-allow Sequence under OnSpawn via self-trigger | Scenario E — otherwise OnSpawn + Sequence needs manual self-send workaround |
| Flag-name enum must include `bit-0..bit-10` | Scenario F — common "bit-7 = hidden" pattern needs it |
| `$CURRENT` template substitution in emitter | Scenario D — ForEach's most common use |

### Convincing arguments for T2 features

- **Subgraphs** (open question 2): Scenario C's cutscene reusability, Scenario E's near-identical intro/outro patterns. Strong case. Recommend adding.
- **Variables / data flow** (open question 4): Scenario D's timer cannot work without this. Strong case. Recommend adding.
- **battlecontroller + cam-spline + particles + subtitles**: mentioned across multiple scenarios. Confirm the T3→T2 promotion from the research notes doc.

### Open friction points (UX rather than vocab)

- **Camera position picking should be clickable** — don't make users type `"intro-wide"` as a string.
- **ActorSet explicit picker should be shift-select** — don't make users type object names.
- **Wait/duration values need playable preview** — a "play this sequence with mock values" button would cut dev loop massively.

### Dropped from T3

None — scenarios validate all T3 items (battlecontroller, cam-spline, particles) as genuinely needed for real modding.

---

## Revised roadmap weighting

After the 6 scenarios, the most-used nodes (appear in 3+ walkthroughs) are:

1. **ActorSet** (4 scenarios)
2. **Sequence + Wait** (3, already done)
3. **SetPermFlag / ClearPermFlag** (3)
4. **SendEvent with variable target** (4 — ties to ForEach substitution)
5. **CheckAllComplete** (2, but critical to those)
6. **FadeToBlack / FadeFromBlack** (2)
7. **CameraSwitchToMarker** (3)
8. **DeclareVariable / SetVariable / GetVariable** (1 scenario but blocking)

The "T1 critical subset" sharpens to **these 8** for a compelling demo, plus the already-implemented Level A.

---

## One bigger question the walkthroughs surfaced

**Does the graph live on one actor, or can it span multiple actors?**

All 6 scenarios have at least one "director" or "controller" actor whose sole purpose is running logic that operates on *other* actors. Currently each `ACTOR_` empty has its own graph — one graph = one deftype.

This is fine for Scenario A (arena-counter), Scenario B (puzzle-door), etc. but it means you conceptually have a "ghost actor" just to run logic.

Alternative: **scene-level graphs** that aren't tied to any particular actor but run as invisible process-drawable entities on level load. Same deftype-compilation model, just spawned by the addon as an invisible `ACTOR_` automatically.

This is a UX concern more than a compiler one — the graph is the same, just where it lives is different. Worth raising as open question 8 for the brainstorm.
