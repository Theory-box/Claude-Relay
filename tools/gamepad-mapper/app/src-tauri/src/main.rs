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

use gilrs::{Axis, Button, Gilrs};

const BUTTONS: &[(Button, &str)] = &[
    (Button::South, "South"),
    (Button::East, "East"),
    (Button::North, "North"),
    (Button::West, "West"),
    (Button::LeftTrigger, "LeftTrigger"),
    (Button::LeftTrigger2, "LeftTrigger2"),
    (Button::RightTrigger, "RightTrigger"),
    (Button::RightTrigger2, "RightTrigger2"),
    (Button::Select, "Select"),
    (Button::Start, "Start"),
    (Button::Mode, "Mode"),
    (Button::LeftThumb, "LeftThumb"),
    (Button::RightThumb, "RightThumb"),
    (Button::DPadUp, "DPadUp"),
    (Button::DPadDown, "DPadDown"),
    (Button::DPadLeft, "DPadLeft"),
    (Button::DPadRight, "DPadRight"),
];

const AXES: &[(Axis, &str)] = &[
    (Axis::LeftStickX, "LeftStickX"),
    (Axis::LeftStickY, "LeftStickY"),
    (Axis::RightStickX, "RightStickX"),
    (Axis::RightStickY, "RightStickY"),
];

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
        fn scroll(&mut self, _: i32) {}
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
    fn scroll(&mut self, a: i32) {
        self.inner.scroll(a);
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
        let mut prev_buttons: HashSet<String> = HashSet::new();

        loop {
            while let Some(ev) = gilrs.next_event() {
                let _ = ev;
            }

            if shared.dirty.swap(false, Ordering::SeqCst) {
                eng.set_config(shared.cfg.lock().unwrap().clone());
            }

            let gp = gilrs.gamepads().next().map(|(_, g)| g);
            let mut pressed: HashSet<String> = HashSet::new();
            let mut axes: HashMap<String, f64> = HashMap::new();
            let mut name = String::from("(no controller)");
            if let Some(gp) = gp {
                name = gp.name().to_string();
                for (b, n) in BUTTONS {
                    if gp.is_pressed(*b) {
                        pressed.insert(n.to_string());
                    }
                }
                for (a, n) in AXES {
                    axes.insert(n.to_string(), gp.value(*a) as f64);
                }
                // Analog triggers are reported as axes by gilrs; treat them as buttons.
                let lz = gp.value(Axis::LeftZ) as f64;
                let rz = gp.value(Axis::RightZ) as f64;
                axes.insert("LeftZ".to_string(), lz);
                axes.insert("RightZ".to_string(), rz);
                if lz > 0.5 { pressed.insert("LeftTrigger2".to_string()); }
                if rz > 0.5 { pressed.insert("RightTrigger2".to_string()); }
            }

            if shared.learn.load(Ordering::SeqCst) {
                if let Some(newp) = pressed.difference(&prev_buttons).next() {
                    shared.learn.store(false, Ordering::SeqCst);
                    let _ = app.emit("learned", newp.clone());
                }
            }
            prev_buttons = pressed.clone();

            let mut pressed_list: Vec<String> = pressed.iter().cloned().collect();
            pressed_list.sort();
            let axes_dbg = serde_json::to_value(&axes).unwrap_or(serde_json::json!({}));

            let dt = last.elapsed().as_secs_f64().min(0.1);
            last = Instant::now();
            if shared.running.load(Ordering::SeqCst) {
                let st = InputState { pressed, axes };
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
                let status = serde_json::json!({
                    "running": shared.running.load(Ordering::SeqCst),
                    "controller": name,
                    "layers": eng.stack,
                    "trusted": trusted,
                    "pressed": pressed_list,
                    "axes": axes_dbg,
                    "eng": eng_summary,
                    "fired": last_fired.lock().unwrap().clone(),
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
