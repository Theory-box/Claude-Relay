# Claude Relay Storage

This repo is used by Claude as persistent storage across sessions.

## Structure
- `knowledge-base/` — documented knowledge extracted from codebases
  - `opengoal/` — OpenGOAL / jak-project documentation
- `session-notes/` — context and state to carry between sessions
- `scratch/` — temporary working files

## Purpose
Claude cannot retain memory between sessions. This repo acts as an external brain —
knowledge extracted in one session can be loaded at the start of the next,
allowing work to continue without starting from scratch.
