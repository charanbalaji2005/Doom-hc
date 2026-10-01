//! Native shell: floating mini window, global shortcut, tray, notifications, and the Python backend as a child process.
use std::sync::Mutex;
use tauri::{AppHandle, Manager, RunEvent};
use tauri_plugin_global_shortcut::{GlobalShortcutExt, Shortcut, ShortcutState};
use tauri_plugin_shell::{process::{CommandChild, CommandEvent}, ShellExt};

const PORT: u16 = 8765;
const DEFAULT_SHORTCUT: &str = "CommandOrControl+Shift+Space";

struct Backend { url: String, token: String, child: Mutex<Option<CommandChild>> }

#[derive(serde::Serialize)]
struct BackendInfo { url: String, token: String }

#[tauri::command]
fn backend_info(state: tauri::State<Backend>) -> BackendInfo { BackendInfo { url: state.url.clone(), token: state.token.clone() } }

#[tauri::command]
fn set_shortcut(app: AppHandle, accelerator: String) -> Result<(), String> {
    let shortcut: Shortcut = accelerator.parse().map_err(|e| format!("{e}"))?;
    let gs = app.global_shortcut();
    gs.unregister_all().map_err(|e| e.to_string())?;
    gs.register(shortcut).map_err(|e| e.to_string())
}

#[tauri::command]
fn open_workspace(app: AppHandle) {
    if let Some(w) = app.get_webview_window("main") { let _ = w.show(); let _ = w.set_focus(); }
}

#[tauri::command]
fn hide_mini(app: AppHandle) {
    if let Some(w) = app.get_webview_window("mini") { let _ = w.hide(); }
}

fn toggle_mini(app: &AppHandle) {
    if let Some(w) = app.get_webview_window("mini") {
        if w.is_visible().unwrap_or(false) { let _ = w.hide(); } else { let _ = w.show(); let _ = w.set_focus(); }
    }
}

pub fn run() {
    let token = format!("{}{}", uuid::Uuid::new_v4().simple(), uuid::Uuid::new_v4().simple());
    let url = format!("http://127.0.0.1:{PORT}");
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new()
            .with_handler(|app, _shortcut, event| { if event.state() == ShortcutState::Pressed { toggle_mini(app) } })
            .build())
        .manage(Backend { url, token: token.clone(), child: Mutex::new(None) })
        .setup(move |app| {
            // Development: HC_PYTHON=/path/to/.venv/bin/python HC_BACKEND_DIR=../backend npm run tauri dev
            // Release: a PyInstaller build of the backend bundled as the `hc-backend` sidecar.
            let shell = app.shell();
            let cmd = match std::env::var("HC_PYTHON") {
                Ok(py) => shell.command(py).args(["-m", "app.main"])
                    .current_dir(std::env::var("HC_BACKEND_DIR").unwrap_or_else(|_| "../backend".into())),
                Err(_) => shell.sidecar("hc-backend")?,
            };
            let (mut rx, child) = cmd.env("HC_API_TOKEN", &token).env("HC_PORT", PORT.to_string()).spawn()?;
            *app.state::<Backend>().child.lock().unwrap() = Some(child);
            tauri::async_runtime::spawn(async move {
                while let Some(ev) = rx.recv().await {
                    if let CommandEvent::Stderr(line) = ev { eprintln!("[backend] {}", String::from_utf8_lossy(&line)); }
                }
            });
            let sc: Shortcut = DEFAULT_SHORTCUT.parse().expect("valid default shortcut");
            if let Err(e) = app.global_shortcut().register(sc) { eprintln!("could not register {DEFAULT_SHORTCUT}: {e}"); }
            if let Some(tray) = app.tray_by_id("main") { let _ = tray.set_tooltip(Some("Humanoid Companion")); }
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![backend_info, set_shortcut, open_workspace, hide_mini])
        .build(tauri::generate_context!())
        .expect("error while building Humanoid Companion");
    app.run(|handle, event| {
        if let RunEvent::Exit = event {
            if let Some(child) = handle.state::<Backend>().child.lock().unwrap().take() { let _ = child.kill(); }
        }
    });
}
