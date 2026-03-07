//! WebSocket server for web-vox — bridges browser to OS TTS.
//! Listens on ws://localhost:21740, accepts JSON messages per the web-vox protocol.
//!
//! Architecture: The main thread owns an NSRunLoop (required by AVSpeechSynthesizer)
//! and processes TTS requests from a channel. Tokio runs on a background thread
//! handling all WebSocket I/O.
//!
//! Run with: cargo run --bin web-vox-server

use std::collections::HashMap;
use std::io::Read as _;
use std::net::SocketAddr;
use std::sync::{mpsc, Mutex};
use std::time::Instant;

use futures_util::{SinkExt, StreamExt};
use sysinfo::{Pid, System};
use tokio::net::{TcpListener, TcpStream};
use tokio_tungstenite::tungstenite::Message;

use web_vox_protocol::*;
// VoiceSampleInfo, VoiceSampleList, VoiceSampleResult used in voice sample handlers

#[cfg(target_os = "macos")]
use web_vox_native_bridge::tts::macos::MacOsSynthesizer;
use web_vox_native_bridge::tts::chatterbox::ChatterboxSynthesizer;
use web_vox_native_bridge::tts::espeak::EspeakSynthesizer;
use web_vox_native_bridge::tts::coqui::CoquiSynthesizer;
use web_vox_native_bridge::tts::coqui_xtts::CoquiXttsSynthesizer;
use web_vox_native_bridge::tts::kokoro::KokoroSynthesizer;
use web_vox_native_bridge::tts::qwen::QwenSynthesizer;
use web_vox_native_bridge::tts::qwen_clone::QwenCloneSynthesizer;
use web_vox_native_bridge::tts::piper::PiperSynthesizer;
use web_vox_native_bridge::tts::voice_designer::VoiceDesignerClient;
use web_vox_native_bridge::tts::traits::{SynthesisOptions, TtsSynthesizer};

/// A TTS work request sent from a tokio task to the main thread.
struct TtsRequest {
    message: ClientMessage,
    reply: tokio::sync::oneshot::Sender<Vec<String>>,
}

// ── Server Process Manager ──────────────────────────────────────────────

struct ServerDef {
    engine: &'static str,
    name: &'static str,
    port: u16,
    python: &'static str,  // "python3.11" or "python3.12"
    script: &'static str,
    extra_args: &'static [&'static str],
}

const SERVER_DEFS: &[ServerDef] = &[
    ServerDef { engine: "chatterbox", name: "Chatterbox", port: 21741, python: "python3.11", script: "chatterbox_server.py", extra_args: &[] },
    ServerDef { engine: "kokoro", name: "Kokoro", port: 21742, python: "python3.11", script: "kokoro_server.py", extra_args: &[] },
    ServerDef { engine: "coqui", name: "Coqui VCTK", port: 21743, python: "python3.11", script: "coqui_server.py", extra_args: &["--model", "tts_models/en/vctk/vits"] },
    ServerDef { engine: "qwen", name: "Qwen3-TTS", port: 21744, python: "python3.12", script: "qwen_tts_server.py", extra_args: &[] },
    ServerDef { engine: "coqui-xtts", name: "Coqui XTTS v2", port: 21745, python: "python3.11", script: "coqui_xtts_server.py", extra_args: &["--lazy"] },
    ServerDef { engine: "qwen-clone", name: "Qwen3-TTS Clone", port: 21746, python: "python3.12", script: "qwen_tts_clone_server.py", extra_args: &["--lazy"] },
    ServerDef { engine: "alignment", name: "Forced Alignment", port: 21747, python: "python3.11", script: "alignment_server.py", extra_args: &["--preload"] },
    ServerDef { engine: "quality", name: "Quality Analysis", port: 21748, python: "python3.11", script: "quality_server.py", extra_args: &[] },
    ServerDef { engine: "voice-designer", name: "Voice Designer", port: 21749, python: "python3.11", script: "voice_designer_server.py", extra_args: &[] },
];

struct ManagedProcess {
    child: std::process::Child,
    started_at: Instant,
}

struct StatsHistory {
    cpu_history: Vec<f32>,
    memory_history: Vec<f64>,
    /// Timestamped log entries: (unix_epoch_secs, cpu%, memory_mb, online)
    usage_log: Vec<(u64, f32, f64, bool)>,
}

static MANAGED_PROCESSES: std::sync::LazyLock<Mutex<HashMap<String, ManagedProcess>>> =
    std::sync::LazyLock::new(|| Mutex::new(HashMap::new()));

static STATS_HISTORY: std::sync::LazyLock<Mutex<HashMap<String, StatsHistory>>> =
    std::sync::LazyLock::new(|| Mutex::new(HashMap::new()));

/// Background collector system — shared so the bg thread can refresh it
static BG_SYSINFO: std::sync::LazyLock<Mutex<System>> =
    std::sync::LazyLock::new(|| Mutex::new(System::new()));

const MAX_HISTORY: usize = 60;
/// Keep up to 360 log entries (~1 hour at 10s intervals)
const MAX_USAGE_LOG: usize = 360;

fn find_python_bin(python_version: &str) -> Option<std::path::PathBuf> {
    // Look for venv python first
    let cwd = std::env::current_dir().unwrap_or_default();
    for ancestor in cwd.ancestors() {
        let venv_name = if python_version.contains("3.12") { "qwen-tts-venv" } else { "tts-venv" };
        let candidate = ancestor.join(venv_name).join("bin").join(python_version);
        if candidate.exists() {
            return Some(candidate);
        }
    }
    // Fall back to system python
    if let Ok(output) = std::process::Command::new("which").arg(python_version).output() {
        let path = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if !path.is_empty() {
            return Some(std::path::PathBuf::from(path));
        }
    }
    None
}

fn find_scripts_dir() -> std::path::PathBuf {
    let cwd = std::env::current_dir().unwrap_or_default();
    for ancestor in cwd.ancestors() {
        let candidate = ancestor.join("packages").join("native-bridge");
        if candidate.join("kokoro_server.py").exists() {
            return candidate;
        }
    }
    cwd.join("packages").join("native-bridge")
}

fn kill_port(port: u16) {
    // Kill any existing process on the port
    if let Ok(output) = std::process::Command::new("lsof")
        .args(["-ti", &format!(":{port}")])
        .output()
    {
        let pids = String::from_utf8_lossy(&output.stdout);
        for pid_str in pids.split_whitespace() {
            if let Ok(pid) = pid_str.parse::<i32>() {
                let _ = std::process::Command::new("kill").arg(pid.to_string()).output();
            }
        }
    }
}

fn start_server(def: &ServerDef) -> Result<(), String> {
    let python_bin = find_python_bin(def.python)
        .ok_or_else(|| format!("Python binary '{}' not found", def.python))?;
    let scripts_dir = find_scripts_dir();
    let script_path = scripts_dir.join(def.script);
    if !script_path.exists() {
        return Err(format!("Script not found: {}", script_path.display()));
    }

    // Kill anything on the port first
    kill_port(def.port);
    std::thread::sleep(std::time::Duration::from_millis(500));

    let mut cmd = std::process::Command::new(&python_bin);
    cmd.arg(&script_path);
    cmd.args(["--port", &def.port.to_string()]);
    cmd.args(def.extra_args);
    cmd.stdout(std::process::Stdio::null());
    cmd.stderr(std::process::Stdio::null());

    let child = cmd.spawn().map_err(|e| format!("Failed to spawn {}: {e}", def.name))?;
    let pid = child.id();

    println!("  [server-mgr] Started {} (PID {}, port {})", def.name, pid, def.port);

    let mut managed = MANAGED_PROCESSES.lock().unwrap();
    managed.insert(def.engine.to_string(), ManagedProcess {
        child,
        started_at: Instant::now(),
    });

    Ok(())
}

fn stop_server(def: &ServerDef) -> Result<(), String> {
    // Kill managed process if we have one
    let mut managed = MANAGED_PROCESSES.lock().unwrap();
    if let Some(mut proc) = managed.remove(def.engine) {
        let _ = proc.child.kill();
        let _ = proc.child.wait();
        println!("  [server-mgr] Stopped managed {} (port {})", def.name, def.port);
    }
    // Also kill anything else on the port
    kill_port(def.port);
    Ok(())
}

fn find_pid_on_port(port: u16) -> Option<u32> {
    let output = std::process::Command::new("lsof")
        .args(["-ti", &format!(":{port}"), "-sTCP:LISTEN"])
        .output()
        .ok()?;
    let stdout = String::from_utf8_lossy(&output.stdout);
    stdout.split_whitespace().next()?.parse().ok()
}

fn collect_stats() -> Vec<ServerProcessStats> {
    // Use the background sysinfo — just read existing data, no heavy refresh here
    let sys = BG_SYSINFO.lock().unwrap();
    let managed = MANAGED_PROCESSES.lock().unwrap();
    let history = STATS_HISTORY.lock().unwrap();

    let mut stats = Vec::new();

    // WS server itself
    {
        let self_pid = std::process::id();
        let (cpu, mem) = if let Some(proc) = sys.process(Pid::from_u32(self_pid)) {
            (proc.cpu_usage(), proc.memory() as f64 / 1_048_576.0)
        } else {
            (0.0, 0.0)
        };

        let h = history.get("ws-server");
        let usage_log: Vec<UsageLogEntry> = h.map(|h| {
            h.usage_log.iter().map(|(ts, c, m, o)| UsageLogEntry {
                timestamp: *ts, cpu_percent: *c, memory_mb: *m, online: *o,
            }).collect()
        }).unwrap_or_default();

        stats.push(ServerProcessStats {
            engine: "ws-server".to_string(),
            name: "WebSocket Bridge".to_string(),
            port: 21740,
            online: true,
            pid: Some(self_pid),
            cpu_percent: cpu,
            memory_mb: mem,
            uptime_secs: 0,
            cpu_history: h.map(|h| h.cpu_history.clone()).unwrap_or_default(),
            memory_history: h.map(|h| h.memory_history.clone()).unwrap_or_default(),
            usage_log,
            managed: false,
        });
    }

    for def in SERVER_DEFS {
        let pid = managed.get(def.engine)
            .map(|p| p.child.id())
            .or_else(|| find_pid_on_port(def.port));

        let online = pid.is_some();
        let (cpu, mem) = if let Some(p) = pid.and_then(|p| sys.process(Pid::from_u32(p))) {
            (p.cpu_usage(), p.memory() as f64 / 1_048_576.0)
        } else {
            (0.0, 0.0)
        };

        let uptime = managed.get(def.engine)
            .map(|p| p.started_at.elapsed().as_secs())
            .unwrap_or(0);

        let is_managed = managed.contains_key(def.engine);

        let h = history.get(def.engine);
        let usage_log: Vec<UsageLogEntry> = h.map(|h| {
            h.usage_log.iter().map(|(ts, c, m, o)| UsageLogEntry {
                timestamp: *ts, cpu_percent: *c, memory_mb: *m, online: *o,
            }).collect()
        }).unwrap_or_default();

        stats.push(ServerProcessStats {
            engine: def.engine.to_string(),
            name: def.name.to_string(),
            port: def.port,
            online,
            pid,
            cpu_percent: cpu,
            memory_mb: mem,
            uptime_secs: uptime,
            cpu_history: h.map(|h| h.cpu_history.clone()).unwrap_or_default(),
            memory_history: h.map(|h| h.memory_history.clone()).unwrap_or_default(),
            usage_log,
            managed: is_managed,
        });
    }

    stats
}

/// Background stats collection — runs every 10 seconds on its own thread.
fn background_stats_collector() {
    loop {
        std::thread::sleep(std::time::Duration::from_secs(10));

        let mut sys = BG_SYSINFO.lock().unwrap();
        sys.refresh_processes(sysinfo::ProcessesToUpdate::All, true);

        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();

        let managed = MANAGED_PROCESSES.lock().unwrap();
        let mut history = STATS_HISTORY.lock().unwrap();

        // WS server itself
        {
            let self_pid = std::process::id();
            let (cpu, mem) = if let Some(proc) = sys.process(Pid::from_u32(self_pid)) {
                (proc.cpu_usage(), proc.memory() as f64 / 1_048_576.0)
            } else {
                (0.0, 0.0)
            };

            let h = history.entry("ws-server".to_string()).or_insert_with(|| StatsHistory {
                cpu_history: Vec::new(), memory_history: Vec::new(), usage_log: Vec::new(),
            });
            h.cpu_history.push(cpu);
            h.memory_history.push(mem);
            h.usage_log.push((now, cpu, mem, true));
            if h.cpu_history.len() > MAX_HISTORY { h.cpu_history.remove(0); }
            if h.memory_history.len() > MAX_HISTORY { h.memory_history.remove(0); }
            if h.usage_log.len() > MAX_USAGE_LOG { h.usage_log.remove(0); }
        }

        // Python servers
        for def in SERVER_DEFS {
            let pid = managed.get(def.engine)
                .map(|p| p.child.id())
                .or_else(|| find_pid_on_port(def.port));

            let online = pid.is_some();
            let (cpu, mem) = if let Some(p) = pid.and_then(|p| sys.process(Pid::from_u32(p))) {
                (p.cpu_usage(), p.memory() as f64 / 1_048_576.0)
            } else {
                (0.0, 0.0)
            };

            let h = history.entry(def.engine.to_string()).or_insert_with(|| StatsHistory {
                cpu_history: Vec::new(), memory_history: Vec::new(), usage_log: Vec::new(),
            });
            h.cpu_history.push(if online { cpu } else { 0.0 });
            h.memory_history.push(if online { mem } else { 0.0 });
            h.usage_log.push((now, cpu, mem, online));
            if h.cpu_history.len() > MAX_HISTORY { h.cpu_history.remove(0); }
            if h.memory_history.len() > MAX_HISTORY { h.memory_history.remove(0); }
            if h.usage_log.len() > MAX_USAGE_LOG { h.usage_log.remove(0); }
        }
    }
}

fn main() {
    env_logger::init();

    // Start background stats collector thread
    std::thread::spawn(background_stats_collector);
    println!("[stats] Background resource monitor started (10s interval)");

    // Channel: tokio tasks send TTS requests to main thread
    let (tx, rx) = mpsc::channel::<TtsRequest>();

    // Start tokio on a background thread
    let tokio_handle = std::thread::spawn(move || {
        let rt = tokio::runtime::Runtime::new().expect("Failed to create tokio runtime");
        rt.block_on(async {
            let addr: SocketAddr = "127.0.0.1:21740".parse().unwrap();
            let listener = TcpListener::bind(&addr).await.expect("Failed to bind");
            println!("web-vox server listening on ws://{addr}");
            println!("Press Ctrl+C to stop.\n");

            while let Ok((stream, peer)) = listener.accept().await {
                println!("[{peer}] Connected");
                let tx = tx.clone();
                tokio::spawn(handle_connection(stream, peer, tx));
            }
        });
    });

    // Main thread: process TTS requests with NSRunLoop
    run_main_thread_loop(rx);

    tokio_handle.join().unwrap();
}

/// Main thread loop — processes TTS requests.
/// On macOS this thread owns the NSRunLoop needed by AVSpeechSynthesizer.
fn run_main_thread_loop(rx: mpsc::Receiver<TtsRequest>) {
    loop {
        match rx.recv() {
            Ok(req) => {
                let responses = handle_message_sync(&req.message);
                let _ = req.reply.send(responses);
            }
            Err(_) => {
                // Channel closed — tokio shut down
                break;
            }
        }
    }
}

async fn handle_connection(
    stream: TcpStream,
    peer: SocketAddr,
    tts_tx: mpsc::Sender<TtsRequest>,
) {
    let ws_stream = match tokio_tungstenite::accept_hdr_async(
        stream,
        |_req: &http::Request<()>, mut resp: http::Response<()>| {
            resp.headers_mut().insert(
                "Access-Control-Allow-Origin",
                http::HeaderValue::from_static("*"),
            );
            Ok(resp)
        },
    )
    .await
    {
        Ok(ws) => ws,
        Err(e) => {
            eprintln!("[{peer}] WebSocket handshake failed: {e}");
            return;
        }
    };

    let (mut write, mut read) = ws_stream.split();

    while let Some(msg) = read.next().await {
        let msg = match msg {
            Ok(m) => m,
            Err(e) => {
                eprintln!("[{peer}] Read error: {e}");
                break;
            }
        };

        match msg {
            Message::Text(text) => {
                let responses = handle_message(&text, &tts_tx).await;
                for resp_json in responses {
                    if let Err(e) = write.send(Message::Text(resp_json.into())).await {
                        eprintln!("[{peer}] Send error: {e}");
                        return;
                    }
                }
            }
            Message::Close(_) => {
                println!("[{peer}] Disconnected");
                break;
            }
            _ => {}
        }
    }
}

/// Parse a JSON message and dispatch to the main thread for TTS work.
async fn handle_message(text: &str, tts_tx: &mpsc::Sender<TtsRequest>) -> Vec<String> {
    let client_msg: ClientMessage = match serde_json::from_str(text) {
        Ok(m) => m,
        Err(e) => {
            let err = HostMessage::Error(ErrorMessage {
                id: None,
                code: "PARSE_ERROR".into(),
                message: format!("Invalid JSON: {e}"),
            });
            return vec![serde_json::to_string(&err).unwrap()];
        }
    };

    // Send to main thread and await response
    let (reply_tx, reply_rx) = tokio::sync::oneshot::channel();
    let req = TtsRequest {
        message: client_msg,
        reply: reply_tx,
    };

    if tts_tx.send(req).is_err() {
        let err = HostMessage::Error(ErrorMessage {
            id: None,
            code: "INTERNAL_ERROR".into(),
            message: "TTS thread not available".into(),
        });
        return vec![serde_json::to_string(&err).unwrap()];
    }

    match reply_rx.await {
        Ok(responses) => responses,
        Err(_) => {
            let err = HostMessage::Error(ErrorMessage {
                id: None,
                code: "INTERNAL_ERROR".into(),
                message: "TTS request dropped".into(),
            });
            vec![serde_json::to_string(&err).unwrap()]
        }
    }
}

/// Process a message synchronously on the main thread (has NSRunLoop access).
fn handle_message_sync(msg: &ClientMessage) -> Vec<String> {
    match msg {
        ClientMessage::ListVoices => handle_list_voices(),
        ClientMessage::Synthesize(req) => handle_synthesize(req),
        ClientMessage::Cancel(_) => vec![],
        ClientMessage::GetSystemInfo => handle_system_info(),
        ClientMessage::ValidateVoice(req) => handle_validate_voice(req),
        ClientMessage::ListPiperCatalog => handle_piper_catalog(),
        ClientMessage::DownloadPiperVoice(req) => handle_download_piper_voice(req),
        ClientMessage::ListVoiceSamples => handle_list_voice_samples(),
        ClientMessage::UploadVoiceSample(req) => handle_upload_voice_sample(req),
        ClientMessage::DeleteVoiceSample(req) => handle_delete_voice_sample(req),
        ClientMessage::ManageServer(req) => handle_manage_server(req),
        ClientMessage::GetServerStats => handle_get_server_stats(),
        ClientMessage::DesignVoice(req) => handle_design_voice(req),
        ClientMessage::BlendVoices(req) => handle_blend_voices(req),
        ClientMessage::ListVoiceProfiles => handle_list_voice_profiles(),
        ClientMessage::SaveVoiceProfile(req) => handle_save_voice_profile(req),
        ClientMessage::DeleteVoiceProfile(req) => handle_delete_voice_profile(req),
    }
}

fn handle_list_voices() -> Vec<String> {
    let mut all_voices = Vec::new();

    // macOS AVSpeech voices
    #[cfg(target_os = "macos")]
    {
        let synth = MacOsSynthesizer::new();
        if let Ok(voices) = synth.list_voices() {
            all_voices.extend(voices);
        }
    }

    // Piper voices (from test-engines/piper/ and repo-root piper/)
    {
        let piper_dir = find_test_engines_dir().join("piper");
        if let Ok(mut piper) = PiperSynthesizer::new(&piper_dir) {
            if let Some(root_piper) = find_root_piper_dir() {
                piper.add_voices_dir(root_piper.join("voices"));
            }
            match piper.list_voices() {
                Ok(voices) => {
                    println!("  [piper] Found {} voice(s)", voices.len());
                    all_voices.extend(voices);
                }
                Err(e) => eprintln!("  [piper] Failed to list voices: {e}"),
            }
        } else if let Some(root_piper) = find_root_piper_dir() {
            // test-engines/piper doesn't exist, but repo-root piper/ does
            if let Ok(piper) = PiperSynthesizer::new(&root_piper) {
                match piper.list_voices() {
                    Ok(voices) => {
                        println!("  [piper] Found {} voice(s)", voices.len());
                        all_voices.extend(voices);
                    }
                    Err(e) => eprintln!("  [piper] Failed to list voices: {e}"),
                }
            }
        }
    }

    // espeak-ng voices
    {
        if let Ok(espeak) = EspeakSynthesizer::new() {
            match espeak.list_voices() {
                Ok(voices) => {
                    println!("  [espeak-ng] Found {} voice(s)", voices.len());
                    all_voices.extend(voices);
                }
                Err(e) => eprintln!("  [espeak-ng] Failed to list voices: {e}"),
            }
        }
    }

    // Chatterbox voices (from Python server)
    {
        let samples_dir = find_voice_samples_dir();
        if let Ok(cb) = ChatterboxSynthesizer::new(None, &samples_dir) {
            if cb.probe() {
                match cb.list_voices() {
                    Ok(voices) => {
                        println!("  [chatterbox] Found {} voice(s)", voices.len());
                        all_voices.extend(voices);
                    }
                    Err(e) => eprintln!("  [chatterbox] Failed to list voices: {e}"),
                }
            } else {
                println!("  [chatterbox] Server not running (start chatterbox_server.py to enable)");
            }
        }
    }

    // Kokoro voices (from Python server)
    {
        let kokoro = KokoroSynthesizer::new(None);
        if kokoro.probe() {
            match kokoro.list_voices() {
                Ok(voices) => {
                    println!("  [kokoro] Found {} voice(s)", voices.len());
                    all_voices.extend(voices);
                }
                Err(e) => eprintln!("  [kokoro] Failed to list voices: {e}"),
            }
        } else {
            println!("  [kokoro] Server not running (start kokoro_server.py to enable)");
        }
    }

    // Coqui TTS voices (from Python server)
    {
        let coqui = CoquiSynthesizer::new(None);
        if coqui.probe() {
            match coqui.list_voices() {
                Ok(voices) => {
                    println!("  [coqui] Found {} voice(s)", voices.len());
                    all_voices.extend(voices);
                }
                Err(e) => eprintln!("  [coqui] Failed to list voices: {e}"),
            }
        } else {
            println!("  [coqui] Server not running (start coqui_server.py to enable)");
        }
    }

    // Qwen3-TTS voices (from Python server)
    {
        let qwen = QwenSynthesizer::new(None);
        if qwen.probe() {
            match qwen.list_voices() {
                Ok(voices) => {
                    println!("  [qwen-tts] Found {} voice(s)", voices.len());
                    all_voices.extend(voices);
                }
                Err(e) => eprintln!("  [qwen-tts] Failed to list voices: {e}"),
            }
        } else {
            println!("  [qwen-tts] Server not running (start qwen_tts_server.py to enable)");
        }
    }

    // Coqui XTTS v2 cloned voices (from Python server)
    {
        let xtts = CoquiXttsSynthesizer::new(None);
        if xtts.probe() {
            match xtts.list_voices() {
                Ok(voices) => {
                    println!("  [coqui-xtts] Found {} voice(s)", voices.len());
                    all_voices.extend(voices);
                }
                Err(e) => eprintln!("  [coqui-xtts] Failed to list voices: {e}"),
            }
        } else {
            println!("  [coqui-xtts] Server not running (start coqui_xtts_server.py to enable)");
        }
    }

    // Qwen3-TTS Base cloned voices (from Python server)
    {
        let qwen_clone = QwenCloneSynthesizer::new(None);
        if qwen_clone.probe() {
            match qwen_clone.list_voices() {
                Ok(voices) => {
                    println!("  [qwen-clone] Found {} voice(s)", voices.len());
                    all_voices.extend(voices);
                }
                Err(e) => eprintln!("  [qwen-clone] Failed to list voices: {e}"),
            }
        } else {
            println!("  [qwen-clone] Server not running (start qwen_tts_clone_server.py to enable)");
        }
    }

    if all_voices.is_empty() {
        let msg = HostMessage::Error(ErrorMessage {
            id: None,
            code: "NO_VOICES".into(),
            message: "No TTS engines available".into(),
        });
        vec![serde_json::to_string(&msg).unwrap()]
    } else {
        let msg = HostMessage::VoiceList(VoiceList { voices: all_voices });
        vec![serde_json::to_string(&msg).unwrap()]
    }
}

fn handle_synthesize(req: &SynthesizeRequest) -> Vec<String> {
    let id = req.id.clone();
    let mut responses = Vec::new();
    println!("  Request: rate={}, pitch={}, voice={:?}", req.rate, req.pitch, req.voice_id);

    // Determine which engine to use based on voice ID prefix
    let voice_id = req.voice_id.as_deref().unwrap_or("");
    let engine = if voice_id.starts_with("chatterbox:") {
        "chatterbox"
    } else if voice_id.starts_with("piper:") {
        "piper"
    } else if voice_id.starts_with("espeak-ng:") {
        "espeak-ng"
    } else if voice_id.starts_with("kokoro:") {
        "kokoro"
    } else if voice_id.starts_with("coqui-xtts:") {
        "coqui-xtts"
    } else if voice_id.starts_with("coqui:") {
        "coqui"
    } else if voice_id.starts_with("qwen-clone:") {
        "qwen-clone"
    } else if voice_id.starts_with("qwen:") {
        "qwen"
    } else {
        "macos"
    };

    let options = SynthesisOptions {
        voice_id: req.voice_id.clone(),
        rate: req.rate,
        pitch: req.pitch,
        volume: req.volume,
    };

    // Synthesize using the appropriate engine
    let synth_result = match engine {
        "chatterbox" => {
            let samples_dir = find_voice_samples_dir();
            match ChatterboxSynthesizer::new(None, &samples_dir) {
                Ok(cb) => cb.synthesize(&req.text, &id, &options),
                Err(e) => Err(e),
            }
        }
        "piper" => {
            let piper_dir = find_test_engines_dir().join("piper");
            let try_test_engines = PiperSynthesizer::new(&piper_dir);
            let try_root = find_root_piper_dir().and_then(|d| PiperSynthesizer::new(&d).ok());
            match (try_test_engines, try_root) {
                (Ok(mut piper), root) => {
                    if let Some(root_piper) = root {
                        for dir in root_piper.voices_dirs() {
                            piper.add_voices_dir(dir.to_path_buf());
                        }
                    }
                    piper.synthesize(&req.text, &id, &options)
                }
                (Err(_), Some(piper)) => piper.synthesize(&req.text, &id, &options),
                (Err(e), None) => Err(e),
            }
        }
        "espeak-ng" => {
            match EspeakSynthesizer::new() {
                Ok(espeak) => espeak.synthesize(&req.text, &id, &options),
                Err(e) => Err(e),
            }
        }
        "kokoro" => {
            let kokoro = KokoroSynthesizer::new(None);
            kokoro.synthesize(&req.text, &id, &options)
        }
        "coqui" => {
            let coqui = CoquiSynthesizer::new(None);
            coqui.synthesize(&req.text, &id, &options)
        }
        "qwen" => {
            let qwen = QwenSynthesizer::new(None);
            qwen.synthesize(&req.text, &id, &options)
        }
        "coqui-xtts" => {
            let xtts = CoquiXttsSynthesizer::new(None);
            xtts.synthesize(&req.text, &id, &options)
        }
        "qwen-clone" => {
            let qwen_clone = QwenCloneSynthesizer::new(None);
            qwen_clone.synthesize(&req.text, &id, &options)
        }
        _ => {
            // macOS AVSpeech — synthesize at 1.0x, then sonic time-stretch
            #[cfg(target_os = "macos")]
            {
                let synth = MacOsSynthesizer::new();
                let macos_options = SynthesisOptions {
                    voice_id: req.voice_id.clone(),
                    rate: 1.0,
                    pitch: req.pitch,
                    volume: req.volume,
                };
                synth.synthesize(&req.text, &id, &macos_options)
            }
            #[cfg(not(target_os = "macos"))]
            {
                Err(web_vox_native_bridge::tts::traits::TtsError::NotAvailable(
                    "TTS not supported on this platform yet".into(),
                ))
            }
        }
    };

    match synth_result {
        Ok(output) => {
            // ── Forced alignment ─────────────────────────────────────────
            // Replace the engine's naive word boundaries with accurate ones
            // from the alignment server (if available and requested).
            let word_boundaries = if req.alignment != "none" {
                let alignment_client =
                    web_vox_native_bridge::tts::alignment::AlignmentClient::new(None);
                match alignment_client.align(
                    &output.samples,
                    output.sample_rate,
                    output.channels,
                    &req.text,
                    &id,
                    &req.alignment,
                ) {
                    Ok(aligned) => {
                        println!(
                            "  [alignment] Replaced {} naive boundaries with {} aligned ones",
                            output.word_boundaries.len(),
                            aligned.len()
                        );
                        aligned
                    }
                    Err(e) => {
                        println!(
                            "  [alignment] Alignment unavailable ({}), using engine boundaries",
                            e
                        );
                        output.word_boundaries.clone()
                    }
                }
            } else {
                output.word_boundaries.clone()
            };

            // ── Quality analysis ─────────────────────────────────────────
            // Run quality analysis on the raw (pre-stretched) audio if requested.
            if req.analyze_quality {
                let quality_client =
                    web_vox_native_bridge::tts::quality::QualityClient::new(None);
                let analyzers: Option<Vec<&str>> = if req.quality_analyzers.is_empty() {
                    None
                } else {
                    Some(req.quality_analyzers.iter().map(|s| s.as_str()).collect())
                };
                match quality_client.analyze(
                    &output.samples,
                    output.sample_rate,
                    output.channels,
                    &req.text,
                    &id,
                    analyzers.as_deref(),
                ) {
                    Ok(analysis) => {
                        let qs = QualityScore {
                            id: id.clone(),
                            overall_score: analysis.overall.score,
                            overall_rating: analysis.overall.rating.clone(),
                            asr_confidence: analysis.asr.as_ref().and_then(|a| a.confidence),
                            asr_wer: analysis.asr.as_ref().and_then(|a| a.wer),
                            asr_hypothesis: analysis.asr.as_ref().and_then(|a| a.hypothesis.clone()),
                            mos: analysis.mos.as_ref().and_then(|m| m.mos),
                            mos_rating: analysis.mos.as_ref().and_then(|m| m.rating.clone()),
                            snr_db: analysis.signal.as_ref().map(|s| s.snr_db),
                            clip_ratio: analysis.signal.as_ref().map(|s| s.clip_ratio),
                            silence_ratio: analysis.signal.as_ref().map(|s| s.silence_ratio),
                            f0_mean_hz: analysis.prosody.as_ref()
                                .and_then(|p| p.f0.as_ref())
                                .and_then(|f| f.mean_hz),
                            f0_range_hz: analysis.prosody.as_ref()
                                .and_then(|p| p.f0.as_ref())
                                .and_then(|f| f.range_hz),
                            artifacts: analysis.signal.as_ref()
                                .map(|s| s.artifacts.iter().map(|a| QualityArtifact {
                                    artifact_type: a.artifact_type.clone(),
                                    severity: a.severity.clone(),
                                    detail: a.detail.clone(),
                                }).collect())
                                .unwrap_or_default(),
                            recommendations: analysis.recommendations,
                        };
                        let msg = HostMessage::QualityScore(qs);
                        responses.push(serde_json::to_string(&msg).unwrap());
                    }
                    Err(e) => {
                        println!(
                            "  [quality] Analysis unavailable ({}), skipping",
                            e
                        );
                    }
                }
            }

            // ── Sonic time-stretching ────────────────────────────────────
            let speed = req.rate;
            let use_sonic = (speed - 1.0).abs() > 0.01;
            let (final_samples, final_duration_ms) = if use_sonic {
                println!("  Applying sonic time-stretch: {:.1}x speed", speed);
                let stretched = web_vox_native_bridge::audio::sonic::time_stretch(
                    &output.samples,
                    output.sample_rate,
                    output.channels,
                    speed,
                );
                let duration_ms = if output.sample_rate > 0 && output.channels > 0 {
                    let frames = stretched.len() as f64 / output.channels as f64;
                    (frames / output.sample_rate as f64) * 1000.0
                } else {
                    0.0
                };
                (stretched, duration_ms)
            } else {
                (output.samples.clone(), output.total_duration_ms)
            };

            // Scale word boundary timings by 1/speed for sonic-stretched audio
            for wb in &word_boundaries {
                let mut scaled_wb = wb.clone();
                if use_sonic {
                    scaled_wb.start_time_ms /= speed as f64;
                    scaled_wb.end_time_ms /= speed as f64;
                    // Also scale syllable and phoneme timings
                    if let Some(ref mut syllables) = scaled_wb.syllables {
                        for s in syllables.iter_mut() {
                            s.start_time_ms /= speed as f64;
                            s.end_time_ms /= speed as f64;
                        }
                    }
                    if let Some(ref mut phonemes) = scaled_wb.phonemes {
                        for p in phonemes.iter_mut() {
                            p.start_time_ms /= speed as f64;
                            p.end_time_ms /= speed as f64;
                        }
                    }
                }
                let msg = HostMessage::WordBoundary(scaled_wb);
                responses.push(serde_json::to_string(&msg).unwrap());
            }

            let chunks = web_vox_native_bridge::audio::encoder::encode_chunks(
                &id,
                &final_samples,
                output.sample_rate,
                output.channels,
            );
            for chunk in chunks {
                let msg = HostMessage::AudioChunk(chunk);
                responses.push(serde_json::to_string(&msg).unwrap());
            }

            let msg = HostMessage::SynthesisComplete(SynthesisComplete {
                id: id.clone(),
                total_duration_ms: final_duration_ms,
            });
            responses.push(serde_json::to_string(&msg).unwrap());

            println!(
                "  [{}] Synthesized \"{}\" -> {:.1}s, {} samples",
                engine,
                truncate(&req.text, 40),
                final_duration_ms / 1000.0,
                final_samples.len()
            );
        }
        Err(e) => {
            eprintln!("  [{}] Synthesis error: {}", engine, e);
            let msg = HostMessage::Error(ErrorMessage {
                id: Some(id),
                code: "SYNTHESIS_ERROR".into(),
                message: e.to_string(),
            });
            responses.push(serde_json::to_string(&msg).unwrap());
        }
    }

    responses
}

fn handle_system_info() -> Vec<String> {
    let mut available_engines = Vec::new();

    #[cfg(target_os = "macos")]
    available_engines.push("macos-avspeech".to_string());

    {
        let piper_dir = find_test_engines_dir().join("piper");
        if piper_dir.join("piper").exists() || piper_dir.join("piper.exe").exists() {
            available_engines.push("piper".to_string());
        }
    }
    {
        if EspeakSynthesizer::new().is_ok() {
            available_engines.push("espeak-ng".to_string());
        }
    }
    {
        let samples_dir = find_voice_samples_dir();
        if let Ok(cb) = ChatterboxSynthesizer::new(None, &samples_dir) {
            if cb.probe() {
                available_engines.push("chatterbox".to_string());
            }
        }
    }
    {
        let kokoro = KokoroSynthesizer::new(None);
        if kokoro.probe() {
            available_engines.push("kokoro".to_string());
        }
    }
    {
        let coqui = CoquiSynthesizer::new(None);
        if coqui.probe() {
            available_engines.push("coqui".to_string());
        }
    }
    {
        let qwen = QwenSynthesizer::new(None);
        if qwen.probe() {
            available_engines.push("qwen".to_string());
        }
    }
    {
        let xtts = CoquiXttsSynthesizer::new(None);
        if xtts.probe() {
            available_engines.push("coqui-xtts".to_string());
        }
    }
    {
        let qwen_clone = QwenCloneSynthesizer::new(None);
        if qwen_clone.probe() {
            available_engines.push("qwen-clone".to_string());
        }
    }

    let info = SystemInfo {
        os: std::env::consts::OS.to_string(),
        os_version: get_os_version(),
        arch: std::env::consts::ARCH.to_string(),
        cpu_cores: std::thread::available_parallelism()
            .map(|p| p.get())
            .unwrap_or(1),
        available_engines,
        hostname: hostname::get()
            .map(|h| h.to_string_lossy().to_string())
            .unwrap_or_default(),
    };

    let msg = HostMessage::SystemInfo(info);
    vec![serde_json::to_string(&msg).unwrap()]
}

fn get_os_version() -> String {
    #[cfg(target_os = "macos")]
    {
        if let Ok(output) = std::process::Command::new("sw_vers")
            .arg("-productVersion")
            .output()
        {
            return String::from_utf8_lossy(&output.stdout).trim().to_string();
        }
    }
    #[cfg(target_os = "linux")]
    {
        if let Ok(content) = std::fs::read_to_string("/etc/os-release") {
            for line in content.lines() {
                if let Some(v) = line.strip_prefix("PRETTY_NAME=") {
                    return v.trim_matches('"').to_string();
                }
            }
        }
    }
    "unknown".to_string()
}

fn handle_validate_voice(req: &ValidateVoiceRequest) -> Vec<String> {
    let voice_id = &req.voice_id;
    let engine = if voice_id.starts_with("chatterbox:") {
        "chatterbox"
    } else if voice_id.starts_with("piper:") {
        "piper"
    } else if voice_id.starts_with("espeak-ng:") {
        "espeak-ng"
    } else if voice_id.starts_with("kokoro:") {
        "kokoro"
    } else if voice_id.starts_with("coqui-xtts:") {
        "coqui-xtts"
    } else if voice_id.starts_with("coqui:") {
        "coqui"
    } else if voice_id.starts_with("qwen-clone:") {
        "qwen-clone"
    } else if voice_id.starts_with("qwen:") {
        "qwen"
    } else {
        "macos"
    };

    let options = SynthesisOptions {
        voice_id: Some(voice_id.clone()),
        rate: 1.0,
        pitch: 1.0,
        volume: 1.0,
    };

    // Try a minimal synthesis to validate
    let result = match engine {
        "chatterbox" => {
            let samples_dir = find_voice_samples_dir();
            match ChatterboxSynthesizer::new(None, &samples_dir) {
                Ok(cb) => {
                    if cb.probe() {
                        cb.synthesize("test", "validate", &options)
                    } else {
                        Err(web_vox_native_bridge::tts::traits::TtsError::NotAvailable(
                            "Chatterbox server not running".into(),
                        ))
                    }
                }
                Err(e) => Err(e),
            }
        }
        "piper" => {
            let piper_dir = find_test_engines_dir().join("piper");
            let try_test_engines = PiperSynthesizer::new(&piper_dir);
            let try_root = find_root_piper_dir().and_then(|d| PiperSynthesizer::new(&d).ok());
            match (try_test_engines, try_root) {
                (Ok(mut piper), root) => {
                    if let Some(root_piper) = root {
                        for dir in root_piper.voices_dirs() {
                            piper.add_voices_dir(dir.to_path_buf());
                        }
                    }
                    piper.synthesize("test", "validate", &options)
                }
                (Err(_), Some(piper)) => piper.synthesize("test", "validate", &options),
                (Err(e), None) => Err(e),
            }
        }
        "espeak-ng" => {
            match EspeakSynthesizer::new() {
                Ok(espeak) => espeak.synthesize("test", "validate", &options),
                Err(e) => Err(e),
            }
        }
        "kokoro" => {
            let kokoro = KokoroSynthesizer::new(None);
            if kokoro.probe() {
                kokoro.synthesize("test", "validate", &options)
            } else {
                Err(web_vox_native_bridge::tts::traits::TtsError::NotAvailable(
                    "Kokoro server not running".into(),
                ))
            }
        }
        "coqui" => {
            let coqui = CoquiSynthesizer::new(None);
            if coqui.probe() {
                coqui.synthesize("test", "validate", &options)
            } else {
                Err(web_vox_native_bridge::tts::traits::TtsError::NotAvailable(
                    "Coqui server not running".into(),
                ))
            }
        }
        "qwen" => {
            let qwen = QwenSynthesizer::new(None);
            if qwen.probe() {
                qwen.synthesize("test", "validate", &options)
            } else {
                Err(web_vox_native_bridge::tts::traits::TtsError::NotAvailable(
                    "Qwen3-TTS server not running".into(),
                ))
            }
        }
        "coqui-xtts" => {
            let xtts = CoquiXttsSynthesizer::new(None);
            if xtts.probe() {
                xtts.synthesize("test", "validate", &options)
            } else {
                Err(web_vox_native_bridge::tts::traits::TtsError::NotAvailable(
                    "Coqui XTTS server not running".into(),
                ))
            }
        }
        "qwen-clone" => {
            let qwen_clone = QwenCloneSynthesizer::new(None);
            if qwen_clone.probe() {
                qwen_clone.synthesize("test", "validate", &options)
            } else {
                Err(web_vox_native_bridge::tts::traits::TtsError::NotAvailable(
                    "Qwen3-TTS Clone server not running".into(),
                ))
            }
        }
        _ => {
            #[cfg(target_os = "macos")]
            {
                let synth = MacOsSynthesizer::new();
                synth.synthesize("test", "validate", &options)
            }
            #[cfg(not(target_os = "macos"))]
            {
                Err(web_vox_native_bridge::tts::traits::TtsError::NotAvailable(
                    "macOS TTS not available on this platform".into(),
                ))
            }
        }
    };

    let validation = match result {
        Ok(_) => VoiceValidation {
            voice_id: voice_id.clone(),
            valid: true,
            error: None,
            suggestion: None,
        },
        Err(e) => {
            let suggestion = match engine {
                "chatterbox" => Some(format!(
                    "Ensure the Chatterbox server is running: \
                     cd packages/native-bridge && python3 chatterbox_server.py"
                )),
                "piper" => Some(format!(
                    "Ensure the Piper model file exists in test-engines/piper/voices/. \
                     Download models from https://github.com/rhasspy/piper/releases"
                )),
                "espeak-ng" => Some(format!(
                    "Install espeak-ng: brew install espeak-ng (macOS) or \
                     apt install espeak-ng (Linux)"
                )),
                "kokoro" => Some(format!(
                    "Ensure the Kokoro server is running: \
                     cd packages/native-bridge && python3 kokoro_server.py"
                )),
                "coqui" => Some(format!(
                    "Ensure the Coqui TTS server is running: \
                     cd packages/native-bridge && python3 coqui_server.py"
                )),
                "qwen" => Some(format!(
                    "Ensure the Qwen3-TTS server is running: \
                     cd packages/native-bridge && python3.12 qwen_tts_server.py"
                )),
                "coqui-xtts" => Some(format!(
                    "Ensure the Coqui XTTS server is running: \
                     cd packages/native-bridge && python3 coqui_xtts_server.py"
                )),
                "qwen-clone" => Some(format!(
                    "Ensure the Qwen3-TTS Clone server is running: \
                     cd packages/native-bridge && python3.12 qwen_tts_clone_server.py"
                )),
                _ => {
                    if voice_id.contains("premium") || voice_id.contains("enhanced") {
                        Some(format!(
                            "This voice may require downloading in System Settings > \
                             Accessibility > Spoken Content > System Voice > Manage Voices"
                        ))
                    } else {
                        Some(format!(
                            "This voice may not be installed. On macOS, go to System Settings > \
                             Accessibility > Spoken Content > System Voice > Manage Voices to \
                             download it."
                        ))
                    }
                }
            };
            VoiceValidation {
                voice_id: voice_id.clone(),
                valid: false,
                error: Some(e.to_string()),
                suggestion,
            }
        }
    };

    let msg = HostMessage::VoiceValidation(validation);
    vec![serde_json::to_string(&msg).unwrap()]
}

// ── Piper catalog & download ─────────────────────────────────────────────

const PIPER_VOICES_JSON_URL: &str =
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/voices.json";
const PIPER_VOICES_BASE_URL: &str =
    "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/";

fn fetch_piper_catalog_json() -> Result<serde_json::Value, String> {
    let mut resp = ureq::get(PIPER_VOICES_JSON_URL)
        .call()
        .map_err(|e| format!("Failed to fetch Piper voice catalog: {e}"))?;
    let body = resp
        .body_mut()
        .read_to_string()
        .map_err(|e| format!("Failed to read catalog response: {e}"))?;
    serde_json::from_str(&body).map_err(|e| format!("Failed to parse catalog JSON: {e}"))
}

fn download_file_bytes(url: &str) -> Result<Vec<u8>, String> {
    let mut resp = ureq::get(url)
        .call()
        .map_err(|e| format!("HTTP request failed: {e}"))?;
    let mut bytes = Vec::new();
    resp.body_mut()
        .as_reader()
        .read_to_end(&mut bytes)
        .map_err(|e| format!("Failed to read response body: {e}"))?;
    Ok(bytes)
}

fn handle_piper_catalog() -> Vec<String> {
    println!("  [piper] Fetching voice catalog from HuggingFace...");

    let catalog = match fetch_piper_catalog_json() {
        Ok(v) => v,
        Err(e) => {
            let msg = HostMessage::Error(ErrorMessage {
                id: None,
                code: "PIPER_CATALOG_ERROR".into(),
                message: e,
            });
            return vec![serde_json::to_string(&msg).unwrap()];
        }
    };

    let voices_dir = find_test_engines_dir().join("piper").join("voices");
    let mut voices = Vec::new();

    if let Some(obj) = catalog.as_object() {
        for (key, entry) in obj {
            let name = entry.get("name")
                .and_then(|v| v.as_str())
                .unwrap_or(key)
                .to_string();

            let language = entry.get("language")
                .and_then(|l| l.get("code"))
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
                .to_string();

            let language_name = entry.get("language")
                .and_then(|l| l.get("name_english"))
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();

            let quality = entry.get("quality")
                .and_then(|v| v.as_str())
                .unwrap_or("unknown")
                .to_string();

            let num_speakers = entry.get("num_speakers")
                .and_then(|v| v.as_u64())
                .unwrap_or(1) as u32;

            let size_bytes = entry.get("files")
                .and_then(|f| f.as_object())
                .map(|files| {
                    files.values()
                        .filter_map(|f| f.get("size_bytes").and_then(|s| s.as_u64()))
                        .sum::<u64>()
                })
                .unwrap_or(0);

            let onnx_name = format!("{key}.onnx");
            let installed = voices_dir.join(&onnx_name).exists();

            voices.push(PiperCatalogVoice {
                key: key.clone(),
                name,
                language,
                language_name,
                quality,
                num_speakers,
                size_bytes,
                installed,
            });
        }
    }

    voices.sort_by(|a, b| a.language.cmp(&b.language).then(a.name.cmp(&b.name)));
    println!("  [piper] Catalog: {} voices available", voices.len());

    let msg = HostMessage::PiperCatalog(PiperCatalog { voices });
    vec![serde_json::to_string(&msg).unwrap()]
}

fn handle_download_piper_voice(req: &DownloadPiperVoiceRequest) -> Vec<String> {
    let key = &req.key;
    println!("  [piper] Downloading voice: {key}");

    let voices_dir = find_test_engines_dir().join("piper").join("voices");
    if let Err(e) = std::fs::create_dir_all(&voices_dir) {
        return vec![piper_download_err(key, &format!("Failed to create voices directory: {e}"))];
    }

    let catalog = match fetch_piper_catalog_json() {
        Ok(v) => v,
        Err(e) => return vec![piper_download_err(key, &e)],
    };

    let voice_entry = match catalog.get(key) {
        Some(v) => v,
        None => return vec![piper_download_err(key, &format!("Voice '{key}' not found in catalog"))],
    };

    let files = match voice_entry.get("files").and_then(|f| f.as_object()) {
        Some(f) => f,
        None => return vec![piper_download_err(key, "No files listed for this voice")],
    };

    for file_path in files.keys() {
        let url = format!("{PIPER_VOICES_BASE_URL}{file_path}");
        let file_name = std::path::Path::new(file_path)
            .file_name()
            .map(|n| n.to_string_lossy().to_string())
            .unwrap_or_else(|| file_path.clone());
        let dest = voices_dir.join(&file_name);

        println!("  [piper] Downloading {file_name}...");

        let bytes = match download_file_bytes(&url) {
            Ok(b) => b,
            Err(e) => return vec![piper_download_err(key, &format!("Failed to download {file_name}: {e}"))],
        };

        if let Err(e) = std::fs::write(&dest, &bytes) {
            return vec![piper_download_err(key, &format!("Failed to write {file_name}: {e}"))];
        }

        println!("  [piper] Saved {} ({:.1} MB)", file_name, bytes.len() as f64 / 1_048_576.0);
    }

    println!("  [piper] Voice '{key}' downloaded successfully");

    let msg = HostMessage::PiperDownloadComplete(PiperDownloadResult {
        key: key.clone(),
        success: true,
        error: None,
    });
    vec![serde_json::to_string(&msg).unwrap()]
}

fn piper_download_err(key: &str, error: &str) -> String {
    let msg = HostMessage::PiperDownloadComplete(PiperDownloadResult {
        key: key.to_string(),
        success: false,
        error: Some(error.to_string()),
    });
    serde_json::to_string(&msg).unwrap()
}

/// Locate the `test-engines/` directory relative to the workspace root.
/// Walks up from the current exe or cwd looking for the directory.
/// Find a repo-root `piper/` directory (separate from test-engines/piper/).
fn find_root_piper_dir() -> Option<std::path::PathBuf> {
    let cwd = std::env::current_dir().unwrap_or_default();
    for ancestor in cwd.ancestors() {
        let candidate = ancestor.join("piper");
        // Distinguish from test-engines/piper by checking for the voices subdir directly
        if candidate.is_dir() && candidate.join("voices").is_dir() {
            return Some(candidate);
        }
    }
    None
}

fn find_test_engines_dir() -> std::path::PathBuf {
    // Try relative to current working directory first
    let cwd = std::env::current_dir().unwrap_or_default();
    for ancestor in cwd.ancestors() {
        let candidate = ancestor.join("test-engines");
        if candidate.is_dir() {
            return candidate;
        }
    }
    // Fallback: relative to executable
    if let Ok(exe) = std::env::current_exe() {
        for ancestor in exe.ancestors() {
            let candidate = ancestor.join("test-engines");
            if candidate.is_dir() {
                return candidate;
            }
        }
    }
    // Last resort
    cwd.join("test-engines")
}

// ── Voice sample management ──────────────────────────────────────────────

fn find_voice_samples_dir() -> std::path::PathBuf {
    let cwd = std::env::current_dir().unwrap_or_default();
    for ancestor in cwd.ancestors() {
        let candidate = ancestor.join("packages").join("native-bridge").join("voice-samples");
        if candidate.is_dir() {
            return candidate;
        }
    }
    // Fallback: create relative to cwd
    let dir = cwd.join("packages").join("native-bridge").join("voice-samples");
    let _ = std::fs::create_dir_all(&dir);
    dir
}

fn handle_list_voice_samples() -> Vec<String> {
    let samples_dir = find_voice_samples_dir();
    let cb = match ChatterboxSynthesizer::new(None, &samples_dir) {
        Ok(cb) => cb,
        Err(e) => {
            let msg = HostMessage::Error(ErrorMessage {
                id: None,
                code: "CHATTERBOX_ERROR".into(),
                message: e.to_string(),
            });
            return vec![serde_json::to_string(&msg).unwrap()];
        }
    };

    match cb.list_samples() {
        Ok(samples) => {
            let infos: Vec<VoiceSampleInfo> = samples
                .into_iter()
                .map(|s| VoiceSampleInfo {
                    name: s.name,
                    filename: s.filename,
                    size_bytes: s.size_bytes,
                })
                .collect();
            let msg = HostMessage::VoiceSamples(VoiceSampleList { samples: infos });
            vec![serde_json::to_string(&msg).unwrap()]
        }
        Err(_) => {
            // Chatterbox server not running — read from disk directly
            let mut infos = Vec::new();
            if let Ok(entries) = std::fs::read_dir(&samples_dir) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if let Some(ext) = path.extension() {
                        if ["wav", "flac", "mp3", "ogg"].contains(&ext.to_str().unwrap_or("")) {
                            if let Ok(meta) = path.metadata() {
                                infos.push(VoiceSampleInfo {
                                    name: path.file_stem().unwrap().to_string_lossy().to_string(),
                                    filename: path.file_name().unwrap().to_string_lossy().to_string(),
                                    size_bytes: meta.len(),
                                });
                            }
                        }
                    }
                }
            }
            infos.sort_by(|a, b| a.name.cmp(&b.name));
            let msg = HostMessage::VoiceSamples(VoiceSampleList { samples: infos });
            vec![serde_json::to_string(&msg).unwrap()]
        }
    }
}

fn handle_upload_voice_sample(req: &UploadVoiceSampleRequest) -> Vec<String> {
    let name = &req.name;
    println!("  [chatterbox] Uploading voice sample: {name}");

    // Decode base64 WAV data
    let wav_data = match web_vox_protocol::decode_audio_base64(&req.data_base64) {
        Ok(data) => data,
        Err(e) => {
            let msg = HostMessage::VoiceSampleResult(VoiceSampleResult {
                name: name.clone(),
                success: false,
                error: Some(format!("Invalid base64 data: {e}")),
            });
            return vec![serde_json::to_string(&msg).unwrap()];
        }
    };

    // Try server upload first, fall back to direct disk write
    let samples_dir = find_voice_samples_dir();
    let cb = ChatterboxSynthesizer::new(None, &samples_dir);

    let result = if let Ok(ref cb) = cb {
        if cb.probe() {
            cb.upload_sample(name, &wav_data)
                .map(|_| ())
                .map_err(|e| e.to_string())
        } else {
            save_sample_to_disk(name, &wav_data, &samples_dir)
        }
    } else {
        save_sample_to_disk(name, &wav_data, &samples_dir)
    };

    let msg = match result {
        Ok(()) => {
            println!("  [chatterbox] Voice sample saved: {name} ({} bytes)", wav_data.len());
            HostMessage::VoiceSampleResult(VoiceSampleResult {
                name: name.clone(),
                success: true,
                error: None,
            })
        }
        Err(e) => HostMessage::VoiceSampleResult(VoiceSampleResult {
            name: name.clone(),
            success: false,
            error: Some(e),
        }),
    };
    vec![serde_json::to_string(&msg).unwrap()]
}

fn save_sample_to_disk(name: &str, wav_data: &[u8], samples_dir: &std::path::Path) -> Result<(), String> {
    let _ = std::fs::create_dir_all(samples_dir);
    let dest = samples_dir.join(format!("{name}.wav"));
    std::fs::write(&dest, wav_data).map_err(|e| format!("Failed to write sample: {e}"))
}

fn handle_delete_voice_sample(req: &DeleteVoiceSampleRequest) -> Vec<String> {
    let name = &req.name;
    println!("  [chatterbox] Deleting voice sample: {name}");

    let samples_dir = find_voice_samples_dir();

    // Try server delete first
    let cb = ChatterboxSynthesizer::new(None, &samples_dir);
    if let Ok(ref cb) = cb {
        if cb.probe() {
            let _ = cb.delete_sample(name);
        }
    }

    // Also delete from disk directly
    let mut deleted = false;
    if let Ok(entries) = std::fs::read_dir(&samples_dir) {
        for entry in entries.flatten() {
            let path = entry.path();
            if path.file_stem().map(|s| s.to_string_lossy().to_string()) == Some(name.to_string()) {
                let _ = std::fs::remove_file(&path);
                deleted = true;
                break;
            }
        }
    }

    let msg = HostMessage::VoiceSampleResult(VoiceSampleResult {
        name: name.clone(),
        success: deleted,
        error: if deleted { None } else { Some("Sample not found".into()) },
    });
    vec![serde_json::to_string(&msg).unwrap()]
}

// ── Server management handlers ───────────────────────────────────────────

fn handle_manage_server(req: &ManageServerRequest) -> Vec<String> {
    let engine = &req.engine;
    let action = &req.action;
    println!("  [server-mgr] {} server: {}", action, engine);

    let def = SERVER_DEFS.iter().find(|d| d.engine == engine);
    let def = match def {
        Some(d) => d,
        None => {
            let msg = HostMessage::ServerManageResult(ServerManageResult {
                engine: engine.clone(),
                action: action.clone(),
                success: false,
                error: Some(format!("Unknown engine: {engine}")),
            });
            return vec![serde_json::to_string(&msg).unwrap()];
        }
    };

    let result = match action.as_str() {
        "start" => start_server(def),
        "stop" => stop_server(def),
        "restart" => {
            let _ = stop_server(def);
            std::thread::sleep(std::time::Duration::from_secs(1));
            start_server(def)
        }
        _ => Err(format!("Unknown action: {action}")),
    };

    // Wait briefly for server to come up
    if result.is_ok() && (action == "start" || action == "restart") {
        for _ in 0..10 {
            std::thread::sleep(std::time::Duration::from_millis(500));
            if find_pid_on_port(def.port).is_some() {
                break;
            }
        }
    }

    let msg = HostMessage::ServerManageResult(ServerManageResult {
        engine: engine.clone(),
        action: action.clone(),
        success: result.is_ok(),
        error: result.err(),
    });
    vec![serde_json::to_string(&msg).unwrap()]
}

fn handle_get_server_stats() -> Vec<String> {
    let stats = collect_stats();
    let msg = HostMessage::ServerStats(ServerStatsResponse { servers: stats });
    vec![serde_json::to_string(&msg).unwrap()]
}

// ── Voice designer handlers ──────────────────────────────────────────────

fn handle_design_voice(req: &DesignVoiceRequest) -> Vec<String> {
    println!("  [voice-designer] Design voice: '{}'", truncate(&req.description, 60));

    let client = VoiceDesignerClient::new(None);
    if !client.probe() {
        let msg = HostMessage::VoiceDesignResult(VoiceDesignResult {
            id: req.id.clone(),
            success: false,
            audio_base64: None,
            sample_rate: None,
            duration_ms: None,
            description: None,
            error: Some("Voice designer server not running. Start it with: python3 voice_designer_server.py".into()),
        });
        return vec![serde_json::to_string(&msg).unwrap()];
    }

    match client.design(&req.description, &req.preview_text) {
        Ok(result) => {
            let msg = HostMessage::VoiceDesignResult(VoiceDesignResult {
                id: req.id.clone(),
                success: result.success,
                audio_base64: result.audio_base64,
                sample_rate: result.sample_rate,
                duration_ms: result.duration_ms,
                description: result.description,
                error: result.error,
            });
            vec![serde_json::to_string(&msg).unwrap()]
        }
        Err(e) => {
            let msg = HostMessage::VoiceDesignResult(VoiceDesignResult {
                id: req.id.clone(),
                success: false,
                audio_base64: None,
                sample_rate: None,
                duration_ms: None,
                description: None,
                error: Some(e.to_string()),
            });
            vec![serde_json::to_string(&msg).unwrap()]
        }
    }
}

fn handle_blend_voices(req: &BlendVoicesRequest) -> Vec<String> {
    println!("  [voice-designer] Blend {} voice samples", req.audio_samples_base64.len());

    let client = VoiceDesignerClient::new(None);
    if !client.probe() {
        let msg = HostMessage::VoiceBlendResult(VoiceBlendResult {
            id: req.id.clone(),
            success: false,
            embedding: None,
            dimensions: None,
            weights_normalized: None,
            error: Some("Voice designer server not running".into()),
        });
        return vec![serde_json::to_string(&msg).unwrap()];
    }

    // Extract embeddings from each audio sample
    let mut embeddings: Vec<Vec<f32>> = Vec::new();
    for (i, audio_b64) in req.audio_samples_base64.iter().enumerate() {
        let pcm_bytes = match web_vox_protocol::decode_audio_base64(audio_b64) {
            Ok(b) => b,
            Err(e) => {
                let msg = HostMessage::VoiceBlendResult(VoiceBlendResult {
                    id: req.id.clone(),
                    success: false,
                    embedding: None,
                    dimensions: None,
                    weights_normalized: None,
                    error: Some(format!("Failed to decode audio sample {i}: {e}")),
                });
                return vec![serde_json::to_string(&msg).unwrap()];
            }
        };

        let samples: Vec<f32> = pcm_bytes
            .chunks_exact(4)
            .map(|chunk| f32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]))
            .collect();

        let sample_rate = req.sample_rates.get(i).copied().unwrap_or(22050);

        match client.extract_embedding(&samples, sample_rate) {
            Ok(result) if result.success => {
                if let Some(emb) = result.embedding {
                    embeddings.push(emb);
                } else {
                    let msg = HostMessage::VoiceBlendResult(VoiceBlendResult {
                        id: req.id.clone(),
                        success: false,
                        embedding: None,
                        dimensions: None,
                        weights_normalized: None,
                        error: Some(format!("No embedding returned for sample {i}")),
                    });
                    return vec![serde_json::to_string(&msg).unwrap()];
                }
            }
            Ok(result) => {
                let msg = HostMessage::VoiceBlendResult(VoiceBlendResult {
                    id: req.id.clone(),
                    success: false,
                    embedding: None,
                    dimensions: None,
                    weights_normalized: None,
                    error: Some(format!("Embedding extraction failed for sample {i}: {}", result.error.unwrap_or_default())),
                });
                return vec![serde_json::to_string(&msg).unwrap()];
            }
            Err(e) => {
                let msg = HostMessage::VoiceBlendResult(VoiceBlendResult {
                    id: req.id.clone(),
                    success: false,
                    embedding: None,
                    dimensions: None,
                    weights_normalized: None,
                    error: Some(format!("Embedding extraction error for sample {i}: {e}")),
                });
                return vec![serde_json::to_string(&msg).unwrap()];
            }
        }
    }

    // Use provided weights or equal weights
    let weights = if req.weights.is_empty() {
        vec![1.0; embeddings.len()]
    } else {
        req.weights.clone()
    };

    match client.blend(&embeddings, &weights) {
        Ok(result) => {
            let msg = HostMessage::VoiceBlendResult(VoiceBlendResult {
                id: req.id.clone(),
                success: result.success,
                embedding: result.embedding,
                dimensions: result.dimensions,
                weights_normalized: result.weights_normalized,
                error: result.error,
            });
            vec![serde_json::to_string(&msg).unwrap()]
        }
        Err(e) => {
            let msg = HostMessage::VoiceBlendResult(VoiceBlendResult {
                id: req.id.clone(),
                success: false,
                embedding: None,
                dimensions: None,
                weights_normalized: None,
                error: Some(e.to_string()),
            });
            vec![serde_json::to_string(&msg).unwrap()]
        }
    }
}

fn handle_list_voice_profiles() -> Vec<String> {
    let client = VoiceDesignerClient::new(None);
    if !client.probe() {
        let msg = HostMessage::VoiceProfiles(VoiceProfileList { profiles: vec![] });
        return vec![serde_json::to_string(&msg).unwrap()];
    }

    match client.list_profiles() {
        Ok(profiles) => {
            let proto_profiles: Vec<VoiceProfileSummary> = profiles
                .into_iter()
                .map(|p| VoiceProfileSummary {
                    id: p.id,
                    name: p.name,
                    description: p.description,
                    sample_rate: p.sample_rate,
                    has_embedding: p.has_embedding.unwrap_or(false),
                    has_reference_audio: p.has_reference_audio.unwrap_or(false),
                    created_at: p.created_at,
                })
                .collect();
            let msg = HostMessage::VoiceProfiles(VoiceProfileList { profiles: proto_profiles });
            vec![serde_json::to_string(&msg).unwrap()]
        }
        Err(e) => {
            let msg = HostMessage::Error(ErrorMessage {
                id: None,
                code: "voice_designer_error".into(),
                message: e.to_string(),
            });
            vec![serde_json::to_string(&msg).unwrap()]
        }
    }
}

fn handle_save_voice_profile(req: &SaveVoiceProfileRequest) -> Vec<String> {
    let client = VoiceDesignerClient::new(None);
    if !client.probe() {
        let msg = HostMessage::VoiceProfileResult(VoiceProfileResult {
            success: false,
            profile_id: None,
            error: Some("Voice designer server not running".into()),
        });
        return vec![serde_json::to_string(&msg).unwrap()];
    }

    match client.save_profile(
        "", // auto-generate ID
        &req.name,
        &req.description,
        req.embedding.as_deref(),
        req.reference_audio_base64.as_deref(),
        req.sample_rate,
    ) {
        Ok(result) => {
            let msg = HostMessage::VoiceProfileResult(VoiceProfileResult {
                success: result.success,
                profile_id: result.profile_id,
                error: result.error,
            });
            vec![serde_json::to_string(&msg).unwrap()]
        }
        Err(e) => {
            let msg = HostMessage::VoiceProfileResult(VoiceProfileResult {
                success: false,
                profile_id: None,
                error: Some(e.to_string()),
            });
            vec![serde_json::to_string(&msg).unwrap()]
        }
    }
}

fn handle_delete_voice_profile(req: &DeleteVoiceProfileRequest) -> Vec<String> {
    let client = VoiceDesignerClient::new(None);
    if !client.probe() {
        let msg = HostMessage::VoiceProfileResult(VoiceProfileResult {
            success: false,
            profile_id: Some(req.profile_id.clone()),
            error: Some("Voice designer server not running".into()),
        });
        return vec![serde_json::to_string(&msg).unwrap()];
    }

    match client.delete_profile(&req.profile_id) {
        Ok(result) => {
            let msg = HostMessage::VoiceProfileResult(VoiceProfileResult {
                success: result.success,
                profile_id: Some(req.profile_id.clone()),
                error: result.error,
            });
            vec![serde_json::to_string(&msg).unwrap()]
        }
        Err(e) => {
            let msg = HostMessage::VoiceProfileResult(VoiceProfileResult {
                success: false,
                profile_id: Some(req.profile_id.clone()),
                error: Some(e.to_string()),
            });
            vec![serde_json::to_string(&msg).unwrap()]
        }
    }
}

fn truncate(s: &str, max: usize) -> String {
    if s.chars().count() <= max {
        s.to_string()
    } else {
        let end: usize = s.char_indices().nth(max).map(|(i, _)| i).unwrap_or(s.len());
        format!("{}...", &s[..end])
    }
}
