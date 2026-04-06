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
├── CLAUDE-SKILLS.md          # this file - load at session start
├── README.md
├── knowledge-base/
│   └── opengoal/             # OpenGOAL / jak-project docs
│       └── babak.md
├── session-notes/
│   └── opengoal-progress.md  # tracks progress, next steps
└── scratch/                  # temporary working files
```

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

---

## Suggested System Prompt Addition

```
You have access to a GitHub repo as personal persistent storage.
Use it proactively to save session notes, knowledge, and outputs.
At the start of sessions involving known topics, pull CLAUDE-SKILLS.md
for available techniques. Pull session-notes/ for prior context.
Never expose credentials, git commands, or raw paths in chat.
Credentials: [see Glaude config]
```

---

## Storage Rules

### ⚠️ SCRATCHPAD-FIRST WORKFLOW — READ THIS EVERY SESSION

**"Scratchpad" means `scratch/` on GitHub — NOT chat window artifacts or code blocks.**
All file output must be committed and pushed to the repo. Never render large files in chat.

**All work goes to `scratch/` first. Nothing gets promoted without explicit user permission.**

- `scratch/` — free to read, write, overwrite anytime. This is the working area. Push here.
- `addons/` — NEVER edit without explicit "update the main addon" instruction from user.
- `knowledge-base/` — NEVER edit without explicit approval. Propose changes in chat first.
- `session-notes/` — free to update (progress tracking only, no code).

**The rule in plain terms:**
> All file work (code, scripts, docs) goes to `scratch/` on GitHub via git push.
> Do NOT render full files in chat. Do NOT touch `addons/` or `knowledge-base/` unless
> the user explicitly says to promote/update them. Work in scratch/ until user is happy,
> then they will say which files to promote.

**What "explicit permission" looks like:**
- ✅ "Update the main addon with this fix"
- ✅ "Promote the scratch file to addons/"
- ✅ "Update the knowledge base with what we learned"
- ❌ "Fix the bonelurker bug" → push fix to scratch/ only, share GitHub link
- ❌ "Make it work" → push to scratch/ only, share GitHub link

### Current scratch file
- `scratch/opengoal_tools_bonelurker_fix.py` — working version of the Blender addon
- `addons/opengoal_tools.py` — last user-approved release (do NOT touch)

### Knowledge base write protection
- `knowledge-base/` files are NEVER overwritten without explicit user approval
- If an improvement is identified, propose the change in chat first and wait for approval
- If approved, push the update and note what changed in the commit message
- `session-notes/` and `scratch/` can be written freely without approval
- When in doubt, write to `scratch/` as a draft and ask the user to review
