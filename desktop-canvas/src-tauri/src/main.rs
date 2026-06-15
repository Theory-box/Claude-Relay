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

fn b64(data: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity((data.len() + 2) / 3 * 4);
    for chunk in data.chunks(3) {
        let b0 = chunk[0] as u32;
        let b1 = if chunk.len() > 1 { chunk[1] as u32 } else { 0 };
        let b2 = if chunk.len() > 2 { chunk[2] as u32 } else { 0 };
        let n = (b0 << 16) | (b1 << 8) | b2;
        out.push(T[((n >> 18) & 63) as usize] as char);
        out.push(T[((n >> 12) & 63) as usize] as char);
        if chunk.len() > 1 { out.push(T[((n >> 6) & 63) as usize] as char); } else { out.push('='); }
        if chunk.len() > 2 { out.push(T[(n & 63) as usize] as char); } else { out.push('='); }
    }
    out
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
fn thumb_data(app: tauri::AppHandle, name: String) -> Result<String, String> {
    let p = canvas_dir(&app)?.join(&name);
    let ext = p.extension().map(|e| e.to_string_lossy().to_lowercase()).unwrap_or_default();
    let mime = match ext.as_str() {
        "png" => "image/png",
        "jpg" | "jpeg" => "image/jpeg",
        "gif" => "image/gif",
        "webp" => "image/webp",
        "bmp" => "image/bmp",
        "svg" => "image/svg+xml",
        _ => return Ok(String::new()),
    };
    let meta = fs::metadata(&p).map_err(|e| e.to_string())?;
    if meta.len() > 8_000_000 {
        return Ok(String::new());
    }
    let bytes = fs::read(&p).map_err(|e| e.to_string())?;
    Ok(format!("data:{};base64,{}", mime, b64(&bytes)))
}

#[tauri::command]
fn open_item(app: tauri::AppHandle, name: String) -> Result<(), String> {
    let p = canvas_dir(&app)?.join(&name);
    std::process::Command::new("cmd")
        .args(["/C", "start", "", &p.to_string_lossy()])
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn open_folder(app: tauri::AppHandle) -> Result<(), String> {
    let dir = canvas_dir(&app)?;
    std::process::Command::new("explorer")
        .arg(dir.to_string_lossy().to_string())
        .spawn()
        .map_err(|e| e.to_string())?;
    Ok(())
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
        .invoke_handler(tauri::generate_handler![
            quit, add_dropped_file, thumb_data, open_item, open_folder, save_layout, load_layout
        ])
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
