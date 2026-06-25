#![cfg_attr(all(not(debug_assertions), target_os = "macos"), windows_subsystem = "windows")]

mod engine;
#[cfg(target_os = "macos")]
mod macout;

use engine::{default_config, Config, Engine, InputState, Out};
use std::collections::{HashMap, HashSet};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};
use tauri::{Emitter, Manager};

use gilrs::{Axis, Button, EventType, Gilrs};

fn btn_label(btn: Button, code_u32: u32) -> String {
    match btn {
        Button::South => "A".into(),
        Button::East => "B".into(),
        Button::North => "Y".into(),
        Button::West => "X".into(),
        Button::LeftTrigger => "LB".into(),
        Button::RightTrigger => "RB".into(),
        Button::LeftTrigger2 => "LT".into(),
        Button::RightTrigger2 => "RT".into(),
        Button::Select => "Back".into(),
        Button::Start => "Start".into(),
        Button::Mode => "Guide".into(),
        Button::LeftThumb => "L3".into(),
        Button::RightThumb => "R3".into(),
        Button::DPadUp => "D-Up".into(),
        Button::DPadDown => "D-Down".into(),
        Button::DPadLeft => "D-Left".into(),
        Button::DPadRight => "D-Right".into(),
        _ => format!("button {}", code_u32),
    }
}

fn config_path() -> std::path::PathBuf {
    let home = std::env::var("HOME").unwrap_or_else(|_| ".".into());
    std::path::Path::new(&home).join(".gamepad_mapper.json")
}

fn load_config() -> Config {
    if let Ok(txt) = std::fs::read_to_string(config_path()) {
        if let Ok(c) = serde_json::from_str::<Config>(&txt) {
            return c;
        }
    }
    default_config()
}

struct Shared {
    cfg: Mutex<Config>,
    running: AtomicBool,
    learn: AtomicBool,
    dirty: AtomicBool,
}

#[tauri::command]
fn get_config(state: tauri::State<Arc<Shared>>) -> String {
    serde_json::to_string(&*state.cfg.lock().unwrap()).unwrap_or_else(|_| "{}".into())
}

#[tauri::command]
fn set_config(json: String, state: tauri::State<Arc<Shared>>) -> Result<(), String> {
    let cfg: Config = serde_json::from_str(&json).map_err(|e| e.to_string())?;
    let _ = std::fs::write(config_path(), serde_json::to_string_pretty(&cfg).unwrap());
    *state.cfg.lock().unwrap() = cfg;
    state.dirty.store(true, Ordering::SeqCst);
    Ok(())
}

#[tauri::command]
fn set_running(on: bool, state: tauri::State<Arc<Shared>>) {
    state.running.store(on, Ordering::SeqCst);
}

#[tauri::command]
fn learn_next(state: tauri::State<Arc<Shared>>) {
    state.learn.store(true, Ordering::SeqCst);
}

#[tauri::command]
fn request_accessibility() -> bool {
    #[cfg(target_os = "macos")]
    {
        return macos_accessibility_client::accessibility::application_is_trusted_with_prompt();
    }
    #[allow(unreachable_code)]
    true
}

#[cfg(target_os = "macos")]
fn make_out() -> Box<dyn Out + Send> { Box::new(macout::MacOut::new()) }

#[cfg(not(target_os = "macos"))]
fn make_out() -> Box<dyn Out + Send> {
    struct Noop;
    impl Out for Noop {
        fn key(&mut self, _: &str, _: u64, _: bool) {}
        fn key_tap(&mut self, _: &str, _: u64) {}
        fn mouse(&mut self, _: &str, _: bool, _: u64) {}
        fn mouse_tap(&mut self, _: &str, _: u64) {}
        fn scroll(&mut self, _: i32, _: i32) {}
        fn move_cursor(&mut self, _: f64, _: f64, _: Option<&str>) {}
    }
    Box::new(Noop)
}

struct LogOut {
    inner: Box<dyn Out + Send>,
    log: Arc<Mutex<String>>,
}
impl Out for LogOut {
    fn key(&mut self, k: &str, f: u64, d: bool) {
        *self.log.lock().unwrap() = format!("key {} {}", k, if d { "down" } else { "up" });
        self.inner.key(k, f, d);
    }
    fn key_tap(&mut self, k: &str, f: u64) {
        *self.log.lock().unwrap() = format!("key {}", k);
        self.inner.key_tap(k, f);
    }
    fn mouse(&mut self, b: &str, d: bool, f: u64) {
        *self.log.lock().unwrap() = format!("{} {}", b, if d { "down" } else { "up" });
        self.inner.mouse(b, d, f);
    }
    fn mouse_tap(&mut self, b: &str, f: u64) {
        *self.log.lock().unwrap() = format!("{} click", b);
        self.inner.mouse_tap(b, f);
    }
    fn scroll(&mut self, dx: i32, dy: i32) {
        *self.log.lock().unwrap() = format!("scroll {} {}", dx, dy);
        self.inner.scroll(dx, dy);
    }
    fn move_cursor(&mut self, dx: f64, dy: f64, h: Option<&str>) {
        self.inner.move_cursor(dx, dy, h);
    }
}

fn spawn_engine(app: tauri::AppHandle, shared: Arc<Shared>) {
    std::thread::spawn(move || {
        let mut gilrs = match Gilrs::new() {
            Ok(g) => g,
            Err(_) => return,
        };
        let mut eng = Engine::new(shared.cfg.lock().unwrap().clone());
        let last_fired = Arc::new(Mutex::new(String::from("-")));
        let mut out: Box<dyn Out + Send> = Box::new(LogOut {
            inner: make_out(),
            log: last_fired.clone(),
        });
        let mut last = Instant::now();
        let mut last_status = Instant::now();
        let trace_start = Instant::now();
        let mut trace: std::collections::VecDeque<String> = std::collections::VecDeque::new();
        let mut prev_pressed: HashSet<String> = HashSet::new();
        let mut prev_running = false;
        let mut pressed: HashSet<String> = HashSet::new(); // raw codes currently down
        let mut labels: HashMap<String, String> = HashMap::new(); // code -> friendly label
        let mut axis_vals: HashMap<String, f64> = HashMap::new(); // code -> value (diag)
        let mut axis_base: HashMap<u32, f64> = HashMap::new(); // code -> resting value

        loop {
            while let Some(ev) = gilrs.next_event() {
                match ev.event {
                    EventType::ButtonPressed(btn, code) => {
                        let cu = code.into_u32();
                        let c = cu.to_string();
                        let lbl = btn_label(btn, cu);
                        trace.push_back(format!("{} DN @{}ms", lbl, trace_start.elapsed().as_millis()));
                        if trace.len() > 24 { trace.pop_front(); }
                        labels.insert(c.clone(), lbl);
                        pressed.insert(c);
                    }
                    EventType::ButtonReleased(_, code) => {
                        let cu = code.into_u32();
                        let c = cu.to_string();
                        let lbl = labels.get(&c).cloned().unwrap_or_else(|| c.clone());
                        trace.push_back(format!("{} UP @{}ms", lbl, trace_start.elapsed().as_millis()));
                        if trace.len() > 24 { trace.pop_front(); }
                        pressed.remove(&c);
                    }
                    EventType::AxisChanged(_, val, code) => {
                        let cu = code.into_u32();
                        let v = val as f64;
                        axis_vals.insert(cu.to_string(), v);
                        let base = *axis_base.entry(cu).or_insert(v);
                        let dev = v - base;
                        let pos = format!("axis{}+", cu);
                        let neg = format!("axis{}-", cu);
                        if dev > 0.6 {
                            labels.insert(pos.clone(), format!("axis {} +", cu));
                            pressed.insert(pos);
                        } else {
                            pressed.remove(&pos);
                        }
                        if dev < -0.6 {
                            labels.insert(neg.clone(), format!("axis {} -", cu));
                            pressed.insert(neg);
                        } else {
                            pressed.remove(&neg);
                        }
                    }
                    EventType::Disconnected => {
                        pressed.clear();
                        axis_vals.clear();
                    }
                    _ => {}
                }
            }

            if shared.dirty.swap(false, Ordering::SeqCst) {
                eng.release_all(out.as_mut());
                eng.set_config(shared.cfg.lock().unwrap().clone());
            }

            // Controller name + left-stick axes for the cursor (the stick maps fine).
            let mut name = String::from("(no controller)");
            let mut cursor_axes: HashMap<String, f64> = HashMap::new();
            if let Some((_, g)) = gilrs.gamepads().next() {
                name = g.name().to_string();
                cursor_axes.insert("LeftStickX".to_string(), g.value(Axis::LeftStickX) as f64);
                cursor_axes.insert("LeftStickY".to_string(), g.value(Axis::LeftStickY) as f64);
                cursor_axes.insert("RightStickX".to_string(), g.value(Axis::RightStickX) as f64);
                cursor_axes.insert("RightStickY".to_string(), g.value(Axis::RightStickY) as f64);
            }

            if shared.learn.load(Ordering::SeqCst) {
                if let Some(newc) = pressed.difference(&prev_pressed).next() {
                    shared.learn.store(false, Ordering::SeqCst);
                    let payload = serde_json::json!({
                        "code": newc,
                        "label": labels.get(newc).cloned().unwrap_or_else(|| newc.clone()),
                    });
                    let _ = app.emit("learned", payload.to_string());
                }
            }
            prev_pressed = pressed.clone();

            let mut pressed_list: Vec<String> = pressed
                .iter()
                .map(|c| labels.get(c).cloned().unwrap_or_else(|| c.clone()))
                .collect();
            pressed_list.sort();
            let mut axes_show = cursor_axes.clone();
            for (k, v) in &axis_vals {
                if v.abs() > 0.05 {
                    axes_show.insert(format!("axis{}", k), *v);
                }
            }
            let axes_dbg = serde_json::to_value(&axes_show).unwrap_or(serde_json::json!({}));

            // full axes (semantic + raw) for the engine and diagnostics
            let mut engine_axes = cursor_axes.clone();
            for (k, v) in &axis_vals {
                engine_axes.insert(format!("axis{}", k), *v);
            }

            let dt = last.elapsed().as_secs_f64().min(0.1);
            last = Instant::now();
            let running = shared.running.load(Ordering::SeqCst);
            if !running && prev_running {
                eng.release_all(out.as_mut());
            }
            prev_running = running;
            if running {
                let st = InputState { pressed: pressed.clone(), axes: engine_axes.clone() };
                eng.tick(&st, dt, out.as_mut());
            }

            if last_status.elapsed() > Duration::from_millis(200) {
                last_status = Instant::now();
                #[cfg(target_os = "macos")]
                let trusted = macos_accessibility_client::accessibility::application_is_trusted();
                #[cfg(not(target_os = "macos"))]
                let trusted = true;
                let eng_summary: String = eng
                    .cfg
                    .layers
                    .iter()
                    .map(|l| format!("{}({})", l.name, l.bindings.len()))
                    .collect::<Vec<_>>()
                    .join(" ");
                let axinfo = {
                    let f = |key: &String| {
                        if key.is_empty() {
                            "—".to_string()
                        } else {
                            format!("{}={:+.2}", key, engine_axes.get(key).copied().unwrap_or(0.0))
                        }
                    };
                    format!(
                        "scrollY {} | scrollX {} | prec {}",
                        f(&eng.cfg.scroll.axis_y),
                        f(&eng.cfg.scroll.axis_x),
                        f(&eng.cfg.precision_axis.axis)
                    )
                };
                let status = serde_json::json!({
                    "running": shared.running.load(Ordering::SeqCst),
                    "controller": name,
                    "layers": eng.stack,
                    "trusted": trusted,
                    "pressed": pressed_list,
                    "axes": axes_dbg,
                    "eng": eng_summary,
                    "fired": last_fired.lock().unwrap().clone(),
                    "mods": eng.active_mods(),
                    "trace": trace.iter().cloned().collect::<Vec<_>>(),
                    "debounce_ms": eng.cfg.release_debounce_ms,
                    "cursor_on": eng.cursor_active(),
                    "axinfo": axinfo,
                });
                let _ = app.emit("status", status.to_string());
            }

            std::thread::sleep(Duration::from_millis(8));
        }
    });
}

fn main() {
    let shared = Arc::new(Shared {
        cfg: Mutex::new(load_config()),
        running: AtomicBool::new(false),
        learn: AtomicBool::new(false),
        dirty: AtomicBool::new(false),
    });

    tauri::Builder::default()
        .manage(shared.clone())
        .invoke_handler(tauri::generate_handler![
            get_config,
            set_config,
            set_running,
            learn_next,
            request_accessibility
        ])
        .setup(move |app| {
            #[cfg(target_os = "macos")]
            {
                let _ = macos_accessibility_client::accessibility::application_is_trusted_with_prompt();
            }
            spawn_engine(app.handle().clone(), shared.clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
