# Junglesnake — Developer Documentation

## Status
✅ Confirmed working (tested April 2026, opengoal_tools_v9)

---

## Overview
Junglesnake is a stationary ambush enemy. It hangs from a fixed position, tracks Jak with head/body rotation, and strikes when he gets close. One of the safest enemies to use in custom levels — no navmesh, no linked actors, fully self-contained.

---

## Type Hierarchy
```
process-drawable
  └── junglesnake
```
Does NOT extend nav-enemy. Implements its own AI entirely via joint rotation math.

---

## States

| State | Trigger |
|---|---|
| `junglesnake-sleeping` | Default on spawn |
| `junglesnake-wake` | Player enters detection range |
| `junglesnake-tracking` | Actively tracking player position |
| `junglesnake-attack` | Player within strike range |
| `junglesnake-give-up` | Player escapes range |
| `junglesnake-die` | Killed |

Player detection uses `track-player-ry` and `track-player-tilt` — pure joint rotation math, no nav system involved.

---

## Animations

| Index | Name |
|---|---|
| 2 | `junglesnake-idle-ja` |
| 3 | `junglesnake-strike-close-ja` |
| 4 | `junglesnake-strike-far-ja` |
| 5 | `junglesnake-drop-down-ja` |
| 6 | `junglesnake-death-ja` |
| 7 | `junglesnake-give-up-ja` |

---

## Spawning

- Entity type: `"junglesnake"`
- Art group: `junglesnake-ag`
- Source: `levels/jungle/junglesnake.gc` (JUN.DGO)
- Nav safe: ✅ yes — no navmesh needed, no crash risk
- Linked actors: none
- Path required: no

### Addon setup (v9+)
The addon handles everything automatically:
- `junglesnake.o` injected into custom DGO
- No duplicate `goal-src` injection (vanilla `game.gp` already compiles it)
- Art group and tpages (JUNGLE_TPAGES) added automatically

### Placement tips
- Place hanging from ceiling geometry — it's designed as a drop-down ambush
- bsphere 120m required (same as all enemies) so `was-drawn` gets set and AI activates
- No rotation needed — it tracks the player automatically via joint math

---

## Source File
`goal_src/jak1/levels/jungle/junglesnake.gc`

## Related Files
- `goal_src/jak1/engine/data/art-elts.gc` — animation asset definitions
- `goal_src/jak1/dgos/jun.gd` — vanilla DGO containing junglesnake.o
