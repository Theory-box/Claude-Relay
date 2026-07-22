# Feature: stepper-to-inputs
Branch: feature/stepper-to-inputs

## What this does
Replaces all +/- increment/decrement button pairs with direct float/int input fields
across panels.py and utils.py. Users can now click and type values directly.

## Core mechanism
`_prop_row(layout, obj, key, label, default)` in utils.py:
- If key missing on obj: writes default (safe ID prop write), then shows layout.prop
- If key exists: shows layout.prop directly
- Called 46x in panels.py, 5x in utils.py

## Properties converted (51 total)
og_idle_distance, og_cam_interp, og_cam_fov, og_spring_height,
og_launcher_fly_time, og_num_lurkers, og_water_surface/wade/swim/bottom,
og_door_timeout, og_button_timeout, og_flip_delay_down/up, og_flip_sync_pct,
og_orb_count, og_whirl_speed/var, og_orbit_scale/timeout, og_sq_down/up,
og_flame_shove/period/phase/pause, og_shover_force/rot, og_move_speed,
og_elevator_rot, og_breakaway_h1/h2, og_fish_count, og_shark_scale/delay/distance/speed,
og_vis_dist, og_crate_pickup_amount, og_sync_period/phase/ease_out/ease_in, og_notice_dist

## Reset/sentinel buttons kept (nudge operators still used)
- og_spring_height: Reset to Default (-1.0)
- og_launcher_fly_time: Reset to Default (-1.0)
- og_num_lurkers: Reset to Default (-1)
- og_door_timeout: Reset (no timeout) (0.0)
- og_button_timeout: Reset (permanent) (0.0)
- og_notice_dist: Set Always Active (-1.0)

## Spawn defaults added
SpawnPlatform: og_sync_period/phase/ease_out/ease_in/wrap, og_notice_dist
SpawnEntity: og_idle_distance, og_vis_dist, og_num_lurkers, og_orb_count,
             og_fish_count, og_move_speed (per entity type)

## Key debugging history
1. First attempt: layout.prop on missing key crashes panel silently -> solved by _prop_row
2. Second attempt: wrote defaults in draw() -> panels disappeared ->
   actually safe for ID props, real issue was layout.prop exception on missing key
3. Third attempt: operator button fallback -> OG_OT_InitActorProp -> overcomplicated,
   removed. Simple _prop_row (write-then-prop) is the correct approach.
4. Missed utils.py first pass -> platform settings missing -> fixed
5. Wrong entity names in SpawnEntity defaults -> fixed (lurker-spawn, sunkenfish etc)
6. Spring height still showing greyed unclickable label -> converted to _prop_row

## Status
Ready for testing. All 12 files syntax clean. 73 panels / 78 operators unchanged.
