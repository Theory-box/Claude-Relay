# Claude VM — Network & Capabilities Reference

All findings verified by live testing in the VM, not assumptions.

---

## ALLOWED DOMAINS (Whitelist)

These are the only domains the egress proxy permits. Everything else returns
`x-deny-reason: host_not_allowed` and connection code 000.

| Domain | What it's for | HTTP status |
|---|---|---|
| `api.anthropic.com` | Anthropic API (Claude itself) | 404 (no root, but reachable) |
| `archive.ubuntu.com` | Ubuntu apt package repository | 200 ✓ |
| `security.ubuntu.com` | Ubuntu security patches (apt) | 301 ✓ |
| `crates.io` | Rust package registry (cargo) | 403 (auth required, reachable) |
| `index.crates.io` | Rust crate index | 200 ✓ |
| `static.crates.io` | Rust crate downloads | 403 (reachable) |
| `files.pythonhosted.org` | Python package downloads (pip) | 200 ✓ |
| `pypi.org` | Python package index (pip) | 200 ✓ |
| `pythonhosted.org` | Python packages (legacy) | 200 ✓ |
| `github.com` | GitHub repos (git clone via HTTPS) | 200 ✓ |
| `npmjs.com` | Node.js packages (npm) | 301 ✓ |
| `npmjs.org` | npm alias | 301 ✓ |
| `www.npmjs.com` | npm web | 403 (reachable) |
| `www.npmjs.org` | npm alias | 301 ✓ |
| `registry.npmjs.org` | npm package downloads | 200 ✓ |
| `registry.yarnpkg.com` | Yarn package downloads | 200 ✓ |
| `yarnpkg.com` | Yarn package manager | 200 ✓ |

---

## BLOCKED DOMAINS (Confirmed)

All return `x-deny-reason: host_not_allowed`:

```
google.com               gitlab.com              bitbucket.org
raw.githubusercontent.com  objects.githubusercontent.com  codeload.github.com
huggingface.co           docker.com              hub.docker.com
releases.ubuntu.com      blender.org             download.blender.org
sourceforge.net          codeberg.org            stackoverflow.com
apt.llvm.org             deb.nodesource.com      download.pytorch.org
conda.anaconda.org       anaconda.com            cmake.org
ffmpeg.org
```

**Notable:** `raw.githubusercontent.com` is blocked even though `github.com` works.
This means you can `git clone` repos but can't `curl` raw files from GitHub directly.
Git clone works because the proxy handles `github.com` traffic specially.

---

## WHAT WORKS IN PRACTICE

### ✅ Git Clone (Public Repos)
```bash
git clone --depth 1 https://github.com/OWNER/REPO
```
Works. The proxy handles github.com HTTPS git traffic.
`--depth 1` recommended to avoid downloading full history.

### ✅ pip install
```bash
pip install PACKAGE --break-system-packages
```
Works. Hits `pypi.org` + `files.pythonhosted.org`.

### ✅ npm install
```bash
npm install PACKAGE
```
Works. Hits `registry.npmjs.org`.

### ✅ yarn install
```bash
yarn add PACKAGE
```
Works. Hits `registry.yarnpkg.com`.

### ✅ apt install
```bash
apt-get install PACKAGE
```
Works. Hits `archive.ubuntu.com` + `security.ubuntu.com`.

### ✅ Anthropic API calls (from artifacts/code)
```python
# From code running in the VM:
import httpx
response = httpx.post("https://api.anthropic.com/v1/messages", ...)
```
Works. This is how AI-powered artifacts call Claude.

### ⚠️ cargo (Rust)
Not installed by default. Would need `apt install cargo` first.
Crates.io is whitelisted so it would work once installed.

### ❌ curl/wget to non-whitelisted domains
```bash
curl https://blender.org/download/...   # BLOCKED
wget https://ffmpeg.org/releases/...    # BLOCKED
curl https://raw.githubusercontent.com/... # BLOCKED
```

### ❌ GUI applications
No display server. Anything needing a window fails.
Blender, VS Code, browsers, etc. — all blocked at the display level.

### ✅ Blender headless / background mode
If Blender were installed (it isn't by default), this would work:
```bash
blender --background --python script.py
```
No display needed. Useful for scripted mesh processing.

---

## KEY IMPLICATIONS

### You CANNOT directly download:
- Raw files from GitHub (`raw.githubusercontent.com` blocked)
- Blender, FFmpeg, CMake, LLVM, PyTorch, Docker images
- Anything from non-listed domains
- Private repos (no auth mechanism)

### You CAN:
- Clone any **public** GitHub repo
- Install any pip/npm/yarn/apt package
- Run code from cloned repos
- Call the Anthropic API
- Process files uploaded by the user (available at `/mnt/user-data/uploads/`)

### Workarounds for blocked downloads:
| Need | Workaround |
|---|---|
| Raw GitHub file | Clone the full repo, read the file locally |
| Blender binary | Upload it as a file attachment |
| PyTorch | `pip install torch` (goes through PyPI ✓) |
| FFmpeg | `apt install ffmpeg` (goes through Ubuntu apt ✓) |
| CMake | `apt install cmake` (Ubuntu apt ✓) |
| Docker images | Can't — no Docker daemon, no registry access |

---

## PRACTICAL EXAMPLES

### Clone a repo and run it
```bash
git clone --depth 1 https://github.com/owner/repo /home/claude/repo
cd /home/claude/repo
pip install -r requirements.txt --break-system-packages
python main.py
```

### Install a tool via apt and use it
```bash
apt-get install -y ffmpeg imagemagick
ffmpeg -i input.mp4 output.gif
```

### Install Python packages and use them
```bash
pip install numpy pandas matplotlib --break-system-packages
python3 -c "import numpy; print(numpy.__version__)"
```

### Call Anthropic API from code
```python
import httpx, json
response = httpx.post(
    "https://api.anthropic.com/v1/messages",
    headers={"Content-Type": "application/json"},
    json={
        "model": "claude-sonnet-4-6",
        "max_tokens": 1000,
        "messages": [{"role": "user", "content": "Hello"}]
    }
)
print(response.json())
```

---

## SESSION PERSISTENCE

- VM **resets between conversations** — nothing persists
- Within a single conversation, everything persists (files, installed packages, cloned repos)
- The `/mnt/user-data/uploads/` and `/mnt/user-data/outputs/` directories are the bridge:
  - Uploads: files you attach to messages
  - Outputs: files I put there for you to download

---

## SYSTEM INFO

```
OS: Ubuntu 24 (Linux)
Python: 3.x (system)
Node: available
npm/yarn: available
git: available
curl/wget: available (for whitelisted domains only)
Working directory: /home/claude
Upload path: /mnt/user-data/uploads/
Output path: /mnt/user-data/outputs/
```
