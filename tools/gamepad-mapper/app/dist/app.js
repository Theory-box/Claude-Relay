const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

let cfg = null;
let running = false;
let selLayer = "base";
let selBinding = 0;
let selAction = 0;
let selPhase = "on_press";
let selBranch = -1;        // -1 = default branch; >=0 = override index
let learnTarget = "input"; // 'input' or 'override'

const BTN_LABEL = {
  South: "A", East: "B", North: "Y", West: "X",
  LeftTrigger: "LB", RightTrigger: "RB",
  LeftTrigger2: "LT", RightTrigger2: "RT",
  Select: "Back", Start: "Start", Mode: "Guide",
  LeftThumb: "L3", RightThumb: "R3",
  DPadUp: "D-Up", DPadDown: "D-Down", DPadLeft: "D-Left", DPadRight: "D-Right",
};
const BTN_NAMES = Object.keys(BTN_LABEL);

const CODE_KEY = {
  Space: "space", Enter: "return", Tab: "tab", Escape: "escape",
  Backspace: "backspace", Delete: "forwarddelete",
  ArrowUp: "up", ArrowDown: "down", ArrowLeft: "left", ArrowRight: "right",
  Home: "home", End: "end", PageUp: "pageup", PageDown: "pagedown",
  Minus: "minus", Equal: "equals", Comma: "comma", Period: "period",
  Slash: "slash", Semicolon: "semicolon", Quote: "quote",
  BracketLeft: "leftbracket", BracketRight: "rightbracket",
  Backslash: "backslash", Backquote: "grave",
};
function codeToKey(code) {
  if (CODE_KEY[code]) return CODE_KEY[code];
  let m = code.match(/^Key([A-Z])$/);
  if (m) return m[1].toLowerCase();
  m = code.match(/^Digit(\d)$/);
  if (m) return m[1];
  m = code.match(/^(F\d{1,2})$/);
  if (m) return m[1].toLowerCase();
  return null;
}

function $(id) { return document.getElementById(id); }
function getPath(obj, path) { return path.split(".").reduce((o, k) => o && o[k], obj); }
function setPath(obj, path, val) {
  const ks = path.split(".");
  let o = obj;
  for (let i = 0; i < ks.length - 1; i++) o = o[ks[i]];
  o[ks[ks.length - 1]] = val;
}

async function pushConfig() {
  try { await invoke("set_config", { json: JSON.stringify(cfg) }); }
  catch (e) { $("status").textContent = "CONFIG ERROR: " + e; console.error(e); }
}

function layer() { return cfg.layers.find((l) => l.name === selLayer); }
function binding() { const l = layer(); return l && l.bindings[selBinding]; }
function branchContainer(b) {
  if (!b) return null;
  if (!b.overrides) b.overrides = [];
  if (selBranch >= 0 && selBranch < b.overrides.length) return b.overrides[selBranch];
  return b; // default branch
}
function phaseList(b) {
  const c = branchContainer(b);
  if (!c) return null;
  if (!c.on_press) c.on_press = [];
  if (!c.on_release) c.on_release = [];
  return c[selPhase];
}
function action() { const l = phaseList(binding()); return l && l[selAction]; }

function inputLabel(inp) {
  return inp.label || BTN_LABEL[inp.name] || inp.name || "(unset)";
}
function evtTag(a) { return a.event && a.event !== "tap" ? " (" + a.event + ")" : ""; }
function actionLabel(a) {
  switch (a.type) {
    case "key": return "key " + (a.mods || []).map((m) => m + "+").join("") + a.key + evtTag(a);
    case "mouse": return a.button + " click" + evtTag(a);
    case "scroll": return "scroll " + a.amount;
    case "modifier": return "hold " + a.mod;
    case "enter_layer": return "enter '" + a.layer + "' (" + a.mode + ")";
    case "exit_layer": return "exit layer";
    case "precision": return "slow cursor " + Math.round((a.factor || 0.3) * 100) + "%";
    case "cursor": return "cursor " + (a.mode || "toggle");
  }
  return a.type;
}

function renderLayers() {
  const ul = $("layers");
  ul.innerHTML = "";
  cfg.layers.forEach((l) => {
    const li = document.createElement("li");
    li.textContent = l.name;
    if (l.name === selLayer) li.className = "sel";
    li.onclick = () => { selLayer = l.name; selBinding = 0; selBranch = -1; selAction = 0; renderBindings(); renderLayers(); };
    ul.appendChild(li);
  });
}

function renderBindings() {
  const ul = $("bindings");
  ul.innerHTML = "";
  const l = layer();
  if (l) l.bindings.forEach((b, i) => {
    const li = document.createElement("li");
    if (!b.on_release) b.on_release = [];
    const press = b.on_press.map(actionLabel).join(" + ") || "(none)";
    const rel = b.on_release.length ? "  ⤴ " + b.on_release.map(actionLabel).join(" + ") : "";
    const ovr = (b.overrides && b.overrides.length) ? "  [+" + b.overrides.length + " override" + (b.overrides.length > 1 ? "s" : "") + "]" : "";
    li.textContent = inputLabel(b.input) + " → " + press + rel + ovr;
    if (i === selBinding) li.className = "sel";
    li.onclick = () => { selBinding = i; selBranch = -1; selPhase = "on_press"; selAction = 0; renderActions(); renderBindings(); };
    ul.appendChild(li);
  });
  renderActions();
}

function renderActions() {
  const ul = $("actions");
  ul.innerHTML = "";
  const b = binding();
  if (b && !b.overrides) b.overrides = [];

  const btabs = $("branchTabs");
  if (btabs) {
    btabs.innerHTML = "";
    if (b) {
      const mk = (idx, label) => {
        const t = document.createElement("button");
        t.textContent = label;
        t.className = "branchtab" + (selBranch === idx ? " sel" : "");
        t.onclick = () => { selBranch = idx; selPhase = "on_press"; selAction = 0; renderActions(); renderFields(); };
        btabs.appendChild(t);
      };
      mk(-1, "Default");
      b.overrides.forEach((ov, i) => mk(i, "When " + (ov.when_label || ov.when)));
      const add = document.createElement("button");
      add.textContent = "+ override";
      add.className = "branchtab add";
      add.onclick = () => startLearnOverride();
      btabs.appendChild(add);
      if (selBranch >= 0 && selBranch < b.overrides.length) {
        const rm = document.createElement("button");
        rm.textContent = "− remove";
        rm.className = "branchtab";
        rm.onclick = () => {
          b.overrides.splice(selBranch, 1); selBranch = -1; selAction = 0;
          renderActions(); renderBindings(); pushConfig();
        };
        btabs.appendChild(rm);
      }
    }
  }

  const tabs = $("phaseTabs");
  if (tabs) {
    tabs.innerHTML = "";
    const cont = branchContainer(b);
    [["on_press", "On Press (button down)"], ["on_release", "On Release (button up)"]].forEach(([ph, lbl]) => {
      const t = document.createElement("button");
      const n = cont && cont[ph] ? cont[ph].length : 0;
      t.textContent = lbl + (n ? " (" + n + ")" : "");
      t.className = "phasetab" + (selPhase === ph ? " sel" : "");
      t.onclick = () => { selPhase = ph; selAction = 0; renderActions(); renderFields(); };
      tabs.appendChild(t);
    });
  }

  const list = phaseList(b);
  if (list) list.forEach((a, i) => {
    const li = document.createElement("li");
    li.textContent = actionLabel(a);
    if (i === selAction) li.className = "sel";
    li.onclick = () => { selAction = i; renderActions(); renderFields(); };
    ul.appendChild(li);
  });
  renderFields();
}

function frow() { const d = document.createElement("div"); d.className = "frow"; return d; }

function renderFields() {
  const box = $("fields");
  box.innerHTML = "";
  const a = action();
  if (!a) return;
  const changed = () => { renderActions(); renderBindings(); pushConfig(); };

  if (a.type === "key") {
    const r = frow();
    const inp = document.createElement("input");
    inp.type = "text"; inp.value = a.key || ""; inp.placeholder = "key";
    inp.oninput = () => { a.key = inp.value; changed(); };
    r.append("key ", inp);
    ["cmd", "shift", "ctrl", "alt"].forEach((m) => {
      const lab = document.createElement("label");
      const c = document.createElement("input"); c.type = "checkbox";
      c.checked = (a.mods || []).includes(m);
      c.onchange = () => {
        a.mods = a.mods || [];
        if (c.checked) { if (!a.mods.includes(m)) a.mods.push(m); }
        else a.mods = a.mods.filter((x) => x !== m);
        changed();
      };
      lab.append(c, m); r.append(lab);
    });
    box.append(r);
    box.append(eventRow(a, changed));
    box.append(learnOutBtn(a, changed));
  } else if (a.type === "mouse") {
    const r = frow();
    const sel = document.createElement("select");
    ["left", "right", "middle"].forEach((o) => sel.add(new Option(o, o)));
    sel.value = a.button || "left";
    sel.onchange = () => { a.button = sel.value; changed(); };
    r.append("button ", sel);
    box.append(r, eventRow(a, changed));
  } else if (a.type === "scroll") {
    const r = frow();
    const inp = document.createElement("input"); inp.type = "number"; inp.value = a.amount ?? 1;
    inp.onchange = () => { a.amount = parseInt(inp.value) || 0; changed(); };
    r.append("amount ", inp); box.append(r);
  } else if (a.type === "modifier") {
    const r = frow();
    const sel = document.createElement("select");
    ["shift", "ctrl", "alt", "cmd"].forEach((o) => sel.add(new Option(o, o)));
    sel.value = a.mod || "shift";
    sel.onchange = () => { a.mod = sel.value; changed(); };
    r.append("modifier ", sel); box.append(r);
  } else if (a.type === "precision") {
    const r = frow();
    const inp = document.createElement("input"); inp.type = "number"; inp.min = 5; inp.max = 100; inp.step = 5;
    inp.value = Math.round((a.factor ?? 0.3) * 100);
    inp.onchange = () => { let p = parseInt(inp.value); if (isNaN(p)) p = 30; a.factor = Math.min(100, Math.max(5, p)) / 100; changed(); };
    r.append("cursor speed % while held ", inp); box.append(r);
  } else if (a.type === "cursor") {
    const r = frow();
    const sel = document.createElement("select");
    [["toggle", "toggle on/off"], ["off", "turn off"], ["on", "turn on"]]
      .forEach(([v, t]) => sel.add(new Option(t, v)));
    sel.value = a.mode || "toggle";
    sel.onchange = () => { a.mode = sel.value; changed(); };
    r.append("stick cursor ", sel); box.append(r);
  } else if (a.type === "enter_layer") {
    const r = frow();
    const sel = document.createElement("select");
    cfg.layers.forEach((l) => sel.add(new Option(l.name, l.name)));
    sel.value = a.layer || cfg.layers[0].name;
    sel.onchange = () => { a.layer = sel.value; changed(); };
    const r2 = frow();
    const mo = document.createElement("select");
    ["momentary", "latched", "toggle"].forEach((o) => mo.add(new Option(o, o)));
    mo.value = a.mode || "momentary";
    mo.onchange = () => { a.mode = mo.value; changed(); };
    r.append("layer ", sel); r2.append("mode ", mo);
    box.append(r, r2);
  }
}

function eventRow(a, changed) {
  if (!a.event) a.event = "tap";
  const r = frow();
  const sel = document.createElement("select");
  [["tap", "click (down+up)"], ["down", "button down only"], ["up", "button up only"]]
    .forEach(([v, t]) => sel.add(new Option(t, v)));
  sel.value = a.event;
  sel.onchange = () => { a.event = sel.value; changed(); };
  r.append("event ", sel);
  return r;
}

function learnOutBtn(a, changed) {
  const btn = document.createElement("button");
  btn.textContent = "Learn output (press a key)";
  btn.onclick = () => {
    btn.textContent = "press a key...";
    const h = (e) => {
      e.preventDefault();
      const k = codeToKey(e.code);
      window.removeEventListener("keydown", h, true);
      btn.textContent = "Learn output (press a key)";
      if (!k) return;
      a.key = k;
      a.mods = [];
      if (e.shiftKey) a.mods.push("shift");
      if (e.ctrlKey) a.mods.push("ctrl");
      if (e.altKey) a.mods.push("alt");
      if (e.metaKey) a.mods.push("cmd");
      changed();
    };
    window.addEventListener("keydown", h, true);
  };
  return btn;
}

// --- structural edits ---
function uniqueLayerName(base) {
  let n = base, i = 1;
  while (cfg.layers.find((l) => l.name === n)) { i++; n = base + i; }
  return n;
}
$("addLayer").onclick = () => {
  let n = ($("layerName").value || "").trim();
  if (!n) n = uniqueLayerName("layer");
  if (cfg.layers.find((l) => l.name === n)) { $("status").textContent = "layer '" + n + "' already exists"; return; }
  cfg.layers.push({ name: n, bindings: [] });
  selLayer = n; selBinding = 0; selAction = 0;
  $("layerName").value = "";
  renderLayers(); renderBindings(); pushConfig();
};
$("renLayer").onclick = () => {
  if (selLayer === "base") { $("status").textContent = "the base layer can't be renamed"; return; }
  const n = ($("layerName").value || "").trim();
  if (!n) { $("status").textContent = "type a new name in the box first"; return; }
  if (cfg.layers.find((l) => l.name === n)) { $("status").textContent = "layer '" + n + "' already exists"; return; }
  const old = selLayer;
  layer().name = n;
  // keep any enter_layer/exit_layer actions pointing at the renamed layer
  cfg.layers.forEach((l) => l.bindings.forEach((b) => {
    [].concat(b.on_press || [], b.on_release || []).forEach((a) => {
      if ((a.type === "enter_layer" || a.type === "exit_layer") && a.layer === old) a.layer = n;
    });
  }));
  selLayer = n; $("layerName").value = "";
  renderLayers(); renderBindings(); pushConfig();
};
$("delLayer").onclick = () => {
  if (selLayer === "base") { $("status").textContent = "the base layer can't be deleted"; return; }
  cfg.layers = cfg.layers.filter((l) => l.name !== selLayer);
  selLayer = "base"; selBinding = 0; selAction = 0;
  renderLayers(); renderBindings(); pushConfig();
};
$("addBinding").onclick = () => {
  const l = layer(); if (!l) return;
  l.bindings.push({ input: { kind: "button", name: "", label: "unset — Learn input" }, on_press: [], on_release: [] });
  selBinding = l.bindings.length - 1; selBranch = -1; selAction = 0; renderBindings(); pushConfig();
};
$("delBinding").onclick = () => {
  const l = layer(); if (!l || !l.bindings.length) return;
  l.bindings.splice(selBinding, 1); selBinding = 0; selBranch = -1; selAction = 0; renderBindings(); pushConfig();
};
$("learnInput").onclick = () => { learnTarget = "input"; $("status").textContent = "press a control..."; invoke("learn_next"); };
function startLearnOverride() {
  if (!binding()) return;
  learnTarget = "override";
  $("status").textContent = "press the control to use as the override condition...";
  invoke("learn_next");
}
function stripDir(code) { return code.replace(/[+-]$/, ""); }
function renderScrollAxes() {
  if ($("scrollYName")) $("scrollYName").textContent = (cfg.scroll && cfg.scroll.axis_y) || "(none)";
  if ($("scrollXName")) $("scrollXName").textContent = (cfg.scroll && cfg.scroll.axis_x) || "(none)";
}
$("learnScrollY").onclick = () => { learnTarget = "scroll_y"; $("status").textContent = "push the stick UP or DOWN..."; invoke("learn_next"); };
$("learnScrollX").onclick = () => { learnTarget = "scroll_x"; $("status").textContent = "push the stick LEFT or RIGHT..."; invoke("learn_next"); };
function renderPrecAxis() {
  if ($("precAxisName")) {
    const pa = cfg.precision_axis;
    $("precAxisName").textContent = pa && pa.axis ? (pa.axis + (pa.sign === "NEG" ? "-" : "+")) : "(none)";
  }
}
$("learnPrec").onclick = () => { learnTarget = "precision"; $("status").textContent = "pull the trigger you want for slow-down..."; invoke("learn_next"); };

$("addAction").onclick = () => {
  const b = binding(); if (!b) return;
  const list = phaseList(b);
  const t = $("actionType").value;
  const a = { type: t };
  if (t === "key") Object.assign(a, { key: "g", mods: [], event: "tap" });
  if (t === "mouse") Object.assign(a, { button: "left", event: "tap" });
  if (t === "scroll") Object.assign(a, { amount: 1 });
  if (t === "modifier") Object.assign(a, { mod: "shift" });
  if (t === "enter_layer") Object.assign(a, { layer: cfg.layers[0].name, mode: "momentary" });
  if (t === "precision") Object.assign(a, { factor: 0.3 });
  if (t === "cursor") Object.assign(a, { mode: "toggle" });
  list.push(a); selAction = list.length - 1; renderActions(); renderBindings(); pushConfig();
};
$("delAction").onclick = () => {
  const b = binding(); const list = phaseList(b);
  if (!list || !list.length) return;
  list.splice(selAction, 1); selAction = 0; renderActions(); renderBindings(); pushConfig();
};

$("run").onclick = async () => {
  running = !running;
  await pushConfig();
  await invoke("set_running", { on: running });
  $("run").textContent = running ? "Stop" : "Start";
  $("run").className = running ? "running" : "primary";
};
$("save").onclick = async () => { await pushConfig(); $("status").textContent = "saved"; };
$("grant").onclick = async () => {
  const ok = await invoke("request_accessibility");
  $("status").textContent = ok
    ? "Accessibility granted"
    : "enable in System Settings > Privacy & Security > Accessibility, then restart the app";
};
$("copylog").onclick = () => {
  const log =
    "=== Gamepad Mapper log ===\n" +
    "status: " + JSON.stringify(lastStatus, null, 2) + "\n\n" +
    "config: " + JSON.stringify(cfg, null, 2);
  const done = () => { $("status").textContent = "log copied — paste it to share"; };
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(log).then(done).catch(() => fallbackCopy(log, done));
  } else {
    fallbackCopy(log, done);
  }
};
function fallbackCopy(text, done) {
  const ta = document.createElement("textarea");
  ta.value = text;
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); done(); } catch (_) {}
  document.body.removeChild(ta);
}

// settings bindings
document.querySelectorAll("#settings [data-path]").forEach((el) => {
  const path = el.dataset.path;
  el.addEventListener("change", () => {
    if (el.type === "checkbox") setPath(cfg, path, el.checked);
    else { const v = parseFloat(el.value); if (!isNaN(v)) setPath(cfg, path, v); }
    pushConfig();
  });
});
function fillSettings() {
  renderScrollAxes();
  renderPrecAxis();
  document.querySelectorAll("#settings [data-path]").forEach((el) => {
    const v = getPath(cfg, el.dataset.path);
    if (el.type === "checkbox") el.checked = !!v; else el.value = v;
  });
}

let lastStatus = {};
listen("status", (e) => {
  try {
    const s = JSON.parse(e.payload);
    lastStatus = s;
    if (!document.activeElement || document.activeElement.tagName !== "INPUT")
      $("status").textContent = (s.running ? "running" : "stopped") + " | " + s.controller + " | " + (s.layers || []).join(" > ");
    const ax = s.axes || {};
    const f = (k) => (ax[k] !== undefined ? ax[k].toFixed(2) : "-");
    $("diag").textContent =
      "Accessibility: " + (s.trusted ? "YES" : "NO") +
      "   pressed: [" + (s.pressed || []).join(", ") + "]" +
      "   mods: [" + (s.mods || []).join(", ") + "]" +
      "   LX " + f("LeftStickX") + " LY " + f("LeftStickY") +
      "   engine: " + (s.eng || "") +
      "   cursor: " + (s.cursor_on === false ? "PAUSED" : "on") +
      "   debounce: " + (s.debounce_ms ?? "-") + "ms" +
      "   fired: " + (s.fired || "-");
    const tr = $("trace");
    if (tr) tr.textContent = "trace: " + (s.trace || []).slice(-12).join("   ");
  } catch (_) {}
});
listen("learned", (e) => {
  let code, label;
  try { const p = JSON.parse(e.payload); code = p.code; label = p.label; }
  catch (_) { code = e.payload; label = e.payload; }
  if (learnTarget === "precision") {
    learnTarget = "input";
    if (!cfg.precision_axis) cfg.precision_axis = { enabled: true, axis: "", sign: "POS", factor: 0.3 };
    cfg.precision_axis.sign = code.endsWith("-") ? "NEG" : "POS";
    cfg.precision_axis.axis = stripDir(code);
    cfg.precision_axis.enabled = true;
    fillSettings(); pushConfig();
    $("status").textContent = "slow-down trigger set: " + cfg.precision_axis.axis;
    return;
  }
  if (learnTarget === "scroll_y" || learnTarget === "scroll_x") {
    const which = learnTarget; learnTarget = "input";
    if (!cfg.scroll) cfg.scroll = { enabled: false, axis_x: "", axis_y: "", speed: 800, invert_x: false, invert_y: false };
    const axis = stripDir(code);
    if (which === "scroll_y") cfg.scroll.axis_y = axis; else cfg.scroll.axis_x = axis;
    renderScrollAxes(); pushConfig();
    $("status").textContent = "scroll axis set: " + axis;
    return;
  }
  const b = binding();
  if (!b) return;
  if (learnTarget === "override") {
    learnTarget = "input";
    if (!b.overrides) b.overrides = [];
    b.overrides.push({ when: code, when_label: label, on_press: [], on_release: [] });
    selBranch = b.overrides.length - 1; selPhase = "on_press"; selAction = 0;
    renderActions(); renderBindings(); pushConfig();
    $("status").textContent = "override when: " + (label || code);
    return;
  }
  b.input = { kind: "button", name: code, label: label };
  renderBindings(); pushConfig();
  $("status").textContent = "learned: " + (label || code);
});

async function init() {
  cfg = JSON.parse(await invoke("get_config"));
  fillSettings();
  renderLayers();
  renderBindings();
}
init();
