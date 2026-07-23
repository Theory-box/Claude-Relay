bl_info = {
    "name": "Cycle Relay",
    "author": "Claude Relay",
    "version": (8, 2, 0),
    "blender": (4, 4, 0),
    "location": "Preferences > Add-ons > Cycle Relay",
    "description": "Map any input to any action via a Hammerspoon middleman. "
                   "Cycle transform axes with a single key.",
    "category": "System",
}

import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
import urllib.request

import bpy

HOME = os.path.expanduser("~")
CONFIG_DIR = os.path.join(HOME, ".config", "blender-cycle-relay")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
# Logs live outside CONFIG_DIR on purpose: writing them inside it used to
# retrigger the config watcher and wipe the armed state mid-transform.
LOG_DIR = os.path.join(HOME, ".cache", "blender-cycle-relay")
RECENT_PATH = os.path.join(LOG_DIR, "recent.log")
HS_DIR = os.path.join(HOME, ".hammerspoon")
LUA_NAME = "blender_cycle_relay.lua"
LUA_PATH = os.path.join(HS_DIR, LUA_NAME)
INIT_LUA = os.path.join(HS_DIR, "init.lua")
REQUIRE_LINE = 'require("blender_cycle_relay")'
MARKER = "-- added by Blender Cycle Relay add-on"
RELEASE_API = "https://api.github.com/repos/Hammerspoon/hammerspoon/releases/latest"
APP_NAME = "Hammerspoon.app"

KEY_TO_HS = {
    'TAB': 'tab', 'SPACE': 'space', 'GRAVE': '`',
    'OSKEY': 'cmd', 'LEFT_CTRL': 'ctrl', 'RIGHT_CTRL': 'ctrl',
    'LEFT_ALT': 'alt', 'RIGHT_ALT': 'alt',
    'LEFT_SHIFT': 'shift', 'RIGHT_SHIFT': 'shift',
    'ESC': 'escape', 'RET': 'return', 'NUMPAD_ENTER': 'padenter',
    'LEFTMOUSE': 'leftmouse', 'RIGHTMOUSE': 'rightmouse',
    'MIDDLEMOUSE': 'middlemouse',
    'BUTTON4MOUSE': 'mouse4', 'BUTTON5MOUSE': 'mouse5',
    'DEL': 'delete', 'BACK_SPACE': 'delete',
    'LEFT_ARROW': 'left', 'RIGHT_ARROW': 'right',
    'UP_ARROW': 'up', 'DOWN_ARROW': 'down',
}

MODIFIER_KEYS = {"cmd", "ctrl", "alt"}

ACTION_ITEMS = [
    ('cycle_axis', "Cycle X / Y / Z", "Send the next axis key"),
    ('cycle_plane', "Cycle XY / XZ / YZ", "Send the next plane (shift + axis)"),
    ('send', "Send a key", "Send whatever key you type below"),
    ('arm', "Arm", "Mark a transform as active"),
    ('disarm', "Disarm", "Mark the transform as finished"),
]

WHEN_ITEMS = [
    ('always', "Always", "Fires whenever the input matches"),
    ('armed', "Only when armed", "Fires only during a transform"),
]

# Sensible starting point: Cmd+Click starts a move, Tab cycles.
DEFAULT_RULES = [
    dict(input="leftmouse", cmd=True, action="send", output="g",
         swallow=True, also_arm=True, when="always",
         note="Cmd+Click -> G (start move)"),
    dict(input="tab", action="cycle_axis", swallow=True, when="armed",
         note="Tab cycles X/Y/Z"),
    dict(input="tab", shift=True, action="cycle_plane", swallow=True,
         when="armed", note="Shift+Tab cycles planes"),
    dict(input="g", action="arm", when="always", note="G arms"),
    dict(input="r", action="arm", when="always", note="R arms"),
    dict(input="s", action="arm", when="always", note="S arms"),
    dict(input="leftmouse", action="disarm", when="armed",
         note="Plain click confirms -> ends transform"),
    dict(input="escape", action="disarm", when="always", note="Esc ends"),
    dict(input="return", action="disarm", when="always", note="Enter ends"),
]

LUA_SOURCE = r'''
-- blender_cycle_relay.lua   RULE ENGINE BUILD
--
-- Behaviour is entirely defined by rules in config.json, written by Blender.
-- Each rule: an input (key or mouse button + modifiers) -> an action.
--
-- SAFETY RAILS:
--   1. synthetic events tagged + skipped -> cannot feed back on itself
--   2. only swallows inputs whose rule says so
--   3. burst limiter auto-disables
--   4. handlers pcall-wrapped; error disables rather than blocks
--   5. dead-man timer
--   6. menubar Stop
--   7. inert unless Blender is frontmost

local M = {}

local HOME = os.getenv("HOME")
local CFG_DIR = HOME .. "/.config/blender-cycle-relay"
local CFG_PATH = CFG_DIR .. "/config.json"
-- Logs deliberately live OUTSIDE the watched config dir: writing them in
-- there re-triggered the config watcher, which reset the armed state.
local LOG_DIR = HOME .. "/.cache/blender-cycle-relay"
local RECENT_PATH = LOG_DIR .. "/recent.log"
local BLENDER_BUNDLE = "org.blenderfoundation.blender"

local SELF_TAG = 5264724
local BURST_WINDOW = 2.0
local BURST_LIMIT = 200
local AUTO_STOP_MINUTES = 240
local POLL_SECONDS = 5
local GRACE_POLLS = 2
local RECENT_MAX = 40

local cfg = nil
local taps, menu, stopTimer, watcher, pollTimer = {}, nil, nil, nil, nil
local stopped = false
local burst, burstStart = 0, 0
local sent = 0
local recent = {}
local emptyPolls, sawBlender = 0, false

local AXIS = { "x", "y", "z" }
-- Blender names a plane by the axis it EXCLUDES:
-- shift+X = YZ, shift+Y = XZ, shift+Z = XY -> XY,XZ,YZ is z,y,x
local PLANE = { "z", "y", "x" }

local st = { armed = false, axis = 0, plane = 0, last = nil, armedAt = 0 }

-- ------------------------------------------------------------------ recent
local function pushRecent(line)
  recent[#recent + 1] = os.date("%H:%M:%S") .. "  " .. line
  while #recent > RECENT_MAX do table.remove(recent, 1) end
  local f = io.open(RECENT_PATH, "w")
  if not f then hs.fs.mkdir(LOG_DIR); f = io.open(RECENT_PATH, "w") end
  if f then f:write(table.concat(recent, "\n") .. "\n"); f:close() end
end

local function log(line)
  pushRecent(line)
  print("[relay] " .. line)
end

-- ------------------------------------------------------------------ safety
local function updateMenu()
  if not menu then return end
  if stopped then menu:setTitle("R:off")
  else menu:setTitle(st.armed and ("R*" .. sent) or ("R:" .. sent)) end
end

function M.stop(reason)
  if stopped then return end
  stopped = true
  for _, t in ipairs(taps) do pcall(function() t:stop() end) end
  if stopTimer then pcall(function() stopTimer:stop() end) end
  if pollTimer then pcall(function() pollTimer:stop() end) end
  log("STOPPED (" .. tostring(reason) .. ")")
  updateMenu()
end

local function guard()
  local t = hs.timer.secondsSinceEpoch()
  if (t - burstStart) > BURST_WINDOW then burstStart = t; burst = 0 end
  burst = burst + 1
  if burst > BURST_LIMIT then M.stop("burst limit"); return false end
  return true
end

-- ------------------------------------------------------------------ config
local lastRaw = nil

local function loadConfig()
  -- Only act on a genuine content change. The watcher can fire for unrelated
  -- writes, and reloading needlessly used to wipe the armed state mid-transform.
  local fh = io.open(CFG_PATH)
  local raw = fh and fh:read("a") or nil
  if fh then fh:close() end
  if raw ~= nil and raw == lastRaw then return end
  lastRaw = raw

  local ok, data = pcall(hs.json.read, CFG_PATH)
  if ok and data then
    cfg = data
    log("config loaded, " .. tostring(cfg.rules and #cfg.rules or 0) .. " rules")
  else
    cfg = nil
    log("NO CONFIG at " .. CFG_PATH)
  end
  -- NOTE: st.armed is intentionally left alone. A config reload says nothing
  -- about whether a transform is currently running.
  updateMenu()
end

local function frontIsBlender()
  local app = hs.application.frontmostApplication()
  return app and app:bundleID() == BLENDER_BUNDLE
end

local function isSelf(e)
  return e:getProperty(hs.eventtap.event.properties.eventSourceUserData) == SELF_TAG
end

-- -------------------------------------------------------------------- send
-- A physically-held Cmd bleeds into synthetic keys: sending "g" while Cmd is
-- down arrives at Blender as Cmd+G (= Create New Collection). Explicitly
-- release held modifiers first so the app sees a clean, unmodified key.
local function releaseHeldMods(keep)
  local p = hs.eventtap.event.properties.eventSourceUserData
  local held = hs.eventtap.checkKeyboardModifiers() or {}
  for _, m in ipairs({ "cmd", "ctrl", "alt", "shift" }) do
    if held[m] and m ~= keep then
      local up = hs.eventtap.event.newKeyEvent({}, m, false)
      up:setProperty(p, SELF_TAG)
      up:post()
    end
  end
end

local function sendKey(key, withShift)
  if not key or key == "" then return end
  releaseHeldMods(withShift and "shift" or nil)
  local p = hs.eventtap.event.properties.eventSourceUserData
  local mods = withShift and { "shift" } or {}
  local d = hs.eventtap.event.newKeyEvent(mods, key, true)
  local u = hs.eventtap.event.newKeyEvent(mods, key, false)
  d:setFlags(withShift and { shift = true } or {})
  u:setFlags(withShift and { shift = true } or {})
  d:setProperty(p, SELF_TAG); u:setProperty(p, SELF_TAG)
  d:post(); u:post()
  sent = sent + 1
  log("  SENT " .. (withShift and "shift+" or "") .. key)
  updateMenu()
end

local function arm(why)
  st.armed = true; st.axis = 0; st.plane = 0; st.last = nil
  st.armedAt = hs.timer.secondsSinceEpoch()
  log("  ARMED (" .. why .. ")")
  updateMenu()
end

local function disarm(why)
  if not st.armed then return end
  st.armed = false
  log("  disarmed (" .. why .. ")")
  updateMenu()
end

local function cycleAxis()
  st.axis = (st.axis % 3) + 1
  st.last = AXIS[st.axis]
  sendKey(st.last, false)
end

local function cyclePlane()
  st.plane = (st.plane % 3) + 1
  sendKey(PLANE[st.plane], true)
end

-- ------------------------------------------------------------------- rules
local function flagsMatch(rule, flags)
  return (not not rule.cmd) == (not not flags.cmd)
     and (not not rule.shift) == (not not flags.shift)
     and (not not rule.ctrl) == (not not flags.ctrl)
     and (not not rule.alt) == (not not flags.alt)
end

-- Returns true if the originating event should be swallowed.
local function runRules(inputName, flags)
  if not cfg or not cfg.rules then return false end
  -- Stale-arm guard: a transform never runs for minutes, so if we still
  -- think one is active long after it started, we guessed wrong.
  local timeout = cfg.arm_timeout or 0
  if st.armed and timeout > 0
     and (hs.timer.secondsSinceEpoch() - st.armedAt) > timeout then
    disarm("timed out after " .. timeout .. "s")
  end
  for _, rule in ipairs(cfg.rules) do
    if rule.enabled ~= false and rule.input == inputName
       and flagsMatch(rule, flags) then
      if rule.when == "armed" and not st.armed then
        log("  rule '" .. tostring(rule.action) .. "' skipped (not armed)")
      else
        local a = rule.action
        if a == "cycle_axis" then cycleAxis()
        elseif a == "cycle_plane" then cyclePlane()
        elseif a == "send" then sendKey(rule.output, rule.out_shift)
        elseif a == "arm" then arm("rule")
        elseif a == "disarm" then disarm("rule")
        end
        if rule.also_arm and a ~= "arm" then arm("rule side-effect") end
        if rule.also_disarm and a ~= "disarm" then disarm("rule side-effect") end
        return rule.swallow == true
      end
    end
  end
  return false
end

-- ---------------------------------------------------------------- handlers
local function onKey(e)
  local swallow = false
  local ok = pcall(function()
    if stopped or not cfg or not cfg.enabled then return end
    if isSelf(e) then return end
    if not guard() then return end
    if not frontIsBlender() then return end
    local name = hs.keycodes.map[e:getKeyCode()]
    if not name then return end
    local flags = e:getFlags()
    if cfg.verbose then
      log(string.format("KEY %s armed=%s", name, tostring(st.armed)))
    end
    swallow = runRules(name, flags)
  end)
  if not ok then M.stop("error in key handler") end
  return swallow
end

local function onMouse(e)
  local swallow = false
  local ok = pcall(function()
    if stopped or not cfg or not cfg.enabled then return end
    if isSelf(e) then return end
    if not guard() then return end
    if not frontIsBlender() then return end
    local types = hs.eventtap.event.types
    local t = e:getType()
    local name = nil
    if t == types.leftMouseDown then name = "leftmouse"
    elseif t == types.rightMouseDown then name = "rightmouse"
    elseif t == types.otherMouseDown then name = "middlemouse" end
    if not name then return end
    local flags = e:getFlags()
    if cfg.verbose then
      log(string.format("MOUSE %s armed=%s", name, tostring(st.armed)))
    end
    swallow = runRules(name, flags)
  end)
  if not ok then M.stop("error in mouse handler") end
  return swallow
end

-- Modifier taps: a bare press+release of cmd/ctrl/alt with nothing in between.
local modDown, dirty = nil, false

local function onFlags(e)
  local ok = pcall(function()
    if stopped or not cfg or not cfg.enabled then return end
    if isSelf(e) then return end
    if not guard() then return end
    if not frontIsBlender() then return end
    local want = cfg.mod_tap_key
    if not want or want == "" then return end
    local flags = e:getFlags()
    local down = flags[want] and true or false
    if down then
      modDown = hs.timer.secondsSinceEpoch(); dirty = false
    else
      if modDown and not dirty then
        local ms = (hs.timer.secondsSinceEpoch() - modDown) * 1000
        if ms < (cfg.mod_tap_ms or 400) then
          runRules("modtap:" .. want, flags)
        end
      end
      modDown = nil
    end
  end)
  if not ok then M.stop("error in flags handler") end
  return false
end

local function markDirty(e)
  pcall(function() if not isSelf(e) then dirty = true end end)
  return false
end

-- ------------------------------------------------------------------- quit
local function countBlender()
  local apps = hs.application.applicationsForBundleID(BLENDER_BUNDLE)
  return apps and #apps or 0
end

local function poll()
  if not cfg or not cfg.auto_quit then return end
  local n = countBlender()
  if n > 0 then sawBlender = true; emptyPolls = 0; return end
  if not sawBlender then return end
  emptyPolls = emptyPolls + 1
  if emptyPolls >= GRACE_POLLS then
    log("no Blender instances left - quitting")
    M.stop("blender closed")
    os.exit(0)
  end
end

-- ------------------------------------------------------------------ start
function M.start()
  hs.fs.mkdir(CFG_DIR)
  hs.fs.mkdir(LOG_DIR)
  loadConfig()
  local types = hs.eventtap.event.types

  taps[#taps + 1] = hs.eventtap.new({ types.keyDown }, onKey)
  taps[#taps + 1] = hs.eventtap.new({ types.leftMouseDown,
                                      types.rightMouseDown,
                                      types.otherMouseDown }, onMouse)
  taps[#taps + 1] = hs.eventtap.new({ types.flagsChanged }, onFlags)
  taps[#taps + 1] = hs.eventtap.new({ types.keyDown, types.leftMouseDown },
                                    markDirty)
  for _, t in ipairs(taps) do pcall(function() t:start() end) end

  watcher = hs.pathwatcher.new(CFG_DIR, function() loadConfig() end)
  pcall(function() watcher:start() end)

  menu = hs.menubar.new()
  if menu then
    menu:setTitle("R:0")
    menu:setTooltip("Blender Cycle Relay")
    menu:setMenu({
      { title = "Stop now", fn = function() M.stop("user") end },
      { title = "Open recent log", fn = function()
          hs.execute("open -a TextEdit " .. RECENT_PATH) end },
    })
  end

  stopTimer = hs.timer.doAfter(AUTO_STOP_MINUTES * 60,
                               function() M.stop("auto-stop") end)
  pollTimer = hs.timer.doEvery(POLL_SECONDS, poll)
  log("started")
end

M.start()

return M
'''


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def is_macos():
    return platform.system() == "Darwin"


def _get_prefs():
    entry = bpy.context.preferences.addons.get(__name__)
    return entry.preferences if entry else None


def _hs_key(t):
    return KEY_TO_HS.get(t, t.lower())


def _luaskin_paths(app):
    fw = os.path.join(app, "Contents", "Frameworks", "LuaSkin.framework")
    return fw, os.path.join(fw, "Versions", "Current"), \
        os.path.join(fw, "Resources", "luaskin.lua")


def bundle_is_intact(app):
    if not app or not os.path.isdir(app):
        return False
    fw, cur, res = _luaskin_paths(app)
    return os.path.isdir(fw) and os.path.islink(cur) and os.path.isfile(res)


def find_hammerspoon():
    for base in ("/Applications", os.path.join(HOME, "Applications")):
        p = os.path.join(base, APP_NAME)
        if os.path.isdir(p):
            return p
    return None


def hammerspoon_running():
    try:
        return subprocess.run(["pgrep", "-x", "Hammerspoon"],
                              capture_output=True, timeout=5).returncode == 0
    except Exception:
        return False


def quit_hammerspoon(log=None):
    try:
        subprocess.run(["osascript", "-e",
                        'tell application "Hammerspoon" to quit'],
                       capture_output=True, timeout=15)
        time.sleep(1.2)
        subprocess.run(["pkill", "-x", "Hammerspoon"],
                       capture_output=True, timeout=10)
        time.sleep(0.4)
    except Exception as e:
        if log:
            log("could not stop Hammerspoon: %s" % e)


# ---------------------------------------------------------------------------
# Install steps
# ---------------------------------------------------------------------------
def step_install_hammerspoon(log, force=False):
    existing = find_hammerspoon()
    if existing and bundle_is_intact(existing) and not force:
        log("Hammerspoon present and intact")
        return True
    quit_hammerspoon(log)
    log("Downloading Hammerspoon...")
    try:
        req = urllib.request.Request(RELEASE_API,
                                     headers={"User-Agent": "cycle-relay"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.load(r)
    except Exception as e:
        log("FAILED to reach GitHub: %s" % e)
        return False
    url = None
    for a in data.get("assets", []):
        if a.get("name", "").endswith(".zip"):
            url = a.get("browser_download_url")
            break
    if not url:
        log("FAILED: no zip asset")
        return False
    tmp = tempfile.mkdtemp(prefix="relay-")
    z = os.path.join(tmp, "hs.zip")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cycle-relay"})
        with urllib.request.urlopen(req, timeout=300) as r, open(z, "wb") as f:
            shutil.copyfileobj(r, f)
        # ditto preserves the symlinks inside .app bundles; zipfile does not.
        res = subprocess.run(["ditto", "-x", "-k", z, tmp],
                             capture_output=True, text=True, timeout=300)
        if res.returncode != 0:
            log("FAILED ditto: %s" % (res.stderr or "")[:150])
            return False
    except Exception as e:
        log("FAILED download: %s" % e)
        return False
    src = None
    for root, dirs, _ in os.walk(tmp):
        if APP_NAME in dirs:
            src = os.path.join(root, APP_NAME)
            break
    if not src:
        log("FAILED: app not in archive")
        return False
    base = "/Applications"
    if not os.access(base, os.W_OK):
        base = os.path.join(HOME, "Applications")
        os.makedirs(base, exist_ok=True)
    dest = os.path.join(base, APP_NAME)
    try:
        for b in ("/Applications", os.path.join(HOME, "Applications")):
            old = os.path.join(b, APP_NAME)
            if os.path.isdir(old):
                shutil.rmtree(old, ignore_errors=True)
        shutil.move(src, dest)
        subprocess.run(["xattr", "-dr", "com.apple.quarantine", dest],
                       capture_output=True, timeout=30)
    except Exception as e:
        log("FAILED install: %s" % e)
        return False
    if not bundle_is_intact(dest):
        log("FAILED: bundle still broken")
        return False
    log("Installed to %s" % dest)
    return True


def step_write_lua(log):
    try:
        os.makedirs(HS_DIR, exist_ok=True)
        with open(LUA_PATH, "w") as f:
            f.write(LUA_SOURCE)
        log("wrote relay script")
        return True
    except Exception as e:
        log("FAILED writing lua: %s" % e)
        return False


def step_patch_init(log):
    try:
        existing = ""
        if os.path.isfile(INIT_LUA):
            with open(INIT_LUA) as f:
                existing = f.read()
        if REQUIRE_LINE in existing:
            return True
        if existing.strip():
            shutil.copy2(INIT_LUA, INIT_LUA + ".backup-%d" % int(time.time()))
        with open(INIT_LUA, "a") as f:
            if existing and not existing.endswith("\n"):
                f.write("\n")
            f.write("\n%s\n%s\n" % (MARKER, REQUIRE_LINE))
        log("patched init.lua")
        return True
    except Exception as e:
        log("FAILED init.lua: %s" % e)
        return False


def step_launch(log):
    app = find_hammerspoon()
    if not app:
        log("Hammerspoon not installed")
        return False
    # Always hard-restart: the hammerspoon://reload URL silently no-ops
    # unless a handler is bound, which leaves the OLD script running.
    try:
        if hammerspoon_running():
            quit_hammerspoon(log)
        subprocess.Popen(["open", "-a", app],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        log("restarted Hammerspoon")
        return True
    except Exception as e:
        log("FAILED launch: %s" % e)
        return False


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
def combo_text(key, cmd, shift, ctrl, alt):
    if not key:
        return "(not set)"
    mods = "".join(m for m, on in (("Cmd+", cmd), ("Shift+", shift),
                                   ("Ctrl+", ctrl), ("Alt+", alt)) if on)
    pretty = {"leftmouse": "Left Click", "rightmouse": "Right Click",
              "middlemouse": "Middle Click", "mouse4": "Mouse 4",
              "mouse5": "Mouse 5", "tab": "Tab", "space": "Space",
              "escape": "Esc", "return": "Enter"}.get(key, key.upper())
    return mods + pretty


def build_rules(prefs):
    """Everything the engine needs, derived from the two simple settings.
    The bookkeeping that used to be exposed as 'arm/disarm' lives here."""
    def R(**kw):
        d = dict(input="", cmd=False, shift=False, ctrl=False, alt=False,
                 action="send", output="", out_shift=False, when="always",
                 swallow=False, also_arm=False, also_disarm=False, enabled=True)
        d.update(kw)
        return d

    rules = []
    # 1. Your move shortcut. Blender normally handles it already, so we only
    #    note that a transform began: nothing sent, nothing swallowed.
    if prefs.move_input:
        if prefs.move_send_g:
            rules.append(R(input=prefs.move_input, cmd=prefs.move_cmd,
                           shift=prefs.move_shift, ctrl=prefs.move_ctrl,
                           alt=prefs.move_alt, action="send", output="g",
                           swallow=True, also_arm=True))
        else:
            rules.append(R(input=prefs.move_input, cmd=prefs.move_cmd,
                           shift=prefs.move_shift, ctrl=prefs.move_ctrl,
                           alt=prefs.move_alt, action="arm", swallow=False))
    # 2. Your cycle key -> step the axis, only during a transform.
    #    A bare modifier (Cmd/Ctrl/Alt) never arrives as a key event, so it
    #    is routed through the modifier-tap path instead.
    if prefs.cycle_input:
        ci = prefs.cycle_input
        name = ("modtap:" + ci) if ci in MODIFIER_KEYS else ci
        rules.append(R(input=name, action="cycle_axis",
                       when="armed", swallow=(ci not in MODIFIER_KEYS)))
        if prefs.enable_planes:
            rules.append(R(input=name, shift=True, action="cycle_plane",
                           when="armed",
                           swallow=(ci not in MODIFIER_KEYS)))
    # 3. Native transform keys also begin a transform.
    for k in ("g", "r", "s"):
        rules.append(R(input=k, action="arm"))
    # 4. Things that end a transform.
    rules.append(R(input="leftmouse", action="disarm", when="armed"))
    for k in ("escape", "return", "padenter"):
        rules.append(R(input=k, action="disarm"))
    return rules


def write_config(context=None):
    prefs = _get_prefs()
    if prefs is None:
        return None
    if not prefs.advanced:
        rules = build_rules(prefs)
    else:
        rules = []
        for r in prefs.rules:
            rules.append({
                "enabled": r.enabled,
                "input": r.input_key,
                "cmd": r.cmd, "shift": r.shift, "ctrl": r.ctrl, "alt": r.alt,
                "action": r.action,
                "output": r.output_key,
                "out_shift": r.out_shift,
                "when": r.when,
                "swallow": r.swallow,
                "also_arm": r.also_arm,
                "also_disarm": r.also_disarm,
            })
    data = {
        "enabled": prefs.relay_enabled,
        "verbose": prefs.verbose,
        "auto_quit": prefs.auto_quit,
        "mod_tap_key": (prefs.cycle_input
                        if (not prefs.advanced
                            and prefs.cycle_input in MODIFIER_KEYS)
                        else (prefs.mod_tap_key
                              if prefs.mod_tap_key != 'NONE' else "")),
        "mod_tap_ms": prefs.mod_tap_ms,
        "arm_timeout": prefs.arm_timeout,
        "rules": rules,
    }
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print("[Cycle Relay] config write failed:", e)
        return None
    return CONFIG_PATH


def _on_change(self, context):
    write_config(context)


def load_defaults(prefs):
    prefs.rules.clear()
    for d in DEFAULT_RULES:
        r = prefs.rules.add()
        r.input_key = d.get("input", "")
        r.cmd = d.get("cmd", False)
        r.shift = d.get("shift", False)
        r.ctrl = d.get("ctrl", False)
        r.alt = d.get("alt", False)
        r.action = d.get("action", "send")
        r.output_key = d.get("output", "")
        r.when = d.get("when", "always")
        r.swallow = d.get("swallow", False)
        r.also_arm = d.get("also_arm", False)
        r.note = d.get("note", "")


def rule_summary(r):
    """One readable sentence describing what a rule does."""
    mods = "+".join(m for m, on in (("Cmd", r.cmd), ("Shift", r.shift),
                                    ("Ctrl", r.ctrl), ("Alt", r.alt)) if on)
    inp = (mods + "+" + r.input_key) if mods else (r.input_key or "?")
    if r.action == 'cycle_axis':
        act = "step through X, Y, Z"
    elif r.action == 'cycle_plane':
        act = "step through XY, XZ, YZ"
    elif r.action == 'send':
        act = "press '%s' for me" % (("Shift+" if r.out_shift else "")
                                     + (r.output_key or "?"))
    elif r.action == 'arm':
        act = "note that a transform started"
    else:
        act = "note that the transform ended"
    out = "%s  ->  %s" % (inp, act)
    if r.when == 'armed':
        out += ", only mid-transform"
    if r.swallow:
        out += ", and hide the key from Blender"
    if r.also_arm:
        out += ", + note transform started"
    return out


# ---------------------------------------------------------------------------
# Rule data
# ---------------------------------------------------------------------------
class CR_Rule(bpy.types.PropertyGroup):
    enabled: bpy.props.BoolProperty(name="On", default=True, update=_on_change)
    note: bpy.props.StringProperty(name="Note", default="")
    input_key: bpy.props.StringProperty(name="Input", default="", update=_on_change)
    cmd: bpy.props.BoolProperty(name="Cmd", update=_on_change)
    shift: bpy.props.BoolProperty(name="Shift", update=_on_change)
    ctrl: bpy.props.BoolProperty(name="Ctrl", update=_on_change)
    alt: bpy.props.BoolProperty(name="Alt", update=_on_change)
    action: bpy.props.EnumProperty(name="Action", items=ACTION_ITEMS,
                                   default='send', update=_on_change)
    output_key: bpy.props.StringProperty(name="Send", default="", update=_on_change)
    out_shift: bpy.props.BoolProperty(name="+Shift", update=_on_change)
    when: bpy.props.EnumProperty(name="When", items=WHEN_ITEMS,
                                 default='always', update=_on_change)
    swallow: bpy.props.BoolProperty(
        name="Hide key from Blender", default=False,
        description=("ON: Blender never sees the key you pressed - use this for "
                     "cycle keys so Tab does not also toggle Edit Mode. "
                     "OFF: the key still does its normal job as well"),
        update=_on_change)
    also_arm: bpy.props.BoolProperty(
        name="Also start transform", update=_on_change,
        description="Additionally mark that a transform is now running")
    also_disarm: bpy.props.BoolProperty(
        name="Also end transform", update=_on_change,
        description="Additionally mark that the transform has finished")


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------
class CR_OT_listen(bpy.types.Operator):
    bl_idname = "cycle_relay.listen"
    bl_label = "Press any key or mouse button"
    index: bpy.props.IntProperty(default=-1)
    target: bpy.props.StringProperty(default="")

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        self.report({'INFO'}, "Press the input you want (Esc to cancel)")
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type in {'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'TIMER',
                          'WINDOW_DEACTIVATE'}:
            return {'RUNNING_MODAL'}
        if event.value != 'PRESS':
            return {'RUNNING_MODAL'}
        if event.type == 'ESC':
            return {'CANCELLED'}
        mod_only = event.type in {'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_CTRL',
                                  'RIGHT_CTRL', 'LEFT_ALT', 'RIGHT_ALT',
                                  'OSKEY'}
        # A bare modifier is a valid cycle key, but not a valid trigger.
        if mod_only and self.target != 'cycle':
            return {'RUNNING_MODAL'}
        prefs = _get_prefs()
        key = _hs_key(event.type)
        if prefs and self.target == 'move':
            prefs.move_input = key
            prefs.move_cmd = event.oskey
            prefs.move_shift = event.shift
            prefs.move_ctrl = event.ctrl
            prefs.move_alt = event.alt
        elif prefs and self.target == 'cycle':
            prefs.cycle_input = key
        elif prefs and 0 <= self.index < len(prefs.rules):
            r = prefs.rules[self.index]
            r.input_key = key
            r.cmd = event.oskey
            r.shift = event.shift
            r.ctrl = event.ctrl
            r.alt = event.alt
        write_config(context)
        self.report({'INFO'}, "Set to %s" % key)
        return {'FINISHED'}


class CR_OT_detect_move(bpy.types.Operator):
    bl_idname = "cycle_relay.detect_move"
    bl_label = "Detect from Blender"
    bl_description = "Reads your Move shortcut out of Blender's keymap"

    def execute(self, context):
        prefs = _get_prefs()
        kc = context.window_manager.keyconfigs.user
        best = None
        for km in kc.keymaps:
            if km.name not in {"3D View", "Object Mode", "Mesh"}:
                continue
            for kmi in km.keymap_items:
                if kmi.idname != "transform.translate" or not kmi.active:
                    continue
                if kmi.value not in {"PRESS", "CLICK", "CLICK_DRAG"}:
                    continue
                score = (kmi.oskey + kmi.ctrl + kmi.alt + kmi.shift)
                if best is None or score > best[0]:
                    best = (score, kmi)
        if best is None:
            self.report({'WARNING'},
                        "No Move shortcut found - set it in Keymap first")
            return {'CANCELLED'}
        kmi = best[1]
        prefs.move_input = _hs_key(kmi.type)
        prefs.move_cmd = kmi.oskey
        prefs.move_shift = kmi.shift
        prefs.move_ctrl = kmi.ctrl
        prefs.move_alt = kmi.alt
        write_config(context)
        self.report({'INFO'}, "Found %s" % prefs.move_input)
        return {'FINISHED'}


class CR_OT_rule_add(bpy.types.Operator):
    bl_idname = "cycle_relay.rule_add"
    bl_label = "Add Rule"

    def execute(self, context):
        prefs = _get_prefs()
        prefs.rules.add()
        write_config(context)
        return {'FINISHED'}


class CR_OT_rule_remove(bpy.types.Operator):
    bl_idname = "cycle_relay.rule_remove"
    bl_label = "Remove"
    index: bpy.props.IntProperty()

    def execute(self, context):
        prefs = _get_prefs()
        if 0 <= self.index < len(prefs.rules):
            prefs.rules.remove(self.index)
            write_config(context)
        return {'FINISHED'}


class CR_OT_defaults(bpy.types.Operator):
    bl_idname = "cycle_relay.defaults"
    bl_label = "Restore Default Rules"

    def execute(self, context):
        prefs = _get_prefs()
        load_defaults(prefs)
        write_config(context)
        self.report({'INFO'}, "Default rules restored")
        return {'FINISHED'}


class CR_OT_copy_log(bpy.types.Operator):
    bl_idname = "cycle_relay.copy_log"
    bl_label = "Copy Log"
    bl_description = "Copies the recent event log to the clipboard"

    def execute(self, context):
        try:
            with open(RECENT_PATH) as f:
                txt = f.read()
        except Exception:
            self.report({'WARNING'}, "No log yet")
            return {'CANCELLED'}
        context.window_manager.clipboard = txt
        self.report({'INFO'}, "Log copied to clipboard")
        return {'FINISHED'}


class CR_OT_setup(bpy.types.Operator):
    bl_idname = "cycle_relay.setup"
    bl_label = "Install / Repair Everything"

    def execute(self, context):
        msgs = []

        def log(m):
            msgs.append(m)
            print("[Cycle Relay]", m)
        if not is_macos():
            self.report({'ERROR'}, "macOS only")
            return {'CANCELLED'}
        ok = step_install_hammerspoon(log)
        step_write_lua(log)
        step_patch_init(log)
        write_config(context)
        step_launch(log)
        prefs = _get_prefs()
        if prefs:
            prefs.last_status = " | ".join(msgs[-3:])
        self.report({'INFO'} if ok else {'WARNING'}, "Setup finished")
        return {'FINISHED'}


class CR_OT_force_reinstall(bpy.types.Operator):
    bl_idname = "cycle_relay.force_reinstall"
    bl_label = "Force Reinstall Hammerspoon"

    def execute(self, context):
        def log(m):
            print("[Cycle Relay]", m)
        ok = step_install_hammerspoon(log, force=True)
        if ok:
            step_write_lua(log)
            step_patch_init(log)
            write_config(context)
            step_launch(log)
        self.report({'INFO'} if ok else {'ERROR'},
                    "Reinstalled" if ok else "Failed - see console")
        return {'FINISHED'}


class CR_OT_restart(bpy.types.Operator):
    bl_idname = "cycle_relay.restart"
    bl_label = "Restart Watcher"

    def execute(self, context):
        def log(m):
            print("[Cycle Relay]", m)
        prefs = _get_prefs()
        if prefs and len(prefs.rules) == 0:
            load_defaults(prefs)
        # Turn auto-launch on: pressing this means you want it running.
        if prefs:
            prefs.auto_launch = True
        step_write_lua(log)
        step_patch_init(log)
        write_config(context)
        step_launch(log)
        self.report({'INFO'}, "Restarted")
        return {'FINISHED'}


class CR_OT_stop(bpy.types.Operator):
    bl_idname = "cycle_relay.stop"
    bl_label = "Stop Watcher"
    bl_description = ("Quits the watcher now. Nothing is intercepted until you "
                      "start it again")

    def execute(self, context):
        prefs = _get_prefs()
        if prefs:
            prefs.auto_launch = False
        quit_hammerspoon(lambda m: print("[Cycle Relay]", m))
        self.report({'INFO'}, "Watcher stopped")
        return {'FINISHED'}


class CR_OT_cleanup(bpy.types.Operator):
    bl_idname = "cycle_relay.cleanup"
    bl_label = "Clean Up Everything"

    def execute(self, context):
        quit_hammerspoon()
        try:
            if os.path.isfile(LUA_PATH):
                os.remove(LUA_PATH)
            if os.path.isfile(INIT_LUA):
                with open(INIT_LUA) as f:
                    t = f.read()
                t = t.replace("\n%s\n%s\n" % (MARKER, REQUIRE_LINE), "\n")
                t = t.replace(MARKER, "").replace(REQUIRE_LINE, "")
                with open(INIT_LUA, "w") as f:
                    f.write(t)
            if os.path.isfile(CONFIG_PATH):
                os.remove(CONFIG_PATH)
        except Exception as e:
            self.report({'ERROR'}, str(e))
            return {'CANCELLED'}
        self.report({'INFO'}, "Cleaned up")
        return {'FINISHED'}


class CR_OT_open_accessibility(bpy.types.Operator):
    bl_idname = "cycle_relay.open_accessibility"
    bl_label = "Open Accessibility Settings"

    def execute(self, context):
        subprocess.Popen(["open", "x-apple.systempreferences:"
                          "com.apple.preference.security?Privacy_Accessibility"])
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------
class CR_Preferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    rules: bpy.props.CollectionProperty(type=CR_Rule)

    move_input: bpy.props.StringProperty(default="leftmouse", update=_on_change)
    move_cmd: bpy.props.BoolProperty(default=True, update=_on_change)
    move_shift: bpy.props.BoolProperty(default=False, update=_on_change)
    move_ctrl: bpy.props.BoolProperty(default=False, update=_on_change)
    move_alt: bpy.props.BoolProperty(default=False, update=_on_change)

    cycle_input: bpy.props.StringProperty(default="tab", update=_on_change)
    move_send_g: bpy.props.BoolProperty(
        name="Blender does not have this shortcut - press G for me",
        default=False,
        description=("Leave OFF if you set this shortcut in Blender Keymap. "
                     "Turn ON only if Blender does not know it"),
        update=_on_change)
    enable_planes: bpy.props.BoolProperty(
        name="Shift + cycle key steps through XY / XZ / YZ",
        default=True, update=_on_change)
    advanced: bpy.props.BoolProperty(
        name="Advanced: edit raw rules", default=False, update=_on_change)
    relay_enabled: bpy.props.BoolProperty(name="Enable relay", default=True,
                                          update=_on_change)
    verbose: bpy.props.BoolProperty(
        name="Verbose logging", default=False,
        description="Log every key seen. Leave off for normal use",
        update=_on_change)
    auto_quit: bpy.props.BoolProperty(
        name="Quit watcher when last Blender closes", default=True,
        update=_on_change)
    auto_launch: bpy.props.BoolProperty(
        name="Start watcher with Blender", default=True)
    mod_tap_key: bpy.props.EnumProperty(
        name="Modifier tap", default='NONE',
        items=[('NONE', "None", ""), ('cmd', "Cmd", ""),
               ('ctrl', "Ctrl", ""), ('alt', "Alt", "")],
        description="Enables rules with input 'modtap:cmd' etc",
        update=_on_change)
    mod_tap_ms: bpy.props.IntProperty(name="Tap window (ms)", default=400,
                                      min=100, max=1000, update=_on_change)
    arm_timeout: bpy.props.IntProperty(
        name="Auto-disarm after (s)", default=30, min=0, max=300,
        description="Forget an unfinished transform after this long. 0 disables",
        update=_on_change)
    show_help: bpy.props.BoolProperty(name="What is arming?", default=False)
    show_rules: bpy.props.BoolProperty(name="Show rules", default=True)
    show_log: bpy.props.BoolProperty(name="Show recent activity", default=False)
    show_setup: bpy.props.BoolProperty(name="Show setup", default=False)
    last_status: bpy.props.StringProperty(default="")

    def draw(self, context):
        layout = self.layout
        if not is_macos():
            layout.label(text="macOS only.", icon='ERROR')
            return

        running = hammerspoon_running()
        head = layout.box()
        hr = head.row(align=True)
        if running:
            hr.label(text="Running", icon='CHECKMARK')
            hr.operator("cycle_relay.stop", text="Turn Off", icon='PAUSE')
        else:
            hr.alert = True
            hr.label(text="Off", icon='PAUSE')
            hr.operator("cycle_relay.restart", text="Turn On", icon='PLAY')

        col = layout.column()
        col.scale_y = 1.2

        b = col.box()
        b.label(text="Shortcut you use to move an object",
                icon='ORIENTATION_GLOBAL')
        r = b.row(align=True)
        r.label(text=combo_text(self.move_input, self.move_cmd, self.move_shift,
                                self.move_ctrl, self.move_alt))
        op = r.operator("cycle_relay.listen", text="Set", icon='REC')
        op.target = 'move'
        r.operator("cycle_relay.detect_move", text="Detect",
                   icon='VIEWZOOM')
        sub = b.column()
        sub.scale_y = 0.75
        sub.label(text="Bind this in Blender Keymap as usual. This just")
        sub.label(text="tells the add-on when cycling should switch on.")
        b.prop(self, "move_send_g")

        b = col.box()
        b.label(text="Key that cycles X / Y / Z", icon='EMPTY_AXIS')
        r = b.row(align=True)
        r.label(text=combo_text(self.cycle_input, False, False, False, False))
        op = r.operator("cycle_relay.listen", text="Set", icon='REC')
        op.target = 'cycle'
        b.prop(self, "enable_planes")

        layout.separator()
        row = layout.row(align=True)
        row.operator("cycle_relay.restart", text="Apply Changes",
                     icon='FILE_REFRESH')
        row.operator("cycle_relay.copy_log", text="Copy Log", icon='COPYDOWN')

        # ---- everything below is optional ----
        box = layout.box()
        box.prop(self, "show_setup", icon='TRIA_DOWN' if self.show_setup
                 else 'TRIA_RIGHT', emboss=False, text="Setup & troubleshooting")
        if self.show_setup:
            app = find_hammerspoon()
            intact = bundle_is_intact(app) if app else False
            box.label(text="Hammerspoon OK" if intact else "Hammerspoon MISSING",
                      icon='CHECKMARK' if intact else 'ERROR')
            box.prop(self, "auto_launch")
            box.prop(self, "auto_quit")
            box.prop(self, "verbose")
            box.operator("cycle_relay.setup", icon='IMPORT')
            r4 = box.row(align=True)
            r4.operator("cycle_relay.force_reinstall", icon='FILE_REFRESH')
            r4.operator("cycle_relay.cleanup", icon='TRASH')
            box.operator("cycle_relay.open_accessibility", icon='PREFERENCES')
            box.label(text="Turn this off before changing Accessibility.",
                      icon='ERROR')
            lines = []
            try:
                with open(RECENT_PATH) as f:
                    lines = f.read().strip().split("\n")[-8:]
            except Exception:
                pass
            c = box.column(align=True)
            c.scale_y = 0.7
            for ln in lines:
                c.label(text=ln)

            box.separator()
            box.prop(self, "advanced")
            if self.advanced:
                box.label(text="Raw rules override the simple settings above.",
                          icon='ERROR')
                for i, r in enumerate(self.rules):
                    rb = box.box()
                    h = rb.row(align=True)
                    h.prop(r, "enabled", text="")
                    h.label(text=rule_summary(r))
                    o = h.operator("cycle_relay.rule_remove", text="", icon='X')
                    o.index = i
                    l1 = rb.row(align=True)
                    l1.prop(r, "input_key", text="")
                    o = l1.operator("cycle_relay.listen", text="", icon='REC')
                    o.index = i
                    m = rb.row(align=True)
                    m.prop(r, "cmd", toggle=True)
                    m.prop(r, "shift", toggle=True)
                    m.prop(r, "ctrl", toggle=True)
                    m.prop(r, "alt", toggle=True)
                    a = rb.row(align=True)
                    a.prop(r, "action", text="")
                    if r.action == 'send':
                        a.prop(r, "output_key", text="")
                    o2 = rb.row(align=True)
                    o2.prop(r, "when", text="")
                    o2.prop(r, "swallow", toggle=True)
                    o2.prop(r, "also_arm", toggle=True)
                rr = box.row(align=True)
                rr.operator("cycle_relay.rule_add", icon='ADD')
                rr.operator("cycle_relay.defaults", icon='LOOP_BACK')
            box.prop(self, "arm_timeout")


classes = (CR_Rule, CR_Preferences, CR_OT_listen, CR_OT_rule_add,
           CR_OT_rule_remove, CR_OT_defaults, CR_OT_copy_log, CR_OT_setup,
           CR_OT_force_reinstall, CR_OT_restart, CR_OT_stop, CR_OT_cleanup,
           CR_OT_detect_move,
           CR_OT_open_accessibility)


def _deferred_start():
    if not is_macos():
        return None

    def log(m):
        print("[Cycle Relay]", m)
    prefs = _get_prefs()
    try:
        if prefs and len(prefs.rules) == 0:
            load_defaults(prefs)
        step_write_lua(log)
        step_patch_init(log)
        write_config(bpy.context)
        # step_launch already quits then relaunches. Never quit without
        # relaunching - that used to leave the watcher dead and silent.
        if prefs and prefs.auto_launch and find_hammerspoon():
            step_launch(log)
        else:
            log("auto-launch is OFF - watcher not started")
    except Exception as e:
        log("startup failed: %s" % e)
    return None


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.app.timers.register(_deferred_start, first_interval=1.0)


def unregister():
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
