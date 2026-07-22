# Camera Rotation — nREPL Diagnostic Commands

Run these IN ORDER after triggering your custom camera in-game.
Each command tells us something specific. Copy results here.

---

## STEP 1 — Confirm the camera switch happened

```lisp
(-> *camera-combiner* tracking-status)
```
Expected: nonzero if a camera slave is active.

```lisp
(-> *camera* num-slaves)
```
Expected: 1 or 2 (2 during blend).

---

## STEP 2 — Read the raw entity quat after level load

```lisp
;; Read what's actually stored in our camera entity
(let ((e (entity-by-name "CAMERA_0")))
  (format #t "entity quat: ~f ~f ~f ~f~%"
    (-> e quat x) (-> e quat y) (-> e quat z) (-> e quat w)))
```
**Expected:** Should match exactly what we put in the JSONC file.
If this is wrong, the problem is in export, not in the math.

---

## STEP 3 — Read the actual inv-camera-rot BEFORE triggering

```lisp
;; While the default follow-cam is active (BEFORE entering trigger volume)
(format #t "DEFAULT cam inv-rot row0: ~f ~f ~f~%"
  (-> *camera-combiner* inv-camera-rot vector 0 x)
  (-> *camera-combiner* inv-camera-rot vector 0 y)
  (-> *camera-combiner* inv-camera-rot vector 0 z))
(format #t "DEFAULT cam inv-rot row1: ~f ~f ~f~%"
  (-> *camera-combiner* inv-camera-rot vector 1 x)
  (-> *camera-combiner* inv-camera-rot vector 1 y)
  (-> *camera-combiner* inv-camera-rot vector 1 z))
(format #t "DEFAULT cam inv-rot row2: ~f ~f ~f~%"
  (-> *camera-combiner* inv-camera-rot vector 2 x)
  (-> *camera-combiner* inv-camera-rot vector 2 y)
  (-> *camera-combiner* inv-camera-rot vector 2 z))
```
**This tells us the base orientation so we can compare.**

---

## STEP 4 — ENTER the trigger volume, then immediately run:

```lisp
;; After custom camera is active
(format #t "CUSTOM cam inv-rot row0: ~f ~f ~f~%"
  (-> *camera-combiner* inv-camera-rot vector 0 x)
  (-> *camera-combiner* inv-camera-rot vector 0 y)
  (-> *camera-combiner* inv-camera-rot vector 0 z))
(format #t "CUSTOM cam inv-rot row1: ~f ~f ~f~%"
  (-> *camera-combiner* inv-camera-rot vector 1 x)
  (-> *camera-combiner* inv-camera-rot vector 1 y)
  (-> *camera-combiner* inv-camera-rot vector 1 z))
(format #t "CUSTOM cam inv-rot row2: ~f ~f ~f~%"
  (-> *camera-combiner* inv-camera-rot vector 2 x)
  (-> *camera-combiner* inv-camera-rot vector 2 y)
  (-> *camera-combiner* inv-camera-rot vector 2 z))
```
**This is the GROUND TRUTH.** From these 3 rows we can figure out EXACTLY what quat to send.

---

## STEP 5 — Read the slave tracking matrix directly

```lisp
;; Read from the camera slave (more direct than combiner)
(when (> (-> *camera* num-slaves) 0)
  (let ((s (ppointer->process (-> *camera* slave 0))))
    (format #t "slave tracking row0: ~f ~f ~f~%"
      (-> (the-as camera-slave s) tracking inv-mat vector 0 x)
      (-> (the-as camera-slave s) tracking inv-mat vector 0 y)
      (-> (the-as camera-slave s) tracking inv-mat vector 0 z))
    (format #t "slave tracking row1: ~f ~f ~f~%"
      (-> (the-as camera-slave s) tracking inv-mat vector 1 x)
      (-> (the-as camera-slave s) tracking inv-mat vector 1 y)
      (-> (the-as camera-slave s) tracking inv-mat vector 1 z))
    (format #t "slave tracking row2: ~f ~f ~f~%"
      (-> (the-as camera-slave s) tracking inv-mat vector 2 x)
      (-> (the-as camera-slave s) tracking inv-mat vector 2 y)
      (-> (the-as camera-slave s) tracking inv-mat vector 2 z))))
```

---

## STEP 6 — Known reference: set a quat manually and read back

```lisp
;; MANUALLY force a known quat via nREPL and read what matrix it produces
;; This bypasses entity export entirely — pure engine test
(let ((e (entity-by-name "CAMERA_0")))
  ;; Set identity quat
  (set! (-> e quat x) 0.0)
  (set! (-> e quat y) 0.0)
  (set! (-> e quat z) 0.0)
  (set! (-> e quat w) 1.0))
;; Then trigger the camera again (walk out and back in)
;; Then read STEP 4 again
;; Identity quat should produce an unrotated matrix (all 1s on diagonal)
```

```lisp
;; Try a known 90-degree rotation and see what it produces
(let ((e (entity-by-name "CAMERA_0")))
  (set! (-> e quat x) 0.7071)
  (set! (-> e quat y) 0.0)
  (set! (-> e quat z) 0.0)
  (set! (-> e quat w) 0.7071))
;; Walk out and back in, then read matrix
```

---

## STEP 7 — Check a VANILLA game camera (the holy grail reference)

Find a vanilla level with a fixed camera cutscene. Read its entity.
Example levels with fixed cameras: title screen, cutscenes, boss arenas.

```lisp
;; Try to find any camera entity in the current level
(let ((actors (-> *level* level 0 bsp actors)))
  (dotimes (i (-> actors length))
    (let ((a (-> actors data i actor)))
      (when (string= (-> a etype symbol name) "entity-camera")
        (format #t "Found entity-camera: ~A at ~f ~f ~f quat ~f ~f ~f ~f~%"
          (res-lump-struct a 'name string)
          (-> a trans x) (-> a trans y) (-> a trans z)
          (-> a quat x) (-> a quat y) (-> a quat z) (-> a quat w))))))
```

---

## STEP 8 — The "interesting" lump bypass (no quaternion needed)

If all else fails, use `interesting` to point the camera at a world position.
This COMPLETELY bypasses the quaternion — the camera looks at the target point.

```jsonc
{
  "trans": [gx, gy, gz],
  "etype": "camera-marker",
  "quat": [0, 0, 0, 1],
  "lump": {
    "name": "CAMERA_0",
    "interpTime": ["float", 1.0],
    "interesting": ["vector3m", [target_gx, target_gy, target_gz]]
  }
}
```
**This is the escape hatch.** Place camera where you want it, put `interesting` at the thing
you want it to look at. Zero maths needed. Exposes it in the Blender UI as a "look at" target.

---

## What To Do With Step 4 Results

Once you have the 3 rows of `inv-camera-rot` after triggering the custom camera:

- **row2** = the direction the game camera is ACTUALLY pointing
- **row1** = the game camera's UP vector
- **row0** = the game camera's RIGHT vector

From this we can work out EXACTLY what quaternion the game wants for any given direction.
This is the only reliable way forward.

