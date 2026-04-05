# OpenGOAL Knowledge Base — Session Notes

## Repo
https://github.com/open-goal/jak-project (clone to VM as jak-project)

## Approach
- Use git grep and git ls-tree for cheap triage — never read full files unless needed
- Sparse checkout folders instead of full repo when needed
- Write knowledge to this repo, load at start of next session
- Push outputs to GitHub, share direct link — never render large files in chat

## What we know
- Repo: 555MB total, 4871 .gc files
- Useful dirs: goal_src/jak1/ (game logic), docs/ (sparse, 3MB)
- Ignore: third-party/ (200MB), test/ (93MB)
- Key tool: git grep -l to find files, git grep -n to extract lines
- raw.githubusercontent.com is BLOCKED on Claude VM — use git clone only
- api.github.com is also BLOCKED

## Addon — opengoal_tools_v9.py
Major fix: all vanilla enemies were marked in_game_cgo=True incorrectly.
Only babak is actually in GAME.CGO. All others need their .o injected into
the custom DGO. Fixed with new o_only=True flag — injects .o without
duplicate goal-src lines (which would cause fatal duplicate defstep errors).

## Confirmed working enemies (tested in-game)
- ✅ babak — always worked (GAME.CGO)
- ✅ junglesnake — confirmed working April 2026 with v9 fix
  - Stationary, no navmesh, no linked actors, safest enemy to use
  - Place hanging from ceiling, bsphere 120m required

## Documented
- [x] babak.md
- [x] junglesnake.md
- [x] entity-spawning.md
- [x] modding-addon.md
- [x] opengoal_tools_v9.py

## Open questions
- [ ] bonelurker crash — still unsolved
- [ ] navmesh — no engine support yet
- [ ] Which other enemies work with v9 fix? (hopper, kermit likely next candidates)
- [ ] Enemy attack/walk-through collision confirmed?
