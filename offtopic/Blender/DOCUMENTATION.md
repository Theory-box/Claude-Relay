# Photon Splat Prepass — User Documentation
**Version:** 0.1 (pre-release)  
**Blender:** 4.4+  
**Engine:** Cycles only

---

## What It Does

Cycles is a path tracer. When rendering dark interiors lit through small openings — a
basement lit through a doorway, a corridor lit by a distant window — it has to trace
rays randomly until they stumble onto a path back to the light. This is unlikely, so it
takes many samples to converge. The result is noise.

This addon bakes a low-resolution **irradiance cache** of your interior at probe
positions scattered throughout the space. It injects that cache back into the scene as
an invisible emissive volume. Bounce rays from your surfaces then hit the glowing volume
nearby instead of having to trace all the way back to the original light source. Fewer
samples needed. Less noise.

**It is invisible to the camera.** You will never see it as fog or haze.
**It is static.** Bake once per lighting setup. Rebake if lights move.

---

## Quick Start

1. Open your scene in Blender 4.4 with Cycles selected.
2. Press **N** in the 3D viewport to open the N-panel.
3. Find the **Photon Splat** tab.
4. Click **Bake Irradiance Cache**.
5. Wait for the bake to complete (Blender will be unresponsive during this time).
6. Render normally. Dark areas should be less noisy at the same sample count.

---

## The Panel

```
┌──────────────────────────────────┐
│  PHOTON SPLAT                    │
├──────────────────────────────────┤
│  Status: ● Ready                 │
│                                  │
│  [  Bake Irradiance Cache  ]     │
│  [  Clear Cache            ]     │
│                                  │
│  ▾ Probe Grid                    │
│    Resolution  X [8] Y [8] Z [4] │
│    Zone Object [  None       ▾]  │
│                                  │
│  ▾ Capture                       │
│    Samples     [8 ]              │
│    Bounces     [4 ]              │
│                                  │
│  ▾ Volume                        │
│    Strength    [1.00]            │
│    Blur Radius [1.50]            │
└──────────────────────────────────┘
```

### Bake Irradiance Cache
Runs the full pipeline: generates probe positions, renders a tiny panoramic capture
at each one, builds a VDB volume from the results, and injects it into the scene.
Blender will appear frozen during this operation. The status line updates between
probes so you can see progress.

### Clear Cache
Removes the irradiance cache volume from the scene and deletes the VDB file.
Does not affect anything else.

---

## Settings

### Probe Grid — Resolution X / Y / Z

How many probe points to scatter through the interior in each axis.
Total probes = X × Y × Z. Each probe is one tiny render.

| Scene size | Recommended |
|---|---|
| Single small room | 4 × 4 × 2 |
| Single large room | 8 × 8 × 4 (default) |
| Multi-room interior | 12 × 12 × 6 |
| Large building interior | 16 × 16 × 8 |

Higher resolution = more accurate cache, longer bake time.
For most architectural stills, the default 8×8×4 is sufficient.

### Probe Grid — Zone Object

By default the addon places probes throughout the full bounding box of all visible
mesh objects, with an interior test to discard probes that land outside geometry.

If your scene has complex or non-manifold mesh topology (openings, non-closed surfaces),
the interior test may misplace probes. In this case, place an **Empty** or **Cube** mesh
object manually inside your interior to define the probe zone, and assign it here.
Probes will be placed within that object's bounding box with no interior test.

**This is the recommended workflow for interiors with doors or windows.**

### Capture — Samples

How many Cycles samples to use for each probe render.
Probes are rendered at 32×16 pixels. Very few samples are needed.

| Value | Effect |
|---|---|
| 4 | Very fast, coarser irradiance |
| 8 (default) | Good balance |
| 16 | Slightly better quality, ~2× bake time |
| 32 | Diminishing returns |

### Capture — Bounces

How many light bounces each probe render uses. This determines how "deep" the
baked lighting information goes.

**Match this to your final render's max bounces.** If you render at 4 diffuse bounces,
set capture bounces to 4. If you set it lower, the cache will underestimate dark areas.
If higher, it may slightly overestimate (harmless).

### Volume — Strength

Multiplier on the emission strength of the injected volume.

- **Too low:** Dark areas still noisy. Volume is not contributing enough.
- **Too high:** Dark areas appear unnaturally bright. Scene loses contrast.
- **1.0 (default):** Physically derived from your scene's lighting.

Adjust this after baking if the result looks wrong. Start at 1.0 and tune from there.

### Volume — Blur Radius

How much the irradiance data is smoothed between probe positions (in voxels).

- **Low (0.5–1.0):** Sharper boundaries between bright/dark areas. May look blocky
  with low probe resolution.
- **Medium (1.5, default):** Smooth transitions. Good for most scenes.
- **High (3.0+):** Very soft, uniform fill. Use if probes are very sparse.

---

## When to Rebake

Rebake whenever the lighting setup changes:

- Sun position changed
- A light was moved, added, or removed
- HDRI changed
- A door/window was opened or closed in the model
- Objects that block light were moved

You do **not** need to rebake for:
- Camera moves
- Material changes (other than emissive materials that contribute significant light)
- Object visibility for non-light-contributing objects

---

## Limitations

**Static only.** The cache is baked for one moment in time. Animated lights or moving
doors require rebaking per lighting state.

**Diffuse indirect only.** The cache captures average incoming light color. It does not
capture directional effects or specular/glossy indirect light. Highly reflective
interiors (polished concrete, glass, mirrors) will see less benefit.

**Coarse resolution.** The probe grid is intentionally low resolution — the goal is
broad fill, not fine detail. Sharp transitions in indirect light (e.g. a spotlight
casting a defined beam across a floor) will be captured approximately.

**Blender 4.4+ Cycles only.** Not compatible with EEVEE. Not compatible with
third-party render engines (Octane, Redshift, etc.). GPU and CPU rendering both
supported for the final render; the bake always uses CPU Cycles internally.

**Non-manifold mesh caveat.** If you don't use a Zone Object, the addon performs an
interior/exterior test on your geometry. This requires closed, manifold mesh topology.
Scenes with open edges or intentional holes in the mesh may produce misplaced probes.
Use the Zone Object setting to avoid this.

---

## How It Works (Technical Summary)

1. **Probe grid generation:** Candidate positions are scattered on a 3D grid across
   the interior volume, tested against the scene geometry, and those outside are
   discarded.

2. **Irradiance capture:** A panoramic (equirectangular) camera is placed at each
   probe position in turn. A 32×16 pixel Cycles render captures the incoming light
   from all directions. The average RGB value of all pixels becomes the irradiance
   estimate at that point.

3. **VDB construction:** Probe irradiance values are written into an OpenVDB
   `Vec3SGrid` (RGB float volume). The grid is Gaussian-blurred to smooth between
   sparse probe positions, filling the gaps with interpolated values. The grid's
   world transform is set to match the scene bounding box exactly.

4. **Volume injection:** The VDB is loaded as a Blender Volume object with an
   emission-only shader (no scatter, no absorption). The object's ray visibility is
   set so it is invisible to camera rays and shadow rays, but visible to diffuse and
   glossy bounce rays. It is physically transparent from the camera's perspective
   but glows when a bounce ray hits it.

5. **Final render:** Your normal render runs unchanged. Camera rays shoot straight
   through the volume without seeing it. Bounce rays from surfaces in dark areas hit
   the volume and sample its emission, receiving the approximate color and intensity
   that was baked there. These rays terminate early instead of continuing to randomly
   search for the original light source.

---

## Troubleshooting

**The bake runs but dark areas are still very noisy.**
- Increase Strength.
- Increase probe Resolution.
- Check that the volume object exists in the scene (it should be named `IrradianceCache`).
- Confirm you're rendering with Cycles, not EEVEE.

**The bake produces a volume that makes everything too bright.**
- Decrease Strength.
- Check that Capture Bounces is not much higher than your render's max bounces.

**The bake takes a very long time.**
- Decrease probe Resolution.
- Decrease Capture Samples (8 is usually sufficient).
- Ensure your scene doesn't have extremely heavy geometry that slows BVH build on first probe.

**Probes are being placed outside the room / in walls.**
- Use the Zone Object setting. Place a box mesh manually around your interior and assign it.

**The volume appears as visible fog in the render.**
- This should not happen. If it does, check that the IrradianceCache material exists
  and is correctly set up (emission only, camera visibility off).
- Try clearing the cache and rebaking.

**Error: "No interior probe positions found".**
- Your Zone Object or scene mesh may not be closed. Use a simple box as Zone Object.
- Or the probe resolution is too low to place any probes inside a small space.
  Try increasing resolution or making the Zone Object tighter.
