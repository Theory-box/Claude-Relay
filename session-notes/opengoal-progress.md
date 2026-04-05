# OpenGOAL Knowledge Base — Session Notes

## Repo
https://github.com/open-goal/jak-project (clone to VM as jak-project)

## Approach
- Use git grep and git ls-tree for cheap triage — never read full files unless needed
- Sparse checkout folders instead of full repo when needed
- Push outputs to GitHub, share direct link — never render large files in chat

## What we know
- Repo: 555MB total, 4871 .gc files
- Useful dirs: goal_src/jak1/ (game logic), docs/ (sparse, 3MB)
- Ignore: third-party/ (200MB), test/ (93MB)
- Key tool: git grep -l to find files, git grep -n to extract lines
- raw.githubusercontent.com BLOCKED on Claude VM — use git clone only
- api.github.com BLOCKED

## Addon — opengoal_tools_v10.py (current scratch)
### v9 fix: enemy code injection (o_only flag)
### v10 fix: player spawn + nREPL reliability

## nREPL (port 8181) — KEY FACTS
- GOALC opens port 8181 on startup as a TCP socket server
- "nREPL: DISABLED" = bind() failed = another GOALC is holding the port
- goalc_send() returns None silently on ConnectionRefusedError — no visible error
- FIX: always kill_goalc() before launch_goalc()

## startup.gc sequencing
- Lines ABOVE ";; og:run-below-on-listen" → run immediately at GOALC startup (run_before_listen)
- Lines BELOW the sentinel → run automatically after (lt) connects to GK (run_after_listen)
- (lt) belongs ABOVE the sentinel; (bg) and (start) belong BELOW it
- DO NOT use (suspend-for) in startup.gc — it's a GOAL runtime function, errors in REPL context
- run_after_listen is triggered by GK being ready, not by sleep timers

## Player spawn fix
- (bg) loads level geometry + calls set-continue! to first continue-point
- (bg) does NOT kill/respawn the player — boot player falls in void and dies
- Fix: call (start 'play (get-or-create-continue! *game-info*)) after (bg)
- (start) kills old player process, spawns fresh at the continue-point (bg) set

## Confirmed working enemies (tested in-game)
- ✅ babak — always worked (GAME.CGO)
- ✅ junglesnake — confirmed April 2026, v9 fix. Stationary, safest enemy to use.
- ✅ hopper — confirmed April 2026, v9 fix. Nav-enemy, needs navmesh workaround.

## Documented
- [x] babak.md
- [x] junglesnake.md
- [x] entity-spawning.md
- [x] modding-addon.md
- [x] player-loading-and-continues.md
- [x] nrepl-and-startup.md  ← NEW April 2026

## Scratch files
- scratch/opengoal_tools_v10.py — current working version

## Open questions
- [ ] bonelurker crash — still unsolved
- [ ] navmesh — no engine support yet
- [ ] Enemy attack/walk-through collision confirmed in-game?
- [ ] Continue testing other enemies with v9 fix
- [ ] Test v10 spawn fix in practice

## Next session
- Confirm v10 spawn fix works (player spawns at SPAWN_ location on Play)
- Test more enemies
- Investigate bonelurker crash
