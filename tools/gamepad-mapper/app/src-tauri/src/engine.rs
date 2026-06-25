use serde::{Deserialize, Serialize};
use std::collections::{HashMap, HashSet};

pub const MOD_SHIFT: u64 = 0x20000;
pub const MOD_CTRL: u64 = 0x40000;
pub const MOD_ALT: u64 = 0x80000;
pub const MOD_CMD: u64 = 0x100000;

pub fn mod_flag(name: &str) -> u64 {
    match name {
        "shift" => MOD_SHIFT,
        "ctrl" => MOD_CTRL,
        "alt" => MOD_ALT,
        "cmd" => MOD_CMD,
        _ => 0,
    }
}

fn def_left() -> String { "left".to_string() }
fn def_precision() -> f64 { 0.3 }
fn def_tap() -> String { "tap".to_string() }
fn def_toggle() -> String { "toggle".to_string() }

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Cursor {
    pub enabled: bool,
    pub axis_x: String,
    pub axis_y: String,
    pub speed: f64,
    pub curve: f64,
    pub invert_y: bool,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct ScrollStick {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub axis_x: String,
    #[serde(default)]
    pub axis_y: String,
    #[serde(default = "def_scroll_speed")]
    pub speed: f64,
    #[serde(default)]
    pub invert_x: bool,
    #[serde(default)]
    pub invert_y: bool,
}

fn def_scroll_speed() -> f64 { 800.0 }
fn def_scrollstick() -> ScrollStick {
    ScrollStick {
        enabled: false,
        axis_x: String::new(),
        axis_y: String::new(),
        speed: 800.0,
        invert_x: false,
        invert_y: false,
    }
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Input {
    pub kind: String, // "button"
    pub name: String, // raw hardware code (stable per device)
    #[serde(default)]
    pub label: String, // friendly label for display
}

#[derive(Serialize, Deserialize, Clone, Debug)]
#[serde(tag = "type")]
pub enum Action {
    #[serde(rename = "key")]
    Key { key: String, #[serde(default)] mods: Vec<String>, #[serde(default = "def_tap")] event: String },
    #[serde(rename = "mouse")]
    Mouse { #[serde(default = "def_left")] button: String, #[serde(default = "def_tap")] event: String },
    #[serde(rename = "scroll")]
    Scroll { amount: i32 },
    #[serde(rename = "modifier")]
    Modifier { #[serde(rename = "mod")] modname: String },
    #[serde(rename = "enter_layer")]
    EnterLayer { layer: String, mode: String },
    #[serde(rename = "exit_layer")]
    ExitLayer { #[serde(default)] layer: Option<String> },
    #[serde(rename = "precision")]
    Precision { #[serde(default = "def_precision")] factor: f64, #[serde(default)] pressure: bool },
    #[serde(rename = "cursor")]
    Cursor { #[serde(default = "def_toggle")] mode: String },
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Override {
    pub when: String,
    #[serde(default)]
    pub when_label: String,
    #[serde(default)]
    pub on_press: Vec<Action>,
    #[serde(default)]
    pub on_release: Vec<Action>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Binding {
    pub input: Input,
    #[serde(default)]
    pub on_press: Vec<Action>,
    #[serde(default)]
    pub on_release: Vec<Action>,
    #[serde(default)]
    pub overrides: Vec<Override>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Layer {
    pub name: String,
    #[serde(default)]
    pub bindings: Vec<Binding>,
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Config {
    pub deadzone: f64,
    pub cursor: Cursor,
    #[serde(default = "def_scrollstick")]
    pub scroll: ScrollStick,
    pub layers: Vec<Layer>,
    #[serde(default = "def_debounce")]
    pub release_debounce_ms: f64,
}

fn def_debounce() -> f64 { 60.0 }

pub fn default_config() -> Config {
    Config {
        deadzone: 0.12,
        cursor: Cursor {
            enabled: true,
            axis_x: "LeftStickX".into(),
            axis_y: "LeftStickY".into(),
            speed: 1100.0,
            curve: 2.0,
            invert_y: false,
        },
        scroll: def_scrollstick(),
        layers: vec![
            Layer { name: "base".into(), bindings: vec![] },
            Layer { name: "alt".into(), bindings: vec![] },
        ],
        release_debounce_ms: 60.0,
    }
}

pub struct InputState {
    pub pressed: HashSet<String>,
    pub axes: HashMap<String, f64>,
}

pub trait Out {
    fn key(&mut self, key: &str, flags: u64, down: bool);
    fn key_tap(&mut self, key: &str, flags: u64);
    fn mouse(&mut self, button: &str, down: bool, flags: u64);
    fn mouse_tap(&mut self, button: &str, flags: u64);
    fn scroll(&mut self, dx: i32, dy: i32);
    fn move_cursor(&mut self, dx: f64, dy: f64, held: Option<&str>);
}

enum Revert {
    PopLayer(String),
    ClearMod(String, String),
    ClearPrecision(String),
    KeyUp(String, u64),
    MouseUp(String, u64),
}

pub struct Engine {
    pub cfg: Config,
    pub stack: Vec<String>,
    prev: HashSet<String>,
    reverts: HashMap<String, Vec<Revert>>,
    mods: HashMap<String, u64>,
    precision: HashMap<String, f64>,
    held_mouse: Option<String>,
    held_keys: HashMap<String, u64>,
    release_timer: HashMap<String, f64>,
    cursor_paused: bool,
    active_branch: HashMap<String, i32>,
    scroll_acc_x: f64,
    scroll_acc_y: f64,
    axis_base: HashMap<String, f64>,
}

fn deadzone(v: f64, d: f64) -> f64 {
    if v.abs() < d {
        0.0
    } else {
        let s = (v.abs() - d) / (1.0 - d);
        if v > 0.0 { s } else { -s }
    }
}

fn curve(v: f64, c: f64) -> f64 {
    (if v >= 0.0 { 1.0 } else { -1.0 }) * v.abs().powf(c)
}

impl Engine {
    pub fn new(cfg: Config) -> Self {
        Engine {
            cfg,
            stack: vec!["base".into()],
            prev: HashSet::new(),
            reverts: HashMap::new(),
            mods: HashMap::new(),
            precision: HashMap::new(),
            held_mouse: None,
            held_keys: HashMap::new(),
            release_timer: HashMap::new(),
            cursor_paused: false,
            active_branch: HashMap::new(),
            scroll_acc_x: 0.0,
            scroll_acc_y: 0.0,
            axis_base: HashMap::new(),
        }
    }

    pub fn set_config(&mut self, cfg: Config) {
        self.cfg = cfg;
        self.stack = vec!["base".into()];
        self.prev.clear();
        self.reverts.clear();
        self.mods.clear();
        self.precision.clear();
        self.held_mouse = None;
        self.held_keys.clear();
        self.release_timer.clear();
        self.active_branch.clear();
    }

    pub fn release_all(&mut self, out: &mut dyn Out) {
        let keys: Vec<String> = self.reverts.keys().cloned().collect();
        for k in keys {
            if let Some(revs) = self.reverts.remove(&k) {
                for r in revs.into_iter().rev() {
                    self.apply_revert(r, out);
                }
            }
        }
        let hk: Vec<(String, u64)> = self.held_keys.drain().collect();
        for (k, f) in hk {
            out.key(&k, f, false);
        }
        if let Some(b) = self.held_mouse.take() {
            out.mouse(&b, false, 0);
        }
        // safety: make sure no modifier key is left held
        for m in ["shift", "ctrl", "alt", "cmd"] {
            out.key(m, 0, false);
        }
        self.prev.clear();
        self.release_timer.clear();
        self.active_branch.clear();
    }

    fn cur_mods(&self) -> u64 {
        self.mods.values().fold(0, |a, b| a | b)
    }

    pub fn cursor_active(&self) -> bool {
        self.cfg.cursor.enabled && !self.cursor_paused
    }

    pub fn active_mods(&self) -> Vec<String> {
        let f = self.cur_mods();
        let mut v = Vec::new();
        if f & MOD_SHIFT != 0 { v.push("shift".to_string()); }
        if f & MOD_CTRL != 0 { v.push("ctrl".to_string()); }
        if f & MOD_ALT != 0 { v.push("alt".to_string()); }
        if f & MOD_CMD != 0 { v.push("cmd".to_string()); }
        v
    }

    fn resolve(&self, name: &str) -> Option<Binding> {
        for lname in self.stack.iter().rev() {
            if let Some(layer) = self.cfg.layers.iter().find(|l| &l.name == lname) {
                for b in &layer.bindings {
                    if b.input.name == name {
                        return Some(b.clone());
                    }
                }
            }
        }
        None
    }

    pub fn tick(&mut self, st: &InputState, dt: f64, out: &mut dyn Out) {
        // capture each axis's resting value once (first sample, controller at rest)
        for (k, v) in &st.axes {
            self.axis_base.entry(k.clone()).or_insert(*v);
        }

        // cursor slow-down multiplier: fixed precision actions, plus pressure-sensitive
        // precision actions bound to a trigger axis (scaled by how far it's pulled)
        let mut prec_mult = 1.0_f64;
        for f in self.precision.values() {
            prec_mult = prec_mult.min(*f);
        }
        for lname in &self.stack {
            if let Some(layer) = self.cfg.layers.iter().find(|l| &l.name == lname) {
                for b in &layer.bindings {
                    let nm = &b.input.name;
                    if !(nm.starts_with("axis") && (nm.ends_with('+') || nm.ends_with('-'))) {
                        continue;
                    }
                    let factor = b.on_press.iter().find_map(|a| match a {
                        Action::Precision { factor, pressure } if *pressure => Some(*factor),
                        _ => None,
                    });
                    if let Some(factor) = factor {
                        let axkey = nm.trim_end_matches(|c| c == '+' || c == '-');
                        let sign = if nm.ends_with('-') { -1.0 } else { 1.0 };
                        let v = *st.axes.get(axkey).unwrap_or(&0.0);
                        let base = *self.axis_base.get(axkey).unwrap_or(&v);
                        let denom = sign - base;
                        let t = if denom.abs() > 0.1 {
                            ((v - base) / denom).clamp(0.0, 1.0)
                        } else {
                            0.0
                        };
                        prec_mult = prec_mult.min(1.0 + t * (factor - 1.0));
                    }
                }
            }
        }

        if self.cfg.cursor.enabled && !self.cursor_paused {
            let ax = deadzone(*st.axes.get(&self.cfg.cursor.axis_x).unwrap_or(&0.0), self.cfg.deadzone);
            let ay = deadzone(*st.axes.get(&self.cfg.cursor.axis_y).unwrap_or(&0.0), self.cfg.deadzone);
            if ax != 0.0 || ay != 0.0 {
                let spd = self.cfg.cursor.speed * prec_mult * dt;
                let ey = if self.cfg.cursor.invert_y { -ay } else { ay };
                out.move_cursor(
                    curve(ax, self.cfg.cursor.curve) * spd,
                    curve(ey, self.cfg.cursor.curve) * spd,
                    self.held_mouse.as_deref(),
                );
            }
        }

        if self.cfg.scroll.enabled {
            let s = &self.cfg.scroll;
            let mut vy = 0.0;
            let mut vx = 0.0;
            if !s.axis_y.is_empty() {
                let v = deadzone(*st.axes.get(&s.axis_y).unwrap_or(&0.0), self.cfg.deadzone);
                vy = if s.invert_y { -v } else { v };
            }
            if !s.axis_x.is_empty() {
                let v = deadzone(*st.axes.get(&s.axis_x).unwrap_or(&0.0), self.cfg.deadzone);
                vx = if s.invert_x { -v } else { v };
            }
            if vy != 0.0 || vx != 0.0 {
                self.scroll_acc_y += vy * s.speed * dt;
                self.scroll_acc_x += vx * s.speed * dt;
                let iy = self.scroll_acc_y.trunc() as i32;
                let ix = self.scroll_acc_x.trunc() as i32;
                if iy != 0 || ix != 0 {
                    out.scroll(ix, iy);
                    self.scroll_acc_y -= iy as f64;
                    self.scroll_acc_x -= ix as f64;
                }
            } else {
                self.scroll_acc_x = 0.0;
                self.scroll_acc_y = 0.0;
            }
        }

        let mut names: HashSet<String> = HashSet::new();
        for l in &self.cfg.layers {
            for b in &l.bindings {
                if b.input.kind == "button" {
                    names.insert(b.input.name.clone());
                }
            }
        }
        let debounce = (self.cfg.release_debounce_ms / 1000.0).max(0.0);
        for name in names {
            let phys = st.pressed.contains(&name);
            let was = self.prev.contains(&name);
            if phys {
                // re-pressed (or still held) — cancel any pending release blip
                self.release_timer.remove(&name);
                if !was {
                    if let Some(b) = self.resolve(&name) {
                        // pick the first override whose 'when' control is held; else default (-1)
                        let mut branch: i32 = -1;
                        for (i, ov) in b.overrides.iter().enumerate() {
                            if st.pressed.contains(&ov.when) {
                                branch = i as i32;
                                break;
                            }
                        }
                        self.active_branch.insert(name.clone(), branch);
                        let acts: &Vec<Action> = if branch >= 0 {
                            &b.overrides[branch as usize].on_press
                        } else {
                            &b.on_press
                        };
                        let mut revs = Vec::new();
                        for a in acts {
                            if let Some(r) = self.do_action(a, &name, out) {
                                revs.push(r);
                            }
                        }
                        if !revs.is_empty() {
                            self.reverts.insert(name.clone(), revs);
                        }
                    }
                    self.prev.insert(name.clone());
                }
            } else if was {
                // physically released but still logically pressed: debounce bounce
                let t = self.release_timer.entry(name.clone()).or_insert(0.0);
                *t += dt;
                if *t >= debounce {
                    self.release_timer.remove(&name);
                    if let Some(revs) = self.reverts.remove(&name) {
                        for r in revs.into_iter().rev() {
                            self.apply_revert(r, out);
                        }
                    }
                    if let Some(b) = self.resolve(&name) {
                        let branch = self.active_branch.remove(&name).unwrap_or(-1);
                        let rel: &Vec<Action> = if branch >= 0 && (branch as usize) < b.overrides.len() {
                            &b.overrides[branch as usize].on_release
                        } else {
                            &b.on_release
                        };
                        for a in rel {
                            self.do_action(a, &name, out);
                        }
                    }
                    self.prev.remove(&name);
                }
            }
        }
    }

    fn do_action(&mut self, a: &Action, name: &str, out: &mut dyn Out) -> Option<Revert> {
        let flags = self.cur_mods();
        match a {
            Action::Key { key, mods, event } => {
                let base = flags;
                match event.as_str() {
                    "down" => {
                        let mut f = base;
                        for m in mods {
                            f |= mod_flag(m);
                        }
                        out.key(key, f, true);
                        self.held_keys.insert(key.clone(), f);
                    }
                    "up" => {
                        let mut f = base;
                        for m in mods {
                            f |= mod_flag(m);
                        }
                        out.key(key, f, false);
                        self.held_keys.remove(key);
                    }
                    _ => {
                        // press modifiers (flag accumulates), tap key, release modifiers
                        // (flag steps back down) so no modifier is left "stuck"
                        let mut cur = base;
                        for m in mods {
                            cur |= mod_flag(m);
                            out.key(m, cur, true);
                        }
                        out.key_tap(key, cur);
                        for m in mods.iter().rev() {
                            cur &= !mod_flag(m);
                            out.key(m, cur, false);
                        }
                    }
                }
            }
            Action::Mouse { button, event } => {
                match event.as_str() {
                    "down" => {
                        out.mouse(button, true, flags);
                        self.held_mouse = Some(button.clone());
                    }
                    "up" => {
                        out.mouse(button, false, flags);
                        if self.held_mouse.as_deref() == Some(button.as_str()) {
                            self.held_mouse = None;
                        }
                    }
                    _ => out.mouse_tap(button, flags),
                }
            }
            Action::Scroll { amount } => out.scroll(0, *amount),
            Action::Modifier { modname } => {
                out.key(modname, mod_flag(modname), true);
                self.mods.insert(name.to_string(), mod_flag(modname));
                return Some(Revert::ClearMod(name.to_string(), modname.clone()));
            }
            Action::Precision { factor, pressure } => {
                if *pressure {
                    // applied continuously in tick() based on trigger position
                    return None;
                }
                self.precision.insert(name.to_string(), *factor);
                return Some(Revert::ClearPrecision(name.to_string()));
            }
            Action::Cursor { mode } => match mode.as_str() {
                "on" => self.cursor_paused = false,
                "off" => self.cursor_paused = true,
                _ => self.cursor_paused = !self.cursor_paused,
            },
            Action::EnterLayer { layer, mode } => match mode.as_str() {
                "toggle" => {
                    if let Some(p) = self.stack.iter().position(|x| x == layer) {
                        self.stack.remove(p);
                    } else {
                        self.stack.push(layer.clone());
                    }
                }
                _ => {
                    self.stack.push(layer.clone());
                    if mode == "momentary" {
                        return Some(Revert::PopLayer(layer.clone()));
                    }
                }
            },
            Action::ExitLayer { layer } => {
                if let Some(l) = layer {
                    if let Some(p) = self.stack.iter().position(|x| x == l) {
                        self.stack.remove(p);
                    }
                } else if self.stack.len() > 1 {
                    self.stack.pop();
                }
            }
        }
        None
    }

    fn apply_revert(&mut self, r: Revert, out: &mut dyn Out) {
        match r {
            Revert::PopLayer(n) => {
                if let Some(p) = self.stack.iter().position(|x| x == &n) {
                    self.stack.remove(p);
                }
            }
            Revert::ClearMod(n, m) => {
                self.mods.remove(&n);
                out.key(&m, 0, false);
            }
            Revert::ClearPrecision(n) => {
                self.precision.remove(&n);
            }
            Revert::KeyUp(k, f) => out.key(&k, f, false),
            Revert::MouseUp(b, f) => {
                out.mouse(&b, false, f);
                self.held_mouse = None;
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct Fake { ev: Vec<String> }
    impl Out for Fake {
        fn key(&mut self, k: &str, f: u64, d: bool) { self.ev.push(format!("key {} {} {}", k, f, d)); }
        fn key_tap(&mut self, k: &str, f: u64) { self.ev.push(format!("keytap {} {}", k, f)); }
        fn mouse(&mut self, b: &str, d: bool, f: u64) { self.ev.push(format!("mouse {} {} {}", b, d, f)); }
        fn mouse_tap(&mut self, b: &str, f: u64) { self.ev.push(format!("mousetap {} {}", b, f)); }
        fn scroll(&mut self, dx: i32, dy: i32) { self.ev.push(format!("scroll {} {}", dx, dy)); }
        fn move_cursor(&mut self, dx: f64, dy: f64, _: Option<&str>) { self.ev.push(format!("move {:.3} {:.3}", dx, dy)); }
    }

    fn st(pressed: &[&str]) -> InputState {
        InputState {
            pressed: pressed.iter().map(|s| s.to_string()).collect(),
            axes: HashMap::new(),
        }
    }

    fn cfg() -> Config {
        let json = r#"{
          "deadzone":0.12,
          "cursor":{"enabled":false,"axis_x":"LeftStickX","axis_y":"LeftStickY","speed":0,"curve":2.0,"invert_y":false},
          "layers":[
            {"name":"base","bindings":[
              {"input":{"kind":"button","name":"LeftTrigger"},"on_press":[{"type":"modifier","mod":"shift"}]},
              {"input":{"kind":"button","name":"RightTrigger2"},"on_press":[{"type":"mouse","button":"left"}]},
              {"input":{"kind":"button","name":"South"},"on_press":[{"type":"enter_layer","layer":"alt","mode":"momentary"}]},
              {"input":{"kind":"button","name":"East"},"on_press":[{"type":"key","key":"g"},{"type":"enter_layer","layer":"grab","mode":"latched"}]}
            ]},
            {"name":"alt","bindings":[{"input":{"kind":"button","name":"North"},"on_press":[{"type":"key","key":"x"}]}]},
            {"name":"grab","bindings":[{"input":{"kind":"button","name":"RightTrigger2"},"on_press":[{"type":"mouse","button":"left"},{"type":"exit_layer"}]}]}
          ]
        }"#;
        serde_json::from_str(json).unwrap()
    }

    #[test]
    fn key_combo_presses_real_modifier() {
        let json = r#"{
          "deadzone":0.12,
          "cursor":{"enabled":false,"axis_x":"LeftStickX","axis_y":"LeftStickY","speed":0,"curve":2.0,"invert_y":false},
          "layers":[{"name":"base","bindings":[
            {"input":{"kind":"button","name":"A"},"on_press":[{"type":"key","key":"z","mods":["ctrl"]}]}
          ]}]
        }"#;
        let cfg: Config = serde_json::from_str(json).unwrap();
        let mut e = Engine::new(cfg);
        let mut o = Fake { ev: vec![] };
        e.tick(&st(&["A"]), 0.01, &mut o);
        // ctrl flag = 0x40000 = 262144
        assert!(o.ev.iter().any(|s| s == "key ctrl 262144 true"), "{:?}", o.ev);
        assert!(o.ev.iter().any(|s| s == "keytap z 262144"), "{:?}", o.ev);
        assert!(o.ev.iter().any(|s| s == "key ctrl 0 false"), "{:?}", o.ev);
    }

    #[test]
    fn pressure_precision() {
        let json = r#"{
          "deadzone":0.0,
          "cursor":{"enabled":true,"axis_x":"LX","axis_y":"LY","speed":1000.0,"curve":1.0,"invert_y":false},
          "layers":[{"name":"base","bindings":[
            {"input":{"kind":"button","name":"axis5+"},"on_press":[{"type":"precision","factor":0.5,"pressure":true}]}
          ]}]
        }"#;
        let cfg: Config = serde_json::from_str(json).unwrap();
        let mut e = Engine::new(cfg);
        let mut o = Fake { ev: vec![] };
        let mk = |lx: f64, tr: f64| {
            let mut a: HashMap<String, f64> = HashMap::new();
            a.insert("LX".to_string(), lx);
            a.insert("axis5".to_string(), tr);
            InputState { pressed: HashSet::new(), axes: a }
        };
        // trigger at rest (-1) captured as baseline -> full speed
        e.tick(&mk(1.0, -1.0), 0.01, &mut o);
        assert!(o.ev.iter().any(|s| s == "move 10.000 0.000"), "{:?}", o.ev);
        // trigger fully pulled (+1) -> 0.5x
        e.tick(&mk(1.0, 1.0), 0.01, &mut o);
        assert!(o.ev.iter().any(|s| s == "move 5.000 0.000"), "{:?}", o.ev);
    }

    #[test]
    fn scroll_stick() {
        let json = r#"{
          "deadzone":0.1,
          "cursor":{"enabled":false,"axis_x":"LeftStickX","axis_y":"LeftStickY","speed":0,"curve":2.0,"invert_y":false},
          "scroll":{"enabled":true,"axis_x":"","axis_y":"RY","speed":1000.0,"invert_x":false,"invert_y":false},
          "layers":[{"name":"base","bindings":[]}]
        }"#;
        let cfg: Config = serde_json::from_str(json).unwrap();
        let mut e = Engine::new(cfg);
        let mut o = Fake { ev: vec![] };
        let mut axes: HashMap<String, f64> = HashMap::new();
        axes.insert("RY".to_string(), 1.0);
        let s = InputState { pressed: HashSet::new(), axes };
        e.tick(&s, 0.05, &mut o); // 1.0 * 1000 * 0.05 = 50
        assert!(o.ev.iter().any(|x| x == "scroll 0 50"), "{:?}", o.ev);
    }

    #[test]
    fn override_when_held() {
        let json = r#"{
          "deadzone":0.12,
          "cursor":{"enabled":false,"axis_x":"LeftStickX","axis_y":"LeftStickY","speed":0,"curve":2.0,"invert_y":false},
          "layers":[{"name":"base","bindings":[
            {"input":{"kind":"button","name":"A"},
             "on_press":[{"type":"mouse","button":"left"}],
             "overrides":[{"when":"X","on_press":[{"type":"mouse","button":"right"}]}]}
          ]}]
        }"#;
        let cfg: Config = serde_json::from_str(json).unwrap();
        let mut e = Engine::new(cfg);
        let mut o = Fake { ev: vec![] };
        // A alone -> default (left)
        e.tick(&st(&["A"]), 0.01, &mut o);
        e.tick(&st(&[]), 0.08, &mut o);
        assert!(o.ev.iter().any(|s| s == "mousetap left 0"));
        assert!(!o.ev.iter().any(|s| s == "mousetap right 0"));
        // hold X, then press A -> override (right)
        e.tick(&st(&["X"]), 0.01, &mut o);
        e.tick(&st(&["X", "A"]), 0.01, &mut o);
        assert!(o.ev.iter().any(|s| s == "mousetap right 0"), "override should fire while X held");
    }

    #[test]
    fn cursor_toggle() {
        let json = r#"{
          "deadzone":0.12,
          "cursor":{"enabled":true,"axis_x":"LeftStickX","axis_y":"LeftStickY","speed":0,"curve":2.0,"invert_y":false},
          "layers":[{"name":"base","bindings":[
            {"input":{"kind":"button","name":"A"},"on_press":[{"type":"cursor","mode":"toggle"}]}
          ]}]
        }"#;
        let cfg: Config = serde_json::from_str(json).unwrap();
        let mut e = Engine::new(cfg);
        let mut o = Fake { ev: vec![] };
        assert!(e.cursor_active());
        e.tick(&st(&["A"]), 0.01, &mut o);
        assert!(!e.cursor_active(), "press should pause cursor");
        e.tick(&st(&[]), 0.08, &mut o);
        e.tick(&st(&["A"]), 0.01, &mut o);
        assert!(e.cursor_active(), "second press should resume cursor");
    }

    #[test]
    fn hold_down_up_no_repeat() {
        let json = r#"{
          "deadzone":0.12,
          "cursor":{"enabled":false,"axis_x":"LeftStickX","axis_y":"LeftStickY","speed":0,"curve":2.0,"invert_y":false},
          "layers":[{"name":"base","bindings":[
            {"input":{"kind":"button","name":"A"},
             "on_press":[{"type":"mouse","button":"left","event":"down"}],
             "on_release":[{"type":"mouse","button":"left","event":"up"}]}
          ]}]
        }"#;
        let cfg: Config = serde_json::from_str(json).unwrap();
        let mut e = Engine::new(cfg);
        let mut o = Fake { ev: vec![] };
        // press + hold several ticks
        for _ in 0..5 { e.tick(&st(&["A"]), 0.01, &mut o); }
        let downs = o.ev.iter().filter(|s| s.starts_with("mouse left true")).count();
        assert_eq!(downs, 1, "should press down exactly once while held");
        // a one-frame bounce (released then re-pressed) must NOT commit a release
        e.tick(&st(&[]), 0.01, &mut o);
        e.tick(&st(&["A"]), 0.01, &mut o);
        let ups_mid = o.ev.iter().filter(|s| s.starts_with("mouse left false")).count();
        assert_eq!(ups_mid, 0, "bounce within debounce must not release");
        // genuine release past debounce
        e.tick(&st(&[]), 0.08, &mut o);
        let ups = o.ev.iter().filter(|s| s.starts_with("mouse left false")).count();
        assert_eq!(ups, 1, "should release up exactly once");
        assert_eq!(o.ev.iter().filter(|s| s.starts_with("mouse left true")).count(), 1);
    }

    #[test]
    fn shift_click() {
        let mut e = Engine::new(cfg());
        let mut o = Fake { ev: vec![] };
        e.tick(&st(&["LeftTrigger"]), 0.01, &mut o);
        e.tick(&st(&["LeftTrigger", "RightTrigger2"]), 0.01, &mut o);
        assert!(o.ev.iter().any(|s| s == &format!("mousetap left {}", MOD_SHIFT)));
        e.tick(&st(&["RightTrigger2"]), 0.08, &mut o); // released LeftTrigger
        assert_eq!(e.cur_mods(), 0);
    }

    #[test]
    fn momentary_layer() {
        let mut e = Engine::new(cfg());
        let mut o = Fake { ev: vec![] };
        e.tick(&st(&["South"]), 0.01, &mut o);
        assert_eq!(e.stack, vec!["base", "alt"]);
        e.tick(&st(&["South", "North"]), 0.01, &mut o);
        assert!(o.ev.iter().any(|s| s == "keytap x 0"));
        e.tick(&st(&[]), 0.08, &mut o);
        assert_eq!(e.stack, vec!["base"]);
    }

    #[test]
    fn latched_then_exit() {
        let mut e = Engine::new(cfg());
        let mut o = Fake { ev: vec![] };
        e.tick(&st(&["East"]), 0.01, &mut o);
        assert_eq!(e.stack, vec!["base", "grab"]);
        e.tick(&st(&[]), 0.01, &mut o);
        assert_eq!(e.stack, vec!["base", "grab"]);
        e.tick(&st(&["RightTrigger2"]), 0.01, &mut o);
        assert_eq!(e.stack, vec!["base"]);
    }
}
