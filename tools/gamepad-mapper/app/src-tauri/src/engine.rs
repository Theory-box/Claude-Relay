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
    Key { key: String, #[serde(default)] mods: Vec<String>, #[serde(default)] hold: bool },
    #[serde(rename = "mouse")]
    Mouse { #[serde(default = "def_left")] button: String, #[serde(default)] hold: bool },
    #[serde(rename = "scroll")]
    Scroll { amount: i32 },
    #[serde(rename = "modifier")]
    Modifier { #[serde(rename = "mod")] modname: String },
    #[serde(rename = "enter_layer")]
    EnterLayer { layer: String, mode: String },
    #[serde(rename = "exit_layer")]
    ExitLayer { #[serde(default)] layer: Option<String> },
    #[serde(rename = "precision")]
    Precision { #[serde(default = "def_precision")] factor: f64 },
}

#[derive(Serialize, Deserialize, Clone, Debug)]
pub struct Binding {
    pub input: Input,
    #[serde(default)]
    pub on_press: Vec<Action>,
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
    pub layers: Vec<Layer>,
}

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
        layers: vec![
            Layer { name: "base".into(), bindings: vec![] },
            Layer { name: "alt".into(), bindings: vec![] },
        ],
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
    fn scroll(&mut self, amount: i32);
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
    }

    fn cur_mods(&self) -> u64 {
        self.mods.values().fold(0, |a, b| a | b)
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
        if self.cfg.cursor.enabled {
            let ax = deadzone(*st.axes.get(&self.cfg.cursor.axis_x).unwrap_or(&0.0), self.cfg.deadzone);
            let ay = deadzone(*st.axes.get(&self.cfg.cursor.axis_y).unwrap_or(&0.0), self.cfg.deadzone);
            if ax != 0.0 || ay != 0.0 {
                let mult = self.precision.values().cloned().fold(1.0_f64, f64::min);
                let spd = self.cfg.cursor.speed * mult * dt;
                let ey = if self.cfg.cursor.invert_y { -ay } else { ay };
                out.move_cursor(
                    curve(ax, self.cfg.cursor.curve) * spd,
                    curve(ey, self.cfg.cursor.curve) * spd,
                    self.held_mouse.as_deref(),
                );
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
        for name in names {
            let now = st.pressed.contains(&name);
            let was = self.prev.contains(&name);
            if now && !was {
                if let Some(b) = self.resolve(&name) {
                    let mut revs = Vec::new();
                    for a in &b.on_press {
                        if let Some(r) = self.do_action(a, &name, out) {
                            revs.push(r);
                        }
                    }
                    if !revs.is_empty() {
                        self.reverts.insert(name.clone(), revs);
                    }
                }
                self.prev.insert(name.clone());
            } else if !now && was {
                if let Some(revs) = self.reverts.remove(&name) {
                    for r in revs.into_iter().rev() {
                        self.apply_revert(r, out);
                    }
                }
                self.prev.remove(&name);
            }
        }
    }

    fn do_action(&mut self, a: &Action, name: &str, out: &mut dyn Out) -> Option<Revert> {
        let flags = self.cur_mods();
        match a {
            Action::Key { key, mods, hold } => {
                let mut f = flags;
                for m in mods {
                    f |= mod_flag(m);
                }
                if *hold {
                    out.key(key, f, true);
                    return Some(Revert::KeyUp(key.clone(), f));
                } else {
                    out.key_tap(key, f);
                }
            }
            Action::Mouse { button, hold } => {
                if *hold {
                    out.mouse(button, true, flags);
                    self.held_mouse = Some(button.clone());
                    return Some(Revert::MouseUp(button.clone(), flags));
                } else {
                    out.mouse_tap(button, flags);
                }
            }
            Action::Scroll { amount } => out.scroll(*amount),
            Action::Modifier { modname } => {
                out.key(modname, mod_flag(modname), true);
                self.mods.insert(name.to_string(), mod_flag(modname));
                return Some(Revert::ClearMod(name.to_string(), modname.clone()));
            }
            Action::Precision { factor } => {
                self.precision.insert(name.to_string(), *factor);
                return Some(Revert::ClearPrecision(name.to_string()));
            }
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
        fn scroll(&mut self, a: i32) { self.ev.push(format!("scroll {}", a)); }
        fn move_cursor(&mut self, _: f64, _: f64, _: Option<&str>) {}
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
    fn shift_click() {
        let mut e = Engine::new(cfg());
        let mut o = Fake { ev: vec![] };
        e.tick(&st(&["LeftTrigger"]), 0.01, &mut o);
        e.tick(&st(&["LeftTrigger", "RightTrigger2"]), 0.01, &mut o);
        assert!(o.ev.iter().any(|s| s == &format!("mousetap left {}", MOD_SHIFT)));
        e.tick(&st(&["RightTrigger2"]), 0.01, &mut o); // released LeftTrigger
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
        e.tick(&st(&[]), 0.01, &mut o);
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
