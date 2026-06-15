#![cfg_attr(all(not(debug_assertions), target_os = "windows"), windows_subsystem = "windows")]

use tauri::Manager;

#[tauri::command]
fn quit(app: tauri::AppHandle) {
    app.exit(0);
}

fn main() {
    tauri::Builder::default()
        .invoke_handler(tauri::generate_handler![quit])
        .setup(|app| {
            let handle = app.handle().clone();
            if let Some(main) = handle.get_webview_window("main") {
                if let Ok(monitors) = main.available_monitors() {
                    // Cover monitor 0 with the existing main window.
                    if let Some(m0) = monitors.get(0) {
                        let _ = main.set_position(*m0.position());
                        let _ = main.set_size(*m0.size());
                    }
                    let _ = main.set_always_on_bottom(true);
                    let _ = main.show();

                    // Create a window on each remaining monitor.
                    let extra: Vec<(tauri::PhysicalPosition<i32>, tauri::PhysicalSize<u32>)> =
                        monitors.iter().skip(1).map(|m| (*m.position(), *m.size())).collect();

                    if !extra.is_empty() {
                        let h2 = handle.clone();
                        std::thread::spawn(move || {
                            for (idx, (pos, size)) in extra.iter().enumerate() {
                                let label = format!("screen-{}", idx + 1);
                                if let Ok(win) = tauri::WebviewWindowBuilder::new(
                                    &h2,
                                    &label,
                                    tauri::WebviewUrl::App("index.html".into()),
                                )
                                .decorations(false)
                                .skip_taskbar(true)
                                .resizable(false)
                                .visible(false)
                                .build()
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
