# Claude Skills & Techniques

This file is loaded at the start of relevant sessions to give Claude access to proven techniques and tools.

---

## GitHub / Repo Navigation (Zero Token Cost)

These commands extract information from repos WITHOUT loading file contents into context.

### Find files by keyword
```bash
git grep -l "keyword"                    # list files containing keyword
git grep -l "keyword" goal_src/jak1/     # scoped to folder
```

### Extract matching lines only (not whole files)
```bash
git grep -n "keyword"                    # show line numbers + matching lines
git grep -n -A 5 "keyword"              # matching lines + 5 lines after
git grep -n "deftype babak"             # find type definitions
git grep -n "defstate.*babak"           # find state definitions
git grep -n "init-from-entity!"         # find spawn/init patterns
```

### List files in a folder without reading them
```bash
git ls-tree --name-only HEAD some/folder/
git ls-tree -r --name-only HEAD         # recursive, entire repo
```

### File sizes without reading contents
```bash
find . -name "*.gc" | xargs wc -l | sort -n   # line counts
du -sh some/folder/                              # folder size
```

### Commit history for a file
```bash
git log --oneline -10 -- path/to/file.gc
```

### Sparse checkout — clone ONE folder instead of whole repo
```bash
mkdir sparse-test && cd sparse-test
git init
git remote add origin https://github.com/org/repo.git
git sparse-checkout init
git sparse-checkout set path/to/folder
git pull origin main --depth=1
```

---

## Network Constraints on Claude's VM

### Allowed domains
- github.com ✓ (git clone, push, pull)
- api.anthropic.com ✓
- pypi.org, npmjs.com, etc. ✓ (package managers)

### Blocked domains
- raw.githubusercontent.com ✗
- api.github.com ✗
- Most external URLs ✗

### Implication
- Can clone/push repos via git
- Cannot fetch raw files via curl/wget from GitHub
- Cannot use GitHub REST API directly

---

## Lean Output Pipeline

Goal: produce output without loading it into conversational context.

### Pattern
1. Use git grep for triage (cheap — only line extracts hit context)
2. Compose output and write directly to disk
3. Push to GitHub — nothing renders in chat
4. User reads output from repo directly

### Why this matters
- Rendering files in chat loads them into context window
- Pushing to GitHub does NOT load into context
- This keeps sessions running longer without bogging down

### Example
```bash
# Good - output goes to github, not chat
git add output.md && git commit -m "add doc" && git push

# Avoid - renders in chat, loads into context
cat output.md
```

---

## Persistent Storage Structure

```
Claude-Relay/
├── CLAUDE-SKILLS.md              # this file - load at session start
├── README.md
├── addons/
│   └── opengoal_tools.py         # PROTECTED on main — working file on feature branches
├── backups/                      # snapshots, never delete
├── knowledge-base/               # PROTECTED on all branches — propose changes in chat first
│   └── opengoal/
├── session-notes/                # free to update, tracks progress per topic
│   ├── opengoal-progress.md      # camera, enemies, general addon work
│   └── audio-panel-progress.md   # audio panel, sound emitters
└── scratch/                      # throwaway / WIP files, free to use
```

---

## Storage Rules

### Branch-aware workflow — read this every session

**Step 1: find the right branch**
Read the relevant session-notes file. It will say which branch the topic lives on.
Then check it out and pull latest, including any knowledge-base/session-notes updates from main:
```bash
git checkout feature/X && git pull && git merge main
```

**Branch rules:**
- `main`          → NEVER commit directly. Only merged from feature branches with explicit user permission.
- `feature/*`     → `addons/opengoal_tools.py` is the working file. Edit freely.
- `scratch/`      → still available for throwaway experiments or multi-step WIP.
- `knowledge-base/` → PROTECTED on all branches. Propose changes in chat, wait for approval.
- `knowledge-base/` → **ALWAYS lives on main.** After writing or updating any knowledge doc on a feature branch, immediately cherry-pick or copy it to main and push. Knowledge docs must never stay branch-only.
- `session-notes/`  → stays on its feature branch. Never pushed to main.

**Merging to main:**
Only when the user explicitly says "merge to main", or after you ask and are given permission.
```bash
git checkout main && git merge feature/X && git push
git checkout feature/X   # return to working branch after
```

**What counts as merge permission:**
- ✅ "Merge audio to main"
- ✅ "Yes" in response to "want me to merge this to main?"
- ❌ Anything ambiguous — ask first
- ❌ "this is good", "looks great", "nice" — do NOT treat as merge permission

### Knowledge base write protection
- `knowledge-base/` files are NEVER overwritten without explicit user approval
- If an improvement is identified, propose the change in chat first and wait for approval
- If approved, push the update and note what changed in the commit message
- **knowledge-base/ always lives on main** — after any approved write, immediately push the file to main (cherry-pick the commit, or copy + commit directly on main). Knowledge docs must not stay branch-only.
- `session-notes/` stays on its feature branch and is never pushed to main
- `scratch/` can be written freely without approval
- When in doubt, write to `scratch/` as a draft and ask the user to review

---

## OpenGOAL Specific

### Repo
https://github.com/open-goal/jak-project

### Key folders
| Folder | Contents | Priority |
|---|---|---|
| goal_src/jak1/ | Game logic, entities, levels | High |
| docs/ | Sparse existing docs (3MB) | High |
| decompiler/ | Decompiler tooling | Medium |
| game/ | C++ engine | Medium |
| third-party/ | Dependencies (200MB) | Ignore |
| test/ | Test references (93MB) | Low |

### File types
- `.gc` — GOAL source files (4,871 total) — main target
- `.h` / `.cpp` — C++ engine code
- `.json` — config/build files

### Useful grep patterns for OpenGOAL
```bash
git grep -n "deftype X"           # find type definition
git grep -n "defstate.*X"         # find all states for type X
git grep -n "init-from-entity!"   # find spawn logic
git grep -n "def-art-elt X"       # find animation assets
git grep -l "X" goal_src/jak1/dgos/  # find which levels use X
git grep -n ":states" file.gc     # list states in a file
```

### Inheritance chain for game entities
```
process
  └── process-drawable
        └── nav-enemy
              └── (specific enemy type e.g. babak)
```
