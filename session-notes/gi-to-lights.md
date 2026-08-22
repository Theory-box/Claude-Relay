# GI to Lights (experimental) - session notes

Branch: feature/gi-to-lights   |   File: research/gi-to-lights/gi_to_lights.py
Separate from the Ray Portal Bake addon for now. This is the "recreate bounce GI as a small
set of real lights" research direction (VPL / Instant Radiosity + clustering).

## v0.1.0 - working end-to-end prototype (Route 1: harvest, no optimizer)
Pipeline:
1. HARVEST (harvest_vpls): shoot particle rays from each real light, random-walk them through
   the scene via scene.ray_cast (multi-bounce, cosine-weighted), drop a VPL at every hit
   carrying bounced radiance tinted by that surface's Principled Base Color albedo. Instant
   Radiosity. Handles POINT/SPOT/AREA (launch from light pos) and SUN (launch from a plane
   along the sun dir). No images, no training loop - lights read straight off the trace.
2. CLUSTER (cluster_vpls): radiance-weighted k-means (k-means++ seeding) reduces thousands of
   VPLs to N, summing member flux (energy preserved), averaging normal, normalising colour.
3. EMIT (emit_lights): N soft POINT lights (shadow_soft_size fattens them -> tames the VPL
   1/r^2 singularity) in a "GI_Rig" collection, nudged off their surface along the normal.
Params (Scene props, gi2l_*): rays/light, bounces, lights N, strength, light size, surface
offset, k-means iters, min flux, seed. UI panel in View3D N-panel "GI Lights". Operators:
gitolights.bake, gitolights.clear.

Energy is physically motivated but APPROXIMATE - absolute brightness via Strength multiplier
(tune to a reference). Spatial layout + colour are the correct parts.

## Verified headless (CPU)
- Cornell box: 4000 rays x 2 bounces -> 6368 VPLs. VPLs near the RED wall are red-dominant
  [0.016,0.002,0.002], near GREEN wall green-dominant [0.002,0.016,0.002]. Clustered to 24.
  Floor near left wall receives redder light, near right wall greener -> COLOUR BLEEDING
  reconstructed from the rig. Core concept proven.
- Real scene (Exterior_78_Farmington, 1 Sun, 64 meshes): 513 VPLs -> 32 lights, all finite,
  no crash.

## What can/can't be tested headless
CAN: harvest (BVH ray_cast), clustering, emission, correctness (tint + colour bleeding),
small Cycles reference compare. CANNOT: visual quality judgement, real-scene scale/speed
(no GPU). -> user eyeballs + GPU provide the visual/scale verdict.

## NEXT (not built)
- Energy calibration against a Cycles GI reference (auto-fit the Strength).
- Textured/gobo lights (Rich-VPL 4x4-16x16 exitant map, or HVL SH) instead of point lights ->
  sharper diffuse detail, fewer lights. (point lights = v1 to prove concept.)
- Bake the rig's lighting to a UV texture (the texture-bake use) - reuse Ray Portal Bake's
  output path; rig -> low-variance direct bake (pre-denoised GI).
- Route 3 later: make gobo texels / SH coeffs differentiable, optimise N lights vs PT target.
- Importance/placement heuristic from the Rich-VPL MAIN paper (only supplemental obtained).
