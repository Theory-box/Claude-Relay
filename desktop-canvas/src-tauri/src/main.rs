#![cfg_attr(all(not(debug_assertions), target_os = "windows"), windows_subsystem = "windows")]

use std::fs;
use std::path::{Path, PathBuf};
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

#[cfg(windows)]
fn drives() -> Vec<String> {
    use windows::Win32::Storage::FileSystem::GetLogicalDrives;
    let mask = unsafe { GetLogicalDrives() };
    let mut v = Vec::new();
    for i in 0..26u32 {
        if mask & (1 << i) != 0 {
            v.push(format!("{}:\\", (b'A' + i as u8) as char));
        }
    }
    v
}
#[cfg(not(windows))]
fn drives() -> Vec<String> { Vec::new() }

#[cfg(windows)]
fn shell_thumb(path: &Path) -> Option<String> {
    use std::os::windows::ffi::OsStrExt;
    use windows::core::PCWSTR;
    use windows::Win32::Foundation::SIZE;
    use windows::Win32::Graphics::Gdi::{
        DeleteObject, GetDC, GetDIBits, GetObjectW, ReleaseDC, BITMAP, BITMAPINFO,
        BITMAPINFOHEADER, DIB_RGB_COLORS, HGDIOBJ,
    };
    use windows::Win32::System::Com::{CoInitializeEx, COINIT_APARTMENTTHREADED};
    use windows::Win32::UI::Shell::{
        SHCreateItemFromParsingName, IShellItemImageFactory, SIIGBF_RESIZETOFIT,
    };
    unsafe {
        let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
        let wide: Vec<u16> = path.as_os_str().encode_wide().chain(std::iter::once(0)).collect();
        let factory: IShellItemImageFactory =
            SHCreateItemFromParsingName(PCWSTR(wide.as_ptr()), None).ok()?;
        let hbm = factory.GetImage(SIZE { cx: 256, cy: 256 }, SIIGBF_RESIZETOFIT).ok()?;
        let mut bmp: BITMAP = std::mem::zeroed();
        if GetObjectW(HGDIOBJ(hbm.0), std::mem::size_of::<BITMAP>() as i32, Some(&mut bmp as *mut BITMAP as *mut _)) == 0 {
            let _ = DeleteObject(HGDIOBJ(hbm.0));
            return None;
        }
        let w = bmp.bmWidth;
        let h = bmp.bmHeight;
        if w <= 0 || h <= 0 { let _ = DeleteObject(HGDIOBJ(hbm.0)); return None; }
        let mut bmi: BITMAPINFO = std::mem::zeroed();
        bmi.bmiHeader.biSize = std::mem::size_of::<BITMAPINFOHEADER>() as u32;
        bmi.bmiHeader.biWidth = w;
        bmi.bmiHeader.biHeight = -h;
        bmi.bmiHeader.biPlanes = 1;
        bmi.bmiHeader.biBitCount = 32;
        bmi.bmiHeader.biCompression = 0;
        let mut buf = vec![0u8; (w as usize) * (h as usize) * 4];
        let hdc = GetDC(None);
        let scan = GetDIBits(hdc, hbm, 0, h as u32, Some(buf.as_mut_ptr() as *mut _), &mut bmi, DIB_RGB_COLORS);
        ReleaseDC(None, hdc);
        let _ = DeleteObject(HGDIOBJ(hbm.0));
        if scan == 0 { return None; }
        let mut any_alpha = false;
        for px in buf.chunks_exact(4) { if px[3] != 0 { any_alpha = true; break; } }
        let mut rgba = vec![0u8; buf.len()];
        for (i, px) in buf.chunks_exact(4).enumerate() {
            rgba[i * 4] = px[2]; rgba[i * 4 + 1] = px[1]; rgba[i * 4 + 2] = px[0];
            rgba[i * 4 + 3] = if any_alpha { px[3] } else { 255 };
        }
        let img = image::RgbaImage::from_raw(w as u32, h as u32, rgba)?;
        let mut png: Vec<u8> = Vec::new();
        {
            use image::ImageEncoder;
            image::codecs::png::PngEncoder::new(&mut png)
                .write_image(img.as_raw(), w as u32, h as u32, image::ExtendedColorType::Rgba8).ok()?;
        }
        Some(format!("data:image/png;base64,{}", b64(&png)))
    }
}
#[cfg(not(windows))]
fn shell_thumb(_path: &Path) -> Option<String> { None }

#[cfg(windows)]
fn run_verb(path: &Path, verb: &str) -> Option<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows::core::PCWSTR;
    use windows::Win32::System::Com::{CoInitializeEx, COINIT_APARTMENTTHREADED};
    use windows::Win32::UI::Shell::ShellExecuteW;
    use windows::Win32::UI::WindowsAndMessaging::SW_SHOWNORMAL;
    unsafe {
        let _ = CoInitializeEx(None, COINIT_APARTMENTTHREADED);
        let f: Vec<u16> = path.as_os_str().encode_wide().chain(std::iter::once(0)).collect();
        let v: Vec<u16> = std::ffi::OsStr::new(verb).encode_wide().chain(std::iter::once(0)).collect();
        let _ = ShellExecuteW(None, PCWSTR(v.as_ptr()), PCWSTR(f.as_ptr()), PCWSTR::null(), PCWSTR::null(), SW_SHOWNORMAL);
    }
    Some(())
}
#[cfg(not(windows))]
fn run_verb(_path: &Path, _verb: &str) -> Option<()> { None }

fn unique_dest(dir: &Path, name: &str) -> PathBuf {
    let mut dest = dir.join(name);
    if dest.exists() {
        let pb = PathBuf::from(name);
        let stem = pb.file_stem().map(|s| s.to_string_lossy().to_string()).unwrap_or_else(|| name.to_string());
        let ext = pb.extension().map(|s| format!(".{}", s.to_string_lossy())).unwrap_or_default();
        let mut i = 1;
        loop {
            let candidate = dir.join(format!("{} ({}){}", stem, i, ext));
            if !candidate.exists() { dest = candidate; break; }
            i += 1;
        }
    }
    dest
}

fn move_path(src: &Path, dest: &Path) -> Result<(), String> {
    if fs::rename(src, dest).is_ok() { return Ok(()); }
    if src.is_file() {
        fs::copy(src, dest).map_err(|e| e.to_string())?;
        fs::remove_file(src).map_err(|e| e.to_string())?;
        Ok(())
    } else {
        Err("could not move".into())
    }
}

#[derive(serde::Serialize)]
struct Entry { name: String, mtime: u64, dir: bool, size: u64 }

#[derive(serde::Serialize)]
struct Place { label: String, path: String }

fn layout_file(app: &tauri::AppHandle, key: &str) -> Result<PathBuf, String> {
    let base = app.path().app_data_dir().map_err(|e| e.to_string())?.join("layouts");
    let safe: String = if key.is_empty() {
        "_thispc".to_string()
    } else {
        key.chars().map(|c| if c == '/' || c == '\\' || c == ':' { '_' } else { c }).collect()
    };
    Ok(base.join(format!("{}.json", safe)))
}

#[tauri::command]
fn quit(app: tauri::AppHandle) { app.exit(0); }

#[tauri::command]
fn places(app: tauri::AppHandle) -> Result<String, String> {
    let mut v: Vec<Place> = Vec::new();
    if let Ok(p) = canvas_dir(&app) { v.push(Place { label: "Desktop Canvas".into(), path: p.to_string_lossy().to_string() }); }
    let path = app.path();
    if let Ok(p) = path.home_dir() { v.push(Place { label: "Home".into(), path: p.to_string_lossy().to_string() }); }
    if let Ok(p) = path.desktop_dir() { v.push(Place { label: "Desktop".into(), path: p.to_string_lossy().to_string() }); }
    if let Ok(p) = path.download_dir() { v.push(Place { label: "Downloads".into(), path: p.to_string_lossy().to_string() }); }
    if let Ok(p) = path.document_dir() { v.push(Place { label: "Documents".into(), path: p.to_string_lossy().to_string() }); }
    v.push(Place { label: "This PC".into(), path: String::new() });
    for d in drives() { v.push(Place { label: d.clone(), path: d }); }
    serde_json::to_string(&v).map_err(|e| e.to_string())
}

#[tauri::command]
fn list_dir(app: tauri::AppHandle, dir: String) -> Result<String, String> {
    let mut out: Vec<Entry> = Vec::new();
    if dir.is_empty() {
        for d in drives() { out.push(Entry { name: d.clone(), mtime: 0, dir: true, size: 0 }); }
        return serde_json::to_string(&out).map_err(|e| e.to_string());
    }
    let p = PathBuf::from(&dir);
    let home = canvas_dir(&app).ok();
    if p.is_dir() {
        for entry in fs::read_dir(&p).map_err(|e| e.to_string())? {
            let entry = entry.map_err(|e| e.to_string())?;
            let ep = entry.path();
            let name = entry.file_name().to_string_lossy().to_string();
            let is_dir = ep.is_dir();
            if is_dir && name == "Trash Can" && home.as_ref().map(|h| h == &p).unwrap_or(false) { continue; }
            let mtime = entry.metadata().ok()
                .and_then(|m| m.modified().ok())
                .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                .map(|d| d.as_secs()).unwrap_or(0);
            let size = if is_dir { 0 } else { entry.metadata().ok().map(|m| m.len()).unwrap_or(0) };
            out.push(Entry { name, mtime, dir: is_dir, size });
        }
    }
    serde_json::to_string(&out).map_err(|e| e.to_string())
}

#[tauri::command]
fn add_dropped_file(app: tauri::AppHandle, dir: String, path: String) -> Result<String, String> {
    let _ = &app;
    let src = PathBuf::from(&path);
    if !src.is_file() { return Err(format!("not a file: {}", path)); }
    let name = src.file_name().ok_or("no file name")?.to_string_lossy().to_string();
    let dst_dir = PathBuf::from(&dir);
    fs::create_dir_all(&dst_dir).map_err(|e| e.to_string())?;
    let dest = unique_dest(&dst_dir, &name);
    fs::copy(&src, &dest).map_err(|e| e.to_string())?;
    Ok(dest.file_name().unwrap().to_string_lossy().to_string())
}

#[tauri::command]
fn make_folder(_app: tauri::AppHandle, dir: String, name: String) -> Result<String, String> {
    let base = PathBuf::from(&dir);
    let clean = name.trim();
    let clean = if clean.is_empty() { "New Folder" } else { clean };
    let dest = unique_dest(&base, clean);
    fs::create_dir_all(&dest).map_err(|e| e.to_string())?;
    Ok(dest.file_name().unwrap().to_string_lossy().to_string())
}

#[tauri::command]
fn move_into(_app: tauri::AppHandle, dir: String, name: String, folder: String) -> Result<(), String> {
    let base = PathBuf::from(&dir);
    let src = base.join(&name);
    if !src.exists() { return Ok(()); }
    let dst_dir = base.join(&folder);
    fs::create_dir_all(&dst_dir).map_err(|e| e.to_string())?;
    let dest = unique_dest(&dst_dir, &name);
    move_path(&src, &dest)
}

#[tauri::command]
fn trash_item(app: tauri::AppHandle, dir: String, name: String) -> Result<(), String> {
    let src = PathBuf::from(&dir).join(&name);
    if !src.exists() { return Ok(()); }
    let trash = canvas_dir(&app)?.join("Trash Can");
    fs::create_dir_all(&trash).map_err(|e| e.to_string())?;
    let dest = unique_dest(&trash, &name);
    move_path(&src, &dest)
}

#[tauri::command]
fn clear_trash(app: tauri::AppHandle) -> Result<(), String> {
    let trash = canvas_dir(&app)?.join("Trash Can");
    if trash.exists() {
        for entry in fs::read_dir(&trash).map_err(|e| e.to_string())? {
            let p = entry.map_err(|e| e.to_string())?.path();
            if p.is_dir() { let _ = fs::remove_dir_all(&p); } else { let _ = fs::remove_file(&p); }
        }
    }
    Ok(())
}

#[tauri::command]
fn open_trash(app: tauri::AppHandle) -> Result<(), String> {
    let trash = canvas_dir(&app)?.join("Trash Can");
    fs::create_dir_all(&trash).map_err(|e| e.to_string())?;
    std::process::Command::new("explorer").arg(trash.to_string_lossy().to_string()).spawn().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn thumb_data(_app: tauri::AppHandle, dir: String, name: String) -> Result<String, String> {
    let p = PathBuf::from(&dir).join(&name);
    if !p.exists() { return Ok(String::new()); }
    Ok(shell_thumb(&p).unwrap_or_default())
}

#[tauri::command]
fn open_item(_app: tauri::AppHandle, dir: String, name: String) -> Result<(), String> {
    let p = PathBuf::from(&dir).join(&name);
    std::process::Command::new("cmd").args(["/C", "start", "", &p.to_string_lossy()]).spawn().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn open_folder(_app: tauri::AppHandle, dir: String) -> Result<(), String> {
    let p = PathBuf::from(&dir);
    std::process::Command::new("explorer").arg(p.to_string_lossy().to_string()).spawn().map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn shell_verb(_app: tauri::AppHandle, dir: String, name: String, verb: String) -> Result<(), String> {
    let p = PathBuf::from(&dir).join(&name);
    if !p.exists() { return Err("file not found".into()); }
    run_verb(&p, &verb);
    Ok(())
}

#[tauri::command]
fn delete_file(_app: tauri::AppHandle, dir: String, name: String) -> Result<(), String> {
    let p = PathBuf::from(&dir).join(&name);
    if p.is_file() {
        fs::remove_file(&p).map_err(|e| e.to_string())?;
    }
    Ok(())
}

#[tauri::command]
fn save_layout(app: tauri::AppHandle, key: String, data: String) -> Result<(), String> {
    let f = layout_file(&app, &key)?;
    if let Some(parent) = f.parent() { fs::create_dir_all(parent).map_err(|e| e.to_string())?; }
    fs::write(f, data).map_err(|e| e.to_string())?;
    Ok(())
}

#[tauri::command]
fn load_layout(app: tauri::AppHandle, key: String) -> Result<String, String> {
    let f = layout_file(&app, &key)?;
    if f.exists() { fs::read_to_string(f).map_err(|e| e.to_string()) } else { Ok("{}".to_string()) }
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            quit, places, list_dir, add_dropped_file, make_folder, move_into, trash_item,
            clear_trash, open_trash, thumb_data, open_item, open_folder, shell_verb, delete_file, save_layout, load_layout
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
