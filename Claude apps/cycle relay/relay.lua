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
