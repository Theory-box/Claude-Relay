const { invoke } = window.__TAURI__.core;
const { listen } = window.__TAURI__.event;

let cfg = null;
let running = false;
let selLayer = "base";
let selBinding = 0;
let selAction = 0;

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
  try { await invoke("set_config", { json: JSON.stringify(cfg) }); } catch (e) { console.error(e); }
}

function layer() { return cfg.layers.find((l) => l.name === selLayer); }
function binding() { const l = layer(); return l && l.bindings[selBinding]; }
function action() { const b = binding(); return b && b.on_press[selAction]; }

function inputLabel(inp) {
  return (BTN_LABEL[inp.name] || inp.name);
}
function actionLabel(a) {
  switch (a.type) {
    case "key": return "key " + (a.mods || []).map((m) => m + "+").join("") + a.key + (a.hold ? " (hold)" : "");
    case "mouse": return a.button + " click" + (a.hold ? " (hold)" : "");
    case "scroll": return "scroll " + a.amount;
    case "modifier": return "hold " + a.mod;
    case "enter_layer": return "enter '" + a.layer + "' (" + a.mode + ")";
    case "exit_layer": return "exit layer";
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
    li.onclick = () => { selLayer = l.name; selBinding = 0; selAction = 0; renderBindings(); renderLayers(); };
    ul.appendChild(li);
  });
}

function renderBindings() {
  const ul = $("bindings");
  ul.innerHTML = "";
  const l = layer();
  if (l) l.bindings.forEach((b, i) => {
    const li = document.createElement("li");
    const acts = b.on_press.map(actionLabel).join(" + ") || "(empty)";
    li.textContent = inputLabel(b.input) + " → " + acts;
    if (i === selBinding) li.className = "sel";
    li.onclick = () => { selBinding = i; selAction = 0; renderActions(); renderBindings(); };
    ul.appendChild(li);
  });
  renderActions();
}

function renderActions() {
  const ul = $("actions");
  ul.innerHTML = "";
  const b = binding();
  if (b) b.on_press.forEach((a, i) => {
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
    box.append(holdRow(a, changed));
    box.append(learnOutBtn(a, changed));
  } else if (a.type === "mouse") {
    const r = frow();
    const sel = document.createElement("select");
    ["left", "right", "middle"].forEach((o) => sel.add(new Option(o, o)));
    sel.value = a.button || "left";
    sel.onchange = () => { a.button = sel.value; changed(); };
    r.append("button ", sel);
    box.append(r, holdRow(a, changed));
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

function holdRow(a, changed) {
  const lab = document.createElement("label");
  const c = document.createElement("input"); c.type = "checkbox"; c.checked = !!a.hold;
  c.onchange = () => { a.hold = c.checked; changed(); };
  lab.append(c, "hold (vs tap)");
  const r = frow(); r.append(lab); return r;
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
$("addLayer").onclick = () => {
  const n = prompt("Layer name:");
  if (n && !cfg.layers.find((l) => l.name === n)) { cfg.layers.push({ name: n, bindings: [] }); selLayer = n; renderLayers(); renderBindings(); pushConfig(); }
};
$("delLayer").onclick = () => {
  if (selLayer === "base") return alert("Can't delete base layer.");
  cfg.layers = cfg.layers.filter((l) => l.name !== selLayer);
  selLayer = "base"; renderLayers(); renderBindings(); pushConfig();
};
$("renLayer").onclick = () => {
  if (selLayer === "base") return;
  const n = prompt("New name:", selLayer);
  if (n && !cfg.layers.find((l) => l.name === n)) { layer().name = n; selLayer = n; renderLayers(); renderBindings(); pushConfig(); }
};
$("addBinding").onclick = () => {
  const l = layer(); if (!l) return;
  l.bindings.push({ input: { kind: "button", name: "South" }, on_press: [] });
  selBinding = l.bindings.length - 1; renderBindings(); pushConfig();
};
$("delBinding").onclick = () => {
  const l = layer(); if (!l || !l.bindings.length) return;
  l.bindings.splice(selBinding, 1); selBinding = 0; renderBindings(); pushConfig();
};
$("learnInput").onclick = () => { $("status").textContent = "press a control..."; invoke("learn_next"); };

$("addAction").onclick = () => {
  const b = binding(); if (!b) return;
  const t = $("actionType").value;
  const a = { type: t };
  if (t === "key") Object.assign(a, { key: "g", mods: [], hold: false });
  if (t === "mouse") Object.assign(a, { button: "left", hold: false });
  if (t === "scroll") Object.assign(a, { amount: 1 });
  if (t === "modifier") Object.assign(a, { mod: "shift" });
  if (t === "enter_layer") Object.assign(a, { layer: cfg.layers[0].name, mode: "momentary" });
  b.on_press.push(a); selAction = b.on_press.length - 1; renderActions(); renderBindings(); pushConfig();
};
$("delAction").onclick = () => {
  const b = binding(); if (!b || !b.on_press.length) return;
  b.on_press.splice(selAction, 1); selAction = 0; renderActions(); renderBindings(); pushConfig();
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

// settings bindings
document.querySelectorAll("#settings [data-path]").forEach((el) => {
  const path = el.dataset.path;
  el.addEventListener("change", () => {
    if (el.type === "checkbox") setPath(cfg, path, el.checked);
    else setPath(cfg, path, parseFloat(el.value));
    pushConfig();
  });
});
function fillSettings() {
  document.querySelectorAll("#settings [data-path]").forEach((el) => {
    const v = getPath(cfg, el.dataset.path);
    if (el.type === "checkbox") el.checked = !!v; else el.value = v;
  });
}

listen("status", (e) => {
  try {
    const s = JSON.parse(e.payload);
    if (!document.activeElement || document.activeElement.tagName !== "INPUT")
      $("status").textContent = (s.running ? "running" : "stopped") + " | " + s.controller + " | " + (s.layers || []).join(" > ");
    const ax = s.axes || {};
    const f = (k) => (ax[k] !== undefined ? ax[k].toFixed(2) : "-");
    $("diag").textContent =
      "Accessibility: " + (s.trusted ? "YES" : "NO") +
      "   pressed: [" + (s.pressed || []).join(", ") + "]" +
      "   LX " + f("LeftStickX") + " LY " + f("LeftStickY") +
      "  RX " + f("RightStickX") + " RY " + f("RightStickY") +
      "  LT " + f("LeftZ") + " RT " + f("RightZ");
  } catch (_) {}
});
listen("learned", (e) => {
  const b = binding();
  if (b) { b.input = { kind: "button", name: e.payload }; renderBindings(); pushConfig(); }
  $("status").textContent = "learned: " + e.payload;
});

async function init() {
  cfg = JSON.parse(await invoke("get_config"));
  fillSettings();
  renderLayers();
  renderBindings();
}
init();
