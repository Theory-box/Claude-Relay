# Getting Started

This guide covers installing the OpenGOAL Tools addon and setting up your first custom level.

---

## Requirements

- **Blender** 4.4 or newer
- **OpenGOAL** (`jak-project`) — cloned and built from [github.com/open-goal/jak-project](https://github.com/open-goal/jak-project)
- **Jak and Daxter: The Precursor Legacy** — USA disc image (dumped ISO)
- **OpenGOAL version**: v0.2.29+

---

## Installing the Addon

1. Download `opengoal_tools.py` from this repository (`addons/opengoal_tools.py`)
2. Open Blender → **Edit → Preferences → Add-ons**
3. Click **Install…** and select the downloaded `.py` file
4. Enable the addon — search for **"OpenGOAL Level Tools"** and tick the checkbox

The addon appears in the **N-Panel** (press `N` in the 3D viewport) under the **OpenGOAL** tab.

---

## Setting Preferences

After enabling the addon, you need to set two paths. Click **Set EXE / Data Paths** in the Build & Play panel, or go to **Edit → Preferences → Add-ons → OpenGOAL Level Tools**.

| Preference | What to set |
|---|---|
| **EXE folder** | Folder containing `gk.exe` and `goalc.exe` (your OpenGOAL build output) |
| **Data folder** | Your `jak-project` root folder (contains `data/goal_src`) |

Example paths:
```
EXE folder:  C:/jak-project/build/bin
Data folder: C:/jak-project
```

---

## Creating Your First Level

### 1. Set a level name

In the **⚙ Level Settings** panel, enter a short lowercase name with no spaces (e.g. `mylevel`). This becomes the internal level identifier used for all generated files.

### 2. Model your geometry

Build your level geometry in Blender as normal. Keep it simple to start — a flat platform is enough to verify everything works.

### 3. Place a spawn point

In the **➕ Place Objects** panel, click **Add Player Spawn**. This creates an empty named `SPAWN_start` at the cursor position. The player will spawn here.

### 4. Export & Build

Click **Export & Build** in the **▶ Build & Play** panel. This:
- Exports your scene as `.glb`
- Generates all required source files (`.jsonc`, `.gd`, `-obs.gc`)
- Patches `level-info.gc` and `game.gp` in the OpenGOAL source tree
- Compiles the level using GOALC

Watch the Blender console for any errors. A successful build ends with GOALC printing `Done`.

### 5. Play

Click **Play** to launch the game and load your level. If GOALC is already running and connected (nREPL), it reuses the existing session — faster than a cold start.

> **Note**: Play does **not** recompile. Always run Export & Build first if you've made changes.

---

## File Structure

The addon writes into your OpenGOAL data folder:

```
<jak-project>/active/jak1/data/
  custom_assets/jak1/levels/<name>/
    <name>.glb           ← exported mesh
    <name>.jsonc         ← actor/ambient placement
    <nick>.gd            ← DGO definition file

  goal_src/jak1/
    levels/<name>/
      <name>-obs.gc      ← stub GOAL source
    engine/level/
      level-info.gc      ← patched (level registration)
    game.gp              ← patched (build entries)
    user/blender/
      startup.gc         ← auto-generated GOALC startup
```

---

## Next Steps

- [Workflow](workflow.md) — understand Export & Build vs Play in detail
- [Entity Spawning](entity-spawning.md) — add enemies, pickups, platforms
- [Audio System](audio-system.md) — add sound banks and ambient sound emitters
- [Camera System](camera-system.md) — add scripted camera zones
