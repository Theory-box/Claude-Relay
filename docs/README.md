# OpenGOAL Tools — Documentation

Documentation for the **OpenGOAL Tools** Blender addon — a toolkit for creating custom Jak and Daxter levels using the [OpenGOAL](https://github.com/open-goal/jak-project) engine.

> All documentation reflects the current addon version. Confirmed working on Blender 4.4+ and OpenGOAL v0.2.29+.

---

## Getting Started

| Doc | Description |
|---|---|
| [Getting Started](getting-started.md) | Install the addon, set preferences, create your first level |
| [Workflow](workflow.md) | Export & Build vs Play, console management, common issues |

---

## Level Content

| Doc | Description |
|---|---|
| [Entity Spawning](entity-spawning.md) | Place enemies, NPCs, pickups, platforms — JSONC format, DGO/game.gp, bsphere rules |
| [Audio System](audio-system.md) | Sound banks, music, ambient sound emitters, known bugs |
| [Camera System](camera-system.md) | Camera markers, trigger volumes, orbit pivots, look-at targets |
| [Player & Continues](player-loading.md) | Spawn points, continue points, level registration |

---

## Enemy Reference

| Doc | Enemy | Notes |
|---|---|---|
| [Babak](enemies/babak.md) | Babak (lurker soldier) | Always in GAME.CGO, no DGO needed |
| [Junglesnake](enemies/junglesnake.md) | Junglesnake | No navmesh required, safest enemy to use |

---

## Data Reference

| File | Description |
|---|---|
| [Enemy Definitions](data/jak1-enemy-definitions.json) | All entity types, art groups, code paths |
| [SBK Sounds](data/sbk_sounds.json) | All 1,048 sound effect names across 24 banks |

---

## External Resources

- [OpenGOAL Project](https://github.com/open-goal/jak-project)
- [Rockpool Mod (reference level)](https://github.com/dallmeyer/OG-ModBase-Rockpool)
- [OpenGOAL Discord](https://discord.gg/VZbXMHXzTv)
