# GOAL Code Examples

> 10 working examples covering core patterns. All confirmed against engine source.
> Place each as a custom type via Spawn → ⚙ Custom Types, attach the code block, add any listed lumps.

---

## Example 1 — Spinning Actor

Rotates an empty around its Y axis continuously. Good for spinning props, indicators, or decorative objects.

**Custom type name:** `spin-prop`
**Lumps:** `spin-rate` — meters — `1.0` (degrees per tick, optional — defaults to 1°/tick)

```lisp
;;-*-Lisp-*-
(in-package goal)

(deftype spin-prop (process-drawable)
  ((angle float))
  (:states spin-prop-idle))

(defstate spin-prop-idle (spin-prop)
  :trans
    (behavior ()
      (+! (-> self angle) (degrees 1.0))
      (quaternion-axis-angle! (-> self root quat) 0.0 1.0 0.0 (-> self angle)))
  :code
    (behavior ()
      (loop (suspend)))
  :post transform-post)

(defmethod init-from-entity! ((this spin-prop) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this angle) 0.0)
  (go spin-prop-idle)
  (none))
```

**Notes:**
- `:trans` runs every frame before `:code` — good for per-frame movement
- `:post transform-post` updates collision/transform after movement — required for anything that moves
- `(degrees 1.0)` = 1 degree per tick = ~60°/second at 60fps
- Change `0.0 1.0 0.0` to rotate around a different axis (X = `1.0 0.0 0.0`, Z = `0.0 0.0 1.0`)

---

## Example 2 — Floating Up and Down

Oscillates an object vertically using a sine wave. Classic floating platform or hovering item effect.

**Custom type name:** `float-bob`
**Lumps:** none

```lisp
;;-*-Lisp-*-
(in-package goal)

(deftype float-bob (process-drawable)
  ((base-y float)
   (timer  float))
  (:states float-bob-idle))

(defstate float-bob-idle (float-bob)
  :trans
    (behavior ()
      (+! (-> self timer) 1.0)
      (let* ((frac  (/ (-> self timer) 180.0))
             (offset (* (meters 0.5) (sin (* 65536.0 frac)))))
        (set! (-> self root trans y) (+ (-> self base-y) offset))))
  :code
    (behavior ()
      (loop (suspend)))
  :post transform-post)

(defmethod init-from-entity! ((this float-bob) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this base-y) (-> this root trans y))
  (set! (-> this timer) 0.0)
  (go float-bob-idle)
  (none))
```

**Notes:**
- `base-y` captures spawn position so the bob is always relative to where you placed it
- `180.0` ticks = one full cycle (about 3 seconds). Lower = faster
- `(meters 0.5)` = 0.5m amplitude. Change for bigger/smaller bob
- Timer wraps naturally via float precision — won't break over long sessions

---

## Example 3 — Move Between Two Points (Ping-Pong)

Smoothly moves an object back and forth between its spawn position and a target offset. Good for sliding doors, moving platforms without path setup, or pendulum objects.

**Custom type name:** `slide-mover`
**Lumps:**
- `move-dist` — meters — `5.0` (how far it travels)
- `move-time` — float — `120.0` (ticks for one-way trip, 120 = ~2 seconds)

```lisp
;;-*-Lisp-*-
(in-package goal)

(deftype slide-mover (process-drawable)
  ((start-pos vector :inline)
   (end-pos   vector :inline)
   (progress  float)
   (direction float))
  (:states slide-mover-idle))

(defstate slide-mover-idle (slide-mover)
  :trans
    (behavior ()
      (+! (-> self progress) (* (-> self direction) (/ 1.0 120.0)))
      (cond
        ((>= (-> self progress) 1.0)
         (set! (-> self progress) 1.0)
         (set! (-> self direction) -1.0))
        ((<= (-> self progress) 0.0)
         (set! (-> self progress) 0.0)
         (set! (-> self direction) 1.0)))
      (vector-lerp! (-> self root trans)
                    (-> self start-pos)
                    (-> self end-pos)
                    (-> self progress)))
  :code
    (behavior ()
      (loop (suspend)))
  :post transform-post)

(defmethod init-from-entity! ((this slide-mover) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> (-> this start-pos) quad) (-> this root trans quad))
  (set! (-> (-> this end-pos) quad)   (-> this root trans quad))
  (+! (-> (-> this end-pos) y) (res-lump-float arg0 'move-dist :default (meters 5.0)))
  (set! (-> this progress)  0.0)
  (set! (-> this direction) 1.0)
  (go slide-mover-idle)
  (none))
```

**Notes:**
- Change `y` to `x` or `z` to slide in a different direction
- `vector-lerp!` smoothly interpolates between start and end — no need for manual math
- `progress` goes 0.0 → 1.0 → 0.0, bouncing at each end
- For eased movement replace the linear `+= direction/time` with `(seek! ...)` 

---

## Example 4 — Proximity Trigger (One-Shot)

Fires once when Jak gets within range, then deactivates permanently. Good for cutscene triggers, one-time events, or zone-based logic.

**Custom type name:** `prox-trigger`
**Lumps:**
- `radius` — meters — `8.0`

```lisp
;;-*-Lisp-*-
(in-package goal)

(deftype prox-trigger (process-drawable)
  ((radius float))
  (:states prox-trigger-wait prox-trigger-done))

(defstate prox-trigger-wait (prox-trigger)
  :trans
    (behavior ()
      (when (and *target*
                 (< (vector-vector-distance
                      (-> self root trans)
                      (-> *target* control trans))
                    (-> self radius)))
        (go prox-trigger-done)))
  :code
    (behavior ()
      (loop (suspend))))

(defstate prox-trigger-done (prox-trigger)
  :enter
    (behavior ()
      (format 0 "[prox-trigger] fired!~%")
      ;; ── PUT YOUR ACTION HERE ──────────────────────────────
      ;; e.g. send an event, play a sound, switch camera:
      ;; (send-event *camera* 'change-to-entity-by-name "cam-marker-0")
      ;; (sound-play "secret-found" :position #f)
      ;; ──────────────────────────────────────────────────────
      (process-entity-status! self (entity-perm-status complete) #t))
  :code
    (behavior ()
      (loop (suspend))))

(defmethod init-from-entity! ((this prox-trigger) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this radius)
        (res-lump-float arg0 'radius :default (meters 8.0)))
  (if (logtest? (-> this entity extra perm status) (entity-perm-status complete))
    (go prox-trigger-done)
    (go prox-trigger-wait))
  (none))
```

**Notes:**
- `perm-status complete` check in `init-from-entity!` means if it already fired this session, it skips straight to done — won't re-fire on level reload
- Add your action in the `:enter` of `prox-trigger-done`
- `:trans` on the wait state checks every frame — throttle with `(zero? (mod (-> *display* base-frame-counter) 4))` if performance matters

---

## Example 5 — Timed Delay Relay

Waits N seconds after receiving `'trigger`, then forwards `'trigger` to another entity. Useful for chaining events with a delay.

**Custom type name:** `delay-relay`
**Lumps:**
- `target-name` — string — `target-entity-name`
- `delay` — float — `180.0` (ticks — 180 = 3 seconds)

```lisp
;;-*-Lisp-*-
(in-package goal)

(deftype delay-relay (process-drawable)
  ((target-name string)
   (delay       float))
  (:states delay-relay-idle delay-relay-counting))

(defstate delay-relay-idle (delay-relay)
  :event
    (behavior ((proc process) (argc int) (message symbol) (block event-message-block))
      (case message
        (('trigger) (go delay-relay-counting))))
  :code
    (behavior ()
      (loop (suspend))))

(defstate delay-relay-counting (delay-relay)
  :code
    (behavior ()
      (let ((t0 (current-time)))
        (until (time-elapsed? t0 (the int (-> self delay)))
          (suspend)))
      (let ((tgt (process-by-ename (-> self target-name))))
        (when tgt (send-event tgt 'trigger)))
      (go delay-relay-idle)))

(defmethod init-from-entity! ((this delay-relay) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this target-name) (res-lump-struct arg0 'target-name string))
  (set! (-> this delay) (res-lump-float arg0 'delay :default 180.0))
  (go delay-relay-idle)
  (none))
```

**Notes:**
- `(current-time)` returns the current frame counter tick
- `(time-elapsed? t0 N)` returns true when N ticks have passed since t0
- After firing it returns to idle — can be re-triggered
- Chain multiple delay-relays to sequence events over time

---

## Example 6 — Toggle Door (Open / Close on Trigger)

Slides open on first `'trigger`, slides closed on second `'trigger`. Works with VOL_ trigger volumes or any other trigger source.

**Custom type name:** `toggle-door`
**Lumps:**
- `open-height` — meters — `4.0` (how far it rises when open)

```lisp
;;-*-Lisp-*-
(in-package goal)

(deftype toggle-door (process-drawable)
  ((closed-y float)
   (open-y   float)
   (lerp-t   float))
  (:states toggle-door-closed
           toggle-door-opening
           toggle-door-open
           toggle-door-closing))

(defstate toggle-door-closed (toggle-door)
  :event
    (behavior ((proc process) (argc int) (message symbol) (block event-message-block))
      (case message
        (('trigger) (go toggle-door-opening))))
  :code (behavior () (loop (suspend)))
  :post transform-post)

(defstate toggle-door-opening (toggle-door)
  :code
    (behavior ()
      (until (>= (-> self lerp-t) 1.0)
        (set! (-> self lerp-t) (fmin 1.0 (+ (-> self lerp-t) (* 1.5 (seconds-per-frame)))))
        (set! (-> self root trans y)
              (lerp (-> self closed-y) (-> self open-y) (-> self lerp-t)))
        (suspend))
      (go toggle-door-open))
  :post transform-post)

(defstate toggle-door-open (toggle-door)
  :event
    (behavior ((proc process) (argc int) (message symbol) (block event-message-block))
      (case message
        (('trigger) (go toggle-door-closing))))
  :code (behavior () (loop (suspend)))
  :post transform-post)

(defstate toggle-door-closing (toggle-door)
  :code
    (behavior ()
      (until (<= (-> self lerp-t) 0.0)
        (set! (-> self lerp-t) (fmax 0.0 (- (-> self lerp-t) (* 1.5 (seconds-per-frame)))))
        (set! (-> self root trans y)
              (lerp (-> self closed-y) (-> self open-y) (-> self lerp-t)))
        (suspend))
      (go toggle-door-closed))
  :post transform-post)

(defmethod init-from-entity! ((this toggle-door) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this closed-y) (-> this root trans y))
  (set! (-> this open-y)
        (+ (-> this closed-y)
           (res-lump-float arg0 'open-height :default (meters 4.0))))
  (set! (-> this lerp-t) 0.0)
  (go toggle-door-closed)
  (none))
```

**Notes:**
- `(seconds-per-frame)` = 1/framerate — multiplied by a speed constant gives frame-rate-independent movement
- `1.5` = speed multiplier; lower = slower door, higher = faster
- Works with X or Z movement too — change the `y` field and `closed-y`/`open-y` to match
- Combine with a VOL_ trigger: the volume sends `'trigger` on enter and `'untrigger` on exit — toggle-door ignores `'untrigger` here but you can handle it too

---

## Example 7 — Follow Waypoint Path

Moves along a set of waypoints placed in Blender and loops. No art needed — just the empty moving through space. Good for testing path logic before attaching it to a real platform.

**Custom type name:** `path-follower`
**Lumps:** none (reads `path` lump automatically from waypoints)
**Blender setup:** Add waypoints to `ACTOR_path-follower_0` via the Waypoints panel

```lisp
;;-*-Lisp-*-
(in-package goal)

(deftype path-follower (process-drawable)
  ((path-pos float)
   (speed    float))
  (:states path-follower-idle))

(defstate path-follower-idle (path-follower)
  :trans
    (behavior ()
      (+! (-> self path-pos) (-> self speed))
      (when (>= (-> self path-pos) 1.0)
        (set! (-> self path-pos) 0.0))
      (let ((pt (new 'stack-no-clear 'vector)))
        (eval-path-curve! (-> self path) pt (-> self path-pos) 'interp)
        (move-to-point! (-> self root) pt)))
  :code
    (behavior ()
      (loop (suspend)))
  :post transform-post)

(defmethod init-from-entity! ((this path-follower) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this path) (new 'process 'curve-control this 'path -1000000000.0))
  (set! (-> this path-pos) 0.0)
  (set! (-> this speed) 0.002)
  (go path-follower-idle)
  (none))
```

**Notes:**
- `speed` of `0.002` = moves 0.2% of the path per tick ≈ one full loop in ~8 seconds
- `(eval-path-curve! path out-vec pos 'interp)` evaluates the path at 0.0–1.0
- `(move-to-point! root vec)` sets position from a vector
- Waypoints must be linked to this actor in the Waypoints panel before export
- The `path` field is built-in on `process-drawable` — no need to declare it

---

## Example 8 — Counter Relay (Fire After N Triggers)

Counts incoming `'trigger` events and only fires its target after receiving N of them. Good for puzzles requiring multiple switches or zones.

**Custom type name:** `counter-relay`
**Lumps:**
- `target-name` — string — `target-entity-name`
- `count` — float — `3.0` (number of triggers required)

```lisp
;;-*-Lisp-*-
(in-package goal)

(deftype counter-relay (process-drawable)
  ((target-name  string)
   (required     int32)
   (current      int32))
  (:states counter-relay-waiting counter-relay-done))

(defstate counter-relay-waiting (counter-relay)
  :event
    (behavior ((proc process) (argc int) (message symbol) (block event-message-block))
      (case message
        (('trigger)
         (+! (-> self current) 1)
         (format 0 "[counter-relay] ~D / ~D~%" (-> self current) (-> self required))
         (when (>= (-> self current) (-> self required))
           (go counter-relay-done)))))
  :code
    (behavior ()
      (loop (suspend))))

(defstate counter-relay-done (counter-relay)
  :enter
    (behavior ()
      (format 0 "[counter-relay] threshold reached — firing ~A~%" (-> self target-name))
      (let ((tgt (process-by-ename (-> self target-name))))
        (when tgt (send-event tgt 'trigger)))
      (process-entity-status! self (entity-perm-status complete) #t))
  :code
    (behavior ()
      (loop (suspend))))

(defmethod init-from-entity! ((this counter-relay) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this target-name) (res-lump-struct arg0 'target-name string))
  (set! (-> this required) (the int (res-lump-float arg0 'count :default 3.0)))
  (set! (-> this current) 0)
  (if (logtest? (-> this entity extra perm status) (entity-perm-status complete))
    (go counter-relay-done)
    (go counter-relay-waiting))
  (none))
```

**Notes:**
- Link multiple VOL_ volumes to this entity — each sends `'trigger` when entered
- `(the int ...)` casts the float lump to int32
- `format 0` prints to the debug console — useful for testing
- Once done, the `complete` flag prevents re-firing on session reload

---

## Example 9 — Camera Switch on Proximity

Switches to a named camera marker when Jak gets close, reverts when he leaves. Good for cinematic moments or guiding attention.

**Custom type name:** `cam-zone`
**Lumps:**
- `cam-name` — string — `cam-marker-0`
- `radius` — meters — `15.0`

```lisp
;;-*-Lisp-*-
(in-package goal)

(deftype cam-zone (process-drawable)
  ((cam-name string)
   (radius   float)
   (active   symbol))
  (:states cam-zone-idle))

(defstate cam-zone-idle (cam-zone)
  :trans
    (behavior ()
      (when (and *target* (zero? (mod (-> *display* base-frame-counter) 4)))
        (let* ((dist (vector-vector-distance
                       (-> self root trans)
                       (-> *target* control trans)))
               (near (< dist (-> self radius))))
          (cond
            ((and near (not (-> self active)))
             (set! (-> self active) #t)
             (send-event *camera* 'change-to-entity-by-name (-> self cam-name)))
            ((and (not near) (-> self active))
             (set! (-> self active) #f)
             (send-event *camera* 'clear-entity))))))
  :code
    (behavior ()
      (loop (suspend))))

(defmethod init-from-entity! ((this cam-zone) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this cam-name) (res-lump-struct arg0 'cam-name string))
  (set! (-> this radius) (res-lump-float arg0 'radius :default (meters 15.0)))
  (set! (-> this active) #f)
  (go cam-zone-idle)
  (none))
```

**Notes:**
- Requires a `CAMERA_` marker placed in Blender — name it `cam-marker-0` (or whatever you put in the lump)
- Frame throttle `(mod frame-counter 4)` keeps it cheap — camera switches are not time-critical
- `'clear-entity` reverts to the default follow camera
- You can add `(send-event *camera* 'teleport)` after the switch for a hard cut instead of blend

---

## Example 10 — Scripted Sequence (Fade, Hold, Fade Back)

A full scripted moment: when Jak enters the zone, fade to black, hold for a few seconds, revert. Locks controls during the sequence.

**Custom type name:** `fade-sequence`
**Lumps:**
- `radius` — meters — `5.0`
- `hold-time` — float — `300.0` (ticks to hold black, 300 = 5 seconds)

```lisp
;;-*-Lisp-*-
(in-package goal)

(deftype fade-sequence (process-drawable)
  ((radius    float)
   (hold-time float))
  (:states fade-sequence-wait
           fade-sequence-run
           fade-sequence-done))

(defstate fade-sequence-wait (fade-sequence)
  :trans
    (behavior ()
      (when (and *target*
                 (< (vector-vector-distance
                      (-> self root trans)
                      (-> *target* control trans))
                    (-> self radius)))
        (go fade-sequence-run)))
  :code (behavior () (loop (suspend))))

(defstate fade-sequence-run (fade-sequence)
  :enter
    (behavior ()
      (set-setting! 'allow-progress #f 0.0 0)
      (set-setting! 'allow-look-around #f 0.0 0))
  :exit
    (behavior ()
      (remove-setting! 'allow-progress)
      (remove-setting! 'allow-look-around)
      (remove-setting! 'bg-a))
  :code
    (behavior ()
      ;; Fade to black over 0.5 seconds
      (let ((t0 (current-time)))
        (until (time-elapsed? t0 (seconds 0.5))
          (set-setting! 'bg-a 'abs
                        (lerp-scale 0.0 1.0
                                    (the float (- (current-time) t0))
                                    0.0 150.0)
                        0)
          (suspend)))
      (set-setting! 'bg-a 'abs 1.0 0)
      ;; ── PUT YOUR MIDPOINT ACTION HERE ──────────────────
      ;; (sound-play "secret-found" :position #f)
      ;; (send-event *camera* 'change-to-entity-by-name "my-cam")
      ;; ───────────────────────────────────────────────────
      ;; Hold black
      (let ((t1 (current-time)))
        (until (time-elapsed? t1 (the int (-> self hold-time)))
          (suspend)))
      ;; Fade back in over 0.5 seconds
      (let ((t2 (current-time)))
        (until (time-elapsed? t2 (seconds 0.5))
          (set-setting! 'bg-a 'abs
                        (lerp-scale 1.0 0.0
                                    (the float (- (current-time) t2))
                                    0.0 150.0)
                        0)
          (suspend)))
      (go fade-sequence-done)))

(defstate fade-sequence-done (fade-sequence)
  :code
    (behavior ()
      (process-entity-status! self (entity-perm-status complete) #t)
      (loop (suspend))))

(defmethod init-from-entity! ((this fade-sequence) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (set! (-> this radius)
        (res-lump-float arg0 'radius :default (meters 5.0)))
  (set! (-> this hold-time)
        (res-lump-float arg0 'hold-time :default 300.0))
  (if (logtest? (-> this entity extra perm status) (entity-perm-status complete))
    (go fade-sequence-done)
    (go fade-sequence-wait))
  (none))
```

**Notes:**
- `set-setting! 'bg-a 'abs 1.0 0` = fully opaque black overlay
- `lerp-scale` maps input range (0 to 150 ticks) to output range (0.0 to 1.0) — smooth fade
- `:exit` on `fade-sequence-run` cleans up settings even if the state is interrupted
- Add camera switch, sound, or whatever else in the midpoint action block
- `perm-status complete` prevents re-firing — remove that line if you want it repeatable

---

## Quick Reference — Patterns Used Across Examples

| Pattern | Syntax |
|---|---|
| Rotate around Y | `(quaternion-axis-angle! (-> self root quat) 0.0 1.0 0.0 angle)` |
| Move to position | `(set! (-> self root trans y) new-y)` |
| Move to vector | `(move-to-point! (-> self root) vec)` |
| Lerp float | `(lerp a b t)` — t is 0.0–1.0 |
| Lerp vector | `(vector-lerp! dest start end t)` |
| Distance to Jak | `(vector-vector-distance (-> self root trans) (-> *target* control trans))` |
| Frame throttle | `(zero? (mod (-> *display* base-frame-counter) 4))` |
| Timer start | `(let ((t0 (current-time))) ...)` |
| Timer check | `(time-elapsed? t0 (seconds 2.0))` |
| Send event | `(send-event proc 'trigger)` |
| Fade to black | `(set-setting! 'bg-a 'abs 1.0 0)` |
| Revert camera | `(send-event *camera* 'clear-entity)` |
| Lock pause menu | `(set-setting! 'allow-progress #f 0.0 0)` |
| Play sound | `(sound-play "sound-name" :position #f)` |
| Mark complete | `(process-entity-status! self (entity-perm-status complete) #t)` |
| Kill a process | `(deactivate proc)` |
| Per-frame | `:trans (behavior () ...)` — runs before :code |
| Update collision | `:post transform-post` — required if position changes |

---

## Example 11 — Level Exit Trigger

Transitions to another level when Jak walks into a VOL_ zone. Uses the same `set-continue!` + `load-commands-set!` pattern as `launcherdoor` (confirmed engine source).

**Custom type name:** `level-exit`
**Lumps:**
- `continue-name` — string — the continue-point name in the destination level (e.g. `my-level-2-start`)

**Setup:**
1. Make sure the destination level has a continue/spawn point — note its name
2. Spawn `ACTOR_level-exit_0`, add the `continue-name` lump
3. Place a `VOL_` mesh over the exit zone
4. Link the VOL_ to `ACTOR_level-exit_0` via Volume Links

```lisp
;;-*-Lisp-*-
(in-package goal)

(deftype level-exit (process-drawable)
  ()
  (:states level-exit-idle))

(defstate level-exit-idle (level-exit)
  :event
    (behavior ((proc process) (argc int) (message symbol) (block event-message-block))
      (case message
        (('trigger)
         (let ((cp-name (res-lump-struct (-> self entity) 'continue-name structure)))
           (when cp-name
             (let ((cp (set-continue! *game-info* (the-as basic cp-name))))
               (load-commands-set! *level* (-> cp load-commands))))))))
  :code
    (behavior ()
      (loop (suspend))))

(defmethod init-from-entity! ((this level-exit) (arg0 entity-actor))
  (set! (-> this root) (new 'process 'trsqv))
  (process-drawable-from-entity! this arg0)
  (go level-exit-idle)
  (none))
```

**How it works:**
- `set-continue!` registers the destination continue-point and returns the `continue-point` struct
- `load-commands-set!` applies that continue's load commands — this is what actually triggers the level load and transition
- This is the exact same call sequence as `launcherdoor.gc` line 80 — the engine's own cave entrance actor

**Finding the continue-name:**
The continue-point name is set in the destination level's Blender file via the **Level Flow** panel (spawn points section). It's the string you give the spawn/continue point there. For a vanilla level like village1 you'd use `"village1-hut"`.

**Notes:**
- No fade or animation — transition happens immediately on zone entry. Wrap in a `fade-sequence` (Example 10) if you want a fade first
- The destination level must be compiled and in the game's build for the transition to work
- If `continue-name` lump is missing or the name doesn't match any known continue-point, nothing happens — no crash

