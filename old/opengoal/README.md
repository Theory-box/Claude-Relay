# OpenGOAL Modding Bundle

Linux x64 binaries + full GOAL source tree for Jak 1 custom level development.

## Reassemble & Extract

```bash
cat opengoal-bundle.part_aa \
    opengoal-bundle.part_ab > opengoal-bundle.tar.gz

tar -xzf opengoal-bundle.tar.gz
cd opengoal-bundle/
```

## Contents After Extraction

```
extractor          — ISO extraction + decompile + compile (one-shot setup)
goalc              — GOAL compiler server (nREPL on port 8181)
gk                 — Game kernel executable
data/goal_src/     — Full GOAL source tree (engine + custom level support)
data/game/         — Runtime assets (textures, fonts, graphics)
data/custom_assets/— Working test-zone example level
README.md          — Quick start for humans
README-AI.md       — Full technical reference for AI assistants
```

## Quick Start

### 1. Provide your own Jak 1 disc data
You need a legally-owned copy of Jak and Daxter: The Precursor Legacy (NTSC v1, PS2),
extracted to a folder.

### 2. Decompile (one-time, ~10 min)
```bash
./extractor --proj-path ./data --folder --decompile /path/to/jak1/disc/
```

### 3. Compile (~15 min)
```bash
./extractor --proj-path ./data --folder --compile /path/to/jak1/disc/
```

### 4. Install the Blender addon
Clone https://github.com/Theory-box/Claude-Relay, checkout `feature/vis-blocker`,
copy `addons/opengoal_tools/` into your Blender 4.4 addons folder:
```
Linux:   ~/.config/blender/4.4/scripts/addons/
Windows: %APPDATA%\Blender Foundation\Blender\4.4\scripts\addons\
```
Enable in Edit → Preferences → Add-ons → search "OpenGOAL Tools".

### 5. Configure the addon
In Blender Preferences → Add-ons → OpenGOAL Tools:
- Project Path → `/path/to/opengoal-bundle/data`
- GOALC Path   → `/path/to/opengoal-bundle/goalc`
- GK Path      → `/path/to/opengoal-bundle/gk`

### 6. Build
Create a Blender collection, name it `test-zone`, add a `SPAWN_start` empty,
hit **Build & Play**. The game should launch and load the test zone.

## Blender Binary
A Linux x64 Blender 4.4.3 binary is stored in the repo `blender/` folder
(same split-chunk format). Reassemble the same way.

## For AI Assistants
See `README-AI.md` (inside the extracted bundle) and:
- `knowledge-base/opengoal/ai-onboarding.md` in this repo — full architecture guide
- `session-notes/` — current feature work state
- Active development branch: `feature/vis-blocker`
