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

// Safety: when SAFETY_ON, WRITE/MOVE/DELETE operations are confined to the Desktop
// Canvas folder. Reading/browsing/opening is always allowed anywhere. Defaults to ON
// every launch (never persisted off) so a restart can't leave writes unguarded.
use std::sync::atomic::{AtomicBool, Ordering};
static SAFETY_ON: AtomicBool = AtomicBool::new(true);

#[tauri::command]
fn set_safety(on: bool) { SAFETY_ON.store(on, Ordering::Relaxed); }

fn in_root(app: &tauri::AppHandle, dir: &str) -> Result<(), String> {
    if !SAFETY_ON.load(Ordering::Relaxed) { return Ok(()); }
    let root = canvas_dir(app)?.canonicalize().map_err(|e| e.to_string())?;
    let d = PathBuf::from(dir)
        .canonicalize()
        .map_err(|_| "Blocked: outside the Desktop Canvas folder".to_string())?;
    if d == root || d.starts_with(&root) { Ok(()) } else { Err("Blocked: outside the Desktop Canvas folder".into()) }
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
    in_root(&app, &dir)?;
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
fn make_folder(app: tauri::AppHandle, dir: String, name: String) -> Result<String, String> {
    in_root(&app, &dir)?;
    let base = PathBuf::from(&dir);
    let clean = name.trim();
    let clean = if clean.is_empty() { "New Folder" } else { clean };
    let dest = unique_dest(&base, clean);
    fs::create_dir_all(&dest).map_err(|e| e.to_string())?;
    Ok(dest.file_name().unwrap().to_string_lossy().to_string())
}

#[tauri::command]
fn move_into(app: tauri::AppHandle, dir: String, name: String, folder: String) -> Result<(), String> {
    in_root(&app, &dir)?;
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
    in_root(&app, &dir)?;
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
fn delete_file(app: tauri::AppHandle, dir: String, name: String) -> Result<(), String> {
    in_root(&app, &dir)?;
    let p = PathBuf::from(&dir).join(&name);
    if p.is_file() {
        fs::remove_file(&p).map_err(|e| e.to_string())?;
    }
    Ok(())
}

fn copy_tree(src: &PathBuf, dst: &PathBuf) -> Result<(), String> {
    if src.is_dir() {
        fs::create_dir_all(dst).map_err(|e| e.to_string())?;
        for entry in fs::read_dir(src).map_err(|e| e.to_string())? {
            let e = entry.map_err(|e| e.to_string())?;
            copy_tree(&e.path(), &dst.join(e.file_name()))?;
        }
        Ok(())
    } else {
        fs::copy(src, dst).map_err(|e| e.to_string())?;
        Ok(())
    }
}

fn dir_size(p: &PathBuf) -> u64 {
    let mut total = 0u64;
    if let Ok(rd) = fs::read_dir(p) {
        for e in rd.flatten() {
            let ep = e.path();
            if ep.is_dir() { total += dir_size(&ep); }
            else if let Ok(m) = e.metadata() { total += m.len(); }
        }
    }
    total
}

#[tauri::command]
fn path_size(path: String) -> Result<u64, String> {
    let p = PathBuf::from(&path);
    if p.is_dir() { Ok(dir_size(&p)) }
    else { Ok(fs::metadata(&p).map(|m| m.len()).unwrap_or(0)) }
}

#[tauri::command]
fn paste_shortcut(app: tauri::AppHandle, dest: String, src: String) -> Result<String, String> {
    in_root(&app, &dest)?; // creating the .lnk is a write -> destination must be writable
    let s = PathBuf::from(&src);
    if !s.exists() { return Err("source missing".into()); }
    let base = s.file_name().ok_or("no name")?.to_string_lossy().to_string();
    let d = unique_dest(&PathBuf::from(&dest), &format!("{} - Shortcut.lnk", base));
    let dest_str = d.to_string_lossy().replace('\'', "''");
    let src_str = s.to_string_lossy().replace('\'', "''");
    let ps = format!(
        "$ws=New-Object -ComObject WScript.Shell; $sc=$ws.CreateShortcut('{}'); $sc.TargetPath='{}'; $sc.Save()",
        dest_str, src_str);
    let status = std::process::Command::new("powershell")
        .args(["-NoProfile", "-WindowStyle", "Hidden", "-Command", &ps])
        .status().map_err(|e| e.to_string())?;
    if !status.success() { return Err("shortcut creation failed".into()); }
    Ok(d.file_name().unwrap().to_string_lossy().to_string())
}

#[derive(serde::Serialize)]
struct LnkInfo { target: String, dir: bool }

#[tauri::command]
fn resolve_lnk(path: String) -> Result<LnkInfo, String> {
    let esc = path.replace('\'', "''");
    let ps = format!("(New-Object -ComObject WScript.Shell).CreateShortcut('{}').TargetPath", esc);
    let out = std::process::Command::new("powershell")
        .args(["-NoProfile", "-WindowStyle", "Hidden", "-Command", &ps])
        .output().map_err(|e| e.to_string())?;
    let target = String::from_utf8_lossy(&out.stdout).trim().to_string();
    let dir = !target.is_empty() && PathBuf::from(&target).is_dir();
    Ok(LnkInfo { target, dir })
}

#[tauri::command]
fn paste_copy(app: tauri::AppHandle, dest: String, src: String) -> Result<String, String> {
    in_root(&app, &dest)?; // destination must be writable (inside canvas)
    let s = PathBuf::from(&src);
    if !s.exists() { return Err("source missing".into()); }
    let name = s.file_name().ok_or("no name")?.to_string_lossy().to_string();
    let d = unique_dest(&PathBuf::from(&dest), &name);
    copy_tree(&s, &d)?;
    Ok(d.file_name().unwrap().to_string_lossy().to_string())
}

#[tauri::command]
fn paste_move(app: tauri::AppHandle, dest: String, src: String) -> Result<String, String> {
    in_root(&app, &dest)?;
    let s = PathBuf::from(&src);
    let parent = s.parent().map(|p| p.to_string_lossy().to_string()).unwrap_or_default();
    in_root(&app, &parent)?; // moving removes from source -> source must be inside canvas too
    if !s.exists() { return Err("source missing".into()); }
    let name = s.file_name().ok_or("no name")?.to_string_lossy().to_string();
    let d = unique_dest(&PathBuf::from(&dest), &name);
    if fs::rename(&s, &d).is_err() {
        copy_tree(&s, &d)?;
        if s.is_dir() { fs::remove_dir_all(&s).map_err(|e| e.to_string())?; } else { fs::remove_file(&s).map_err(|e| e.to_string())?; }
    }
    Ok(d.file_name().unwrap().to_string_lossy().to_string())
}

#[tauri::command]
fn load_spaces(app: tauri::AppHandle) -> Result<String, String> {
    let base = app.path().app_data_dir().map_err(|e| e.to_string())?;
    let f = base.join("spaces.json");
    if f.exists() {
        return fs::read_to_string(&f).map_err(|e| e.to_string());
    }
    // default: only the main canvas folder
    let home = canvas_dir(&app)?.to_string_lossy().to_string();
    Ok(format!("[{{\"label\":\"Desktop Canvas\",\"path\":{}}}]",
        serde_json::to_string(&home).map_err(|e| e.to_string())?))
}

#[tauri::command]
fn save_spaces(app: tauri::AppHandle, data: String) -> Result<(), String> {
    let base = app.path().app_data_dir().map_err(|e| e.to_string())?;
    fs::create_dir_all(&base).map_err(|e| e.to_string())?;
    fs::write(base.join("spaces.json"), data).map_err(|e| e.to_string())
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

#[tauri::command]
fn drag_out(window: tauri::WebviewWindow, paths: Vec<String>) -> Result<(), String> {
    if paths.is_empty() { return Err("no files".into()); }
    window.app_handle().run_on_main_thread(move || {
        use std::os::windows::ffi::OsStrExt;
        use windows::core::PCWSTR;
        use windows::Win32::System::Com::{IDataObject, CoTaskMemFree};
        use windows::Win32::System::Ole::{OleInitialize, DROPEFFECT_COPY, DROPEFFECT_LINK};
        use windows::Win32::UI::Shell::{SHCreateItemFromParsingName, IShellItem, IShellItemArray, BHID_DataObject, SHDoDragDrop, SHParseDisplayName, SHCreateShellItemArrayFromIDLists};
        use windows::Win32::UI::Shell::Common::ITEMIDLIST;
        let to_wide = |s: &str| -> Vec<u16> { std::path::Path::new(s).as_os_str().encode_wide().chain(std::iter::once(0)).collect() };
        unsafe {
            let _ = OleInitialize(None);
            let data: IDataObject = if paths.len() == 1 {
                let wide = to_wide(&paths[0]);
                let item: IShellItem = match SHCreateItemFromParsingName(PCWSTR(wide.as_ptr()), None) { Ok(i) => i, Err(_) => return };
                match item.BindToHandler(None, &BHID_DataObject) { Ok(d) => d, Err(_) => return }
            } else {
                let mut pidls: Vec<*const ITEMIDLIST> = Vec::new();
                for p in &paths {
                    let wide = to_wide(p);
                    let mut pidl: *mut ITEMIDLIST = std::ptr::null_mut();
                    if SHParseDisplayName(PCWSTR(wide.as_ptr()), None, &mut pidl, 0, None).is_ok() && !pidl.is_null() {
                        pidls.push(pidl as *const ITEMIDLIST);
                    }
                }
                if pidls.is_empty() { return; }
                let made = SHCreateShellItemArrayFromIDLists(&pidls);
                for pidl in &pidls { CoTaskMemFree(Some(*pidl as *const core::ffi::c_void)); }
                let arr: IShellItemArray = match made { Ok(a) => a, Err(_) => return };
                match arr.BindToHandler(None, &BHID_DataObject) { Ok(d) => d, Err(_) => return }
            };
            let _ = SHDoDragDrop(None, Some(&data), None, DROPEFFECT_COPY | DROPEFFECT_LINK);
        }
    }).map_err(|e| e.to_string())
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![
            quit, places, list_dir, add_dropped_file, make_folder, move_into, trash_item,
            clear_trash, open_trash, thumb_data, open_item, open_folder, shell_verb, delete_file, paste_copy, paste_move, paste_shortcut, resolve_lnk, path_size, set_safety, load_spaces, save_spaces, save_layout, load_layout, drag_out
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
