use serde_json::{json, Value};
use std::io::{BufRead, BufReader, Write};
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::{Arc, Mutex};
use std::thread;
use tauri::{AppHandle, Emitter, Manager};

fn project_root() -> PathBuf {
    let mut dirs: Vec<PathBuf> = Vec::new();
    if let Ok(cwd) = std::env::current_dir() {
        dirs.push(cwd);
    }
    if let Ok(exe) = std::env::current_exe() {
        if let Some(parent) = exe.parent() {
            dirs.push(parent.to_path_buf());
        }
    }
    for dir in &dirs {
        for ancestor in dir.ancestors() {
            // Önce gerçek proje kökü: desktop/tauri_bridge.py + desktop/app/ birlikte olmalı.
            // cockpit/desktop gölgesi silindi; yalnız başına tauri_bridge.py yetmez.
            if ancestor.join("desktop/tauri_bridge.py").exists()
                && ancestor.join("desktop/app/agentd_client.py").exists()
            {
                return ancestor.to_path_buf();
            }
        }
    }
    dirs.first().cloned().unwrap_or_default()
}

fn venv_python(root: &PathBuf) -> PathBuf {
    let venv = root.join(".venv/bin/python");
    if venv.exists() {
        venv
    } else {
        PathBuf::from("python3")
    }
}

struct Watcher {
    child: Child,
    stdin: Option<ChildStdin>,
}

static WATCHER: Mutex<Option<Arc<Mutex<Watcher>>>> = Mutex::new(None);

fn watcher_arc() -> Result<Arc<Mutex<Watcher>>, String> {
    WATCHER
        .lock()
        .map_err(|e| e.to_string())?
        .clone()
        .ok_or_else(|| "canlı RFB izleyici çalışmıyor".into())
}

fn send_watcher_line(line: &str) -> Result<(), String> {
    let arc = watcher_arc()?;
    let mut watcher = arc.lock().map_err(|e| e.to_string())?;
    let stdin = watcher
        .stdin
        .as_mut()
        .ok_or_else(|| "RFB köprüsü stdin kapandı".to_string())?;
    stdin
        .write_all(line.as_bytes())
        .map_err(|e| e.to_string())?;
    stdin.write_all(b"\n").map_err(|e| e.to_string())?;
    stdin.flush().map_err(|e| e.to_string())
}

/// RFB izleyici sürecini başlatır; stdout satırlarını `show_base` event'ine yayınlar.
fn spawn_watcher(app: &AppHandle, remote_port: u16) -> Result<(), String> {
    let mut guard = WATCHER.lock().map_err(|e| e.to_string())?;
    if guard.is_some() {
        return Ok(());
    }
    let root = project_root();
    let mut child = Command::new(venv_python(&root))
        .arg(root.join("desktop/vnc_live_bridge.py"))
        .current_dir(&root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("RFB köprüsü başlatılamadı: {e}"))?;
    let stdin: ChildStdin = child.stdin.take().ok_or("RFB köprüsü stdin kullanılamıyor")?;
    let stdout = child.stdout.take().ok_or("RFB köprüsü stdout kullanılamıyor")?;
    *guard = Some(Arc::new(Mutex::new(Watcher {
        child,
        stdin: Some(stdin),
    })));
    drop(guard);
    send_watcher_line(&format!(
        "{{\"action\":\"watch\",\"remote_port\":{}}}",
        remote_port
    ))?;

    let emitter = app.clone();
    thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            let Ok(line) = line else { break };
            if line.trim().is_empty() {
                continue;
            }
            let payload = serde_json::from_str::<Value>(&line)
                .unwrap_or_else(|_| json!({"state": "BRIDGE", "detail": line.trim()}));
            let _ = emitter.emit("show_base", payload);
        }
    });

    let reaper = app.clone();
    thread::spawn(move || loop {
        thread::sleep(std::time::Duration::from_millis(250));
        let Ok(arc) = watcher_arc() else { break };
        let exited = {
            let mut watcher = match arc.lock() {
                Ok(w) => w,
                Err(_) => break,
            };
            match watcher.child.try_wait() {
                Ok(Some(_)) => {
                    watcher.stdin = None;
                    true
                }
                Ok(None) => false,
                Err(_) => true,
            }
        };
        if exited {
            if let Ok(mut guard) = WATCHER.lock() {
                *guard = None;
            }
            let _ = reaper.emit(
                "show_base",
                json!({"state": "RELEASED", "detail": "RFB izleyici süreç kapandı"}),
            );
            break;
        }
    });
    Ok(())
}

fn stop_watcher() -> Result<(), String> {
    let arc = {
        WATCHER
            .lock()
            .map_err(|e| e.to_string())?
            .clone()
    };
    if let Some(arc) = arc {
        // Önce kibarca dur de, olmazsa hemen öldür. Pencereyi bekletme.
        let _ = send_watcher_line("{\"action\":\"stop\"}");
        {
            let mut watcher = arc.lock().map_err(|e| e.to_string())?;
            let _ = watcher.child.kill();
            let _ = watcher.child.wait();
            watcher.stdin = None;
        }
    }
    if let Ok(mut guard) = WATCHER.lock() {
        *guard = None;
    }
    Ok(())
}

#[tauri::command]
fn agentd(command: String, payload: Value) -> Result<Value, String> {
    use std::time::Duration;
    let root = project_root();
    let mut request = payload.as_object().cloned().unwrap_or_default();
    request.insert("command".into(), Value::String(command));
    let mut child = Command::new(venv_python(&root))
        .arg(root.join("desktop/tauri_bridge.py"))
        .current_dir(&root)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("agentd köprüsü başlatılamadı: {e}"))?;
    child
        .stdin
        .take()
        .ok_or("köprü stdin kullanılamıyor")?
        .write_all(Value::Object(request).to_string().as_bytes())
        .map_err(|e| e.to_string())?;
    // Köprü yanıt vermezse pencereyi kilitleme: 15 saniyede kes.
    let output = wait_with_timeout(&mut child, Duration::from_secs(15))
        .ok_or("VDS yanıt vermedi (15sn zaman aşımı)")?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    serde_json::from_slice(&output.stdout).map_err(|e| format!("köprü yanıtı çözülemedi: {e}"))
}

fn wait_with_timeout(child: &mut Child, timeout: std::time::Duration) -> Option<std::process::Output> {
    use std::time::Instant;
    let start = Instant::now();
    loop {
        match child.try_wait() {
            Ok(Some(status)) => {
                // Çocuk zaten bitmiş; kalan çıktıyı topla.
                use std::io::Read;
                let mut stdout = Vec::new();
                let mut stderr = Vec::new();
                if let Some(mut out) = child.stdout.take() {
                    let _ = out.read_to_end(&mut stdout);
                }
                if let Some(mut err) = child.stderr.take() {
                    let _ = err.read_to_end(&mut stderr);
                }
                return Some(std::process::Output { status, stdout, stderr });
            }
            Ok(None) => {
                if start.elapsed() >= timeout {
                    let _ = child.kill();
                    let _ = child.wait();
                    return None;
                }
                thread::sleep(std::time::Duration::from_millis(50));
            }
            Err(_) => return None,
        }
    }
}

/// UI'ın seçtiği ajan kimliği (frontend `set_display_target` ile yazar).
#[tauri::command]
fn set_display_target(app: AppHandle, agent_id: String) -> Result<(), String> {
    let state = app
        .try_state::<Mutex<String>>()
        .ok_or("display hedefi yok")?;
    *state.lock().map_err(|e| e.to_string())? = agent_id;
    Ok(())
}

fn display_target(app: &AppHandle) -> Result<String, String> {
    let state = app
        .try_state::<Mutex<String>>()
        .ok_or("display hedefi yok")?;
    let guard = state.lock().map_err(|e| e.to_string())?;
    Ok(guard.clone())
}

/// Kontrolü Al: gerçek `display_select` + wayvnc SSH tüneli + RFB izleyici.
#[tauri::command]
fn vnc_take(app: AppHandle) -> Result<Value, String> {
    let agent_id = display_target(&app)?;
    if agent_id.is_empty() {
        return Err("Önce ajan seçin".into());
    }
    let selection = agentd("display_select".into(), json!({ "agent_id": agent_id }))?;
    if !selection.get("ok").and_then(Value::as_bool).unwrap_or(false) {
        let detail = selection
            .get("detail")
            .and_then(Value::as_str)
            .unwrap_or("display_select başarısız");
        return Err(detail.to_string());
    }
    if !selection
        .get("live_view_available")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return Err("VDS canlı yüzeyi hazır değil (capability ready değil)".into());
    }
    let capability = selection
        .get("display_capability")
        .cloned()
        .unwrap_or_else(|| json!({}));
    let remote_port = capability
        .get("wayvnc_loopback_port")
        .and_then(Value::as_u64)
        .ok_or("capability gerçek wayvnc portu yayınlamadı")? as u16;
    spawn_watcher(&app, remote_port)?;
    Ok(selection)
}

/// Ajana Geri Ver: gerçek `display_release` + RFB izleyiciyi kapat.
#[tauri::command]
fn vnc_release(app: AppHandle) -> Result<Value, String> {
    let release = agentd("display_release".into(), json!({}))?;
    stop_watcher()?;
    let _ = app.emit(
        "show_base",
        json!({"state": "RELEASED", "detail": "Gerçek VDS yüzeyi bırakıldı"}),
    );
    Ok(release)
}

/// Ölü izleyiciyi düşürür; sonraki `vnc_take` yeni süreç başlatır.
#[tauri::command]
fn vnc_stop() -> Result<(), String> {
    stop_watcher()
}

/// İnsan girdisini gerçek RFB soketine yazar (pointer/key).
#[tauri::command]
fn vnc_input(
    kind: String,
    x: Option<i64>,
    y: Option<i64>,
    mask: Option<i64>,
    keysym: Option<i64>,
    down: Option<bool>,
) -> Result<(), String> {
    let payload = json!({
        "action": "input",
        "kind": kind,
        "x": x.unwrap_or(0),
        "y": y.unwrap_or(0),
        "mask": mask.unwrap_or(0),
        "keysym": keysym.unwrap_or(0),
        "down": down.unwrap_or(true),
    });
    send_watcher_line(&payload.to_string())
}

/// Seçili ajanın gerçek kare artifact'ini indirip veri URL'si olarak döner.
#[tauri::command]
fn fetch_frame(agent_id: String, frame_ref: String) -> Result<Value, String> {
    if agent_id.is_empty() || frame_ref.is_empty() {
        return Err("ajan ve frame referansı gerekli".into());
    }
    let root = project_root();
    let script = format!(
        "import json,sys;sys.path.insert(0, {root:?});from desktop.app.artifacts import ArtifactCache;from desktop.app.vds import VDSConfig;cache=ArtifactCache(VDSConfig());path=cache.fetch({ref:?}, {agent:?});print(json.dumps({{'path': str(path)}}))",
        root = root,
        ref = frame_ref,
        agent = agent_id,
    );
    let output = Command::new(venv_python(&root))
        .arg("-c")
        .arg(&script)
        .current_dir(&root)
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .map_err(|e| format!("frame alımı başlatılamadı: {e}"))?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).trim().to_string());
    }
    let parsed: Value = serde_json::from_slice(&output.stdout)
        .map_err(|e| format!("frame çıktısı çözülemedi: {e}"))?;
    let path = parsed
        .get("path")
        .and_then(Value::as_str)
        .ok_or("frame yolu yok")?
        .to_string();
    let bytes = std::fs::read(&path).map_err(|e| format!("frame okunamadı: {e}"))?;
    const CHARS: &[u8] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut encoded = String::with_capacity((bytes.len() + 2) / 3 * 4);
    for chunk in bytes.chunks(3) {
        let b = [
            chunk[0],
            *chunk.get(1).unwrap_or(&0),
            *chunk.get(2).unwrap_or(&0),
        ];
        let n = ((b[0] as u32) << 16) | ((b[1] as u32) << 8) | b[2] as u32;
        encoded.push(CHARS[(n >> 18) as usize & 63] as char);
        encoded.push(CHARS[(n >> 12) as usize & 63] as char);
        encoded.push(if chunk.len() > 1 {
            CHARS[(n >> 6) as usize & 63] as char
        } else {
            '='
        });
        encoded.push(if chunk.len() > 2 {
            CHARS[n as usize & 63] as char
        } else {
            '='
        });
    }
    Ok(json!({ "path": path, "data_url": format!("data:image/png;base64,{encoded}") }))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .setup(|app| {
            app.manage(Mutex::new(String::new()));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            agentd,
            set_display_target,
            vnc_take,
            vnc_release,
            vnc_stop,
            vnc_input,
            fetch_frame
        ])
        .run(tauri::generate_context!())
        .expect("PaidProxy kokpiti başlatılamadı");
}
