#![cfg_attr(all(not(debug_assertions), target_os = "windows"), windows_subsystem = "windows")]

use std::fs;
use std::path::PathBuf;
use tauri::Manager;

fn canvas_dir(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let base = app
        .path()
        .desktop_dir()
        .or_else(|_| app.path().home_dir().map(|h| h.join("Desktop")))
        .map_err(|e| e.to_string())?;
    let dir = base.join("Desktop Canvas");
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    Ok(dir)
}

#[tauri::command]
fn quit(app: tauri::AppHandle) {
    app.exit(0);
}

#[tauri::command]
fn add_dropped_file(app: tauri::AppHandle, path: String) -> Result<String, String> {
    let src = PathBuf::from(&path);
    if !src.is_file() {
        return Err(format!("not a file: {}", path));
    }
    let name = src.file_name().ok_or("no file name")?.to_string_lossy().to_string();
    let dir = canvas_dir(&app)?;
    let mut dest = dir.join(&name);
    if dest.exists() {
        let stem = src.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_else(|| name.clone());
        let ext = src.extension().map(|s| format!(".{}", s.to_string_lossy())).unwrap_or_default();
        let mut i = 1;
        loop {
            let candidate = dir.join(format!("{} ({}){}", stem, i, ext));
            if !candidate.exists() { dest = candidate; break; }
            i += 1;
        }
    }
    fs::copy(&src, &dest).map_err(|e| e.to_string())?;
    Ok(dest.file_name().unwrap().to_string_lossy().to_string())
}

#[tauri::command]
fn save_layout(app: tauri::AppHandle, data: String) -> Result<(), String> {
    let dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    fs::write(dir.join("layout.json"), data).map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn load_layout(app: tauri::AppHandle) -> Result<String, String> {
    let dir = app.path().app_data_dir().map_err(|e| e.to_string())?;
    let p = dir.join("layout.json");
    if p.exists() { fs::read_to_string(p).map_err(|e| e.to_string()) } else { Ok("[]".to_string()) }
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![quit, add_dropped_file, save_layout, load_layout])
        .setup(|app| {
            let handle = app.handle().clone();
            let _ = canvas_dir(&handle);
            if let Some(main) = handle.get_webview_window("main") {
                if let Ok(monitors) = main.available_monitors() {
                    if let Some(m0) = monitors.get(0) {
                        let wa = m0.work_area();
                        let _ = main.set_position(wa.position);
                        let _ = main.set_size(wa.size);
                    }
                    let _ = main.set_always_on_bottom(true);
                    let _ = main.show();

                    let extra: Vec<(tauri::PhysicalPosition<i32>, tauri::PhysicalSize<u32>)> =
                        monitors.iter().skip(1).map(|m| { let wa = m.work_area(); (wa.position, wa.size) }).collect();

                    if !extra.is_empty() {
                        let h2 = handle.clone();
                        std::thread::spawn(move || {
                            for (idx, (pos, size)) in extra.iter().enumerate() {
                                let label = format!("screen-{}", idx + 1);
                                if let Ok(win) = tauri::WebviewWindowBuilder::new(&h2, &label, tauri::WebviewUrl::App("index.html".into()))
                                    .decorations(false).skip_taskbar(true).resizable(false).visible(false).build()
                                {
                                    let _ = win.set_position(*pos);
                                    let _ = win.set_size(*size);
                                    let _ = win.set_always_on_bottom(true);
                                    let _ = win.show();
                                }
                            }
                        });
                    }
                } else {
                    let _ = main.set_always_on_bottom(true);
                    let _ = main.show();
                }
            }
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Desktop Canvas");
}
