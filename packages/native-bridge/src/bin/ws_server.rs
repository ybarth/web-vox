//! WebSocket server for web-vox — bridges browser to OS TTS.
//! Listens on ws://localhost:21740, accepts JSON messages per the web-vox protocol.
//!
//! Architecture: The main thread owns an NSRunLoop (required by AVSpeechSynthesizer)
//! and processes TTS requests from a channel. Tokio runs on a background thread
//! handling all WebSocket I/O.
//!
//! Run with: cargo run --bin web-vox-server

use std::net::SocketAddr;
use std::sync::mpsc;

use futures_util::{SinkExt, StreamExt};
use tokio::net::{TcpListener, TcpStream};
use tokio_tungstenite::tungstenite::Message;

use web_vox_protocol::*;

#[cfg(target_os = "macos")]
use web_vox_native_bridge::tts::macos::MacOsSynthesizer;
use web_vox_native_bridge::tts::traits::{SynthesisOptions, TtsSynthesizer};

/// A TTS work request sent from a tokio task to the main thread.
struct TtsRequest {
    message: ClientMessage,
    reply: tokio::sync::oneshot::Sender<Vec<String>>,
}

fn main() {
    env_logger::init();

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
    }
}

fn handle_list_voices() -> Vec<String> {
    #[cfg(target_os = "macos")]
    {
        let synth = MacOsSynthesizer::new();
        match synth.list_voices() {
            Ok(voices) => {
                let msg = HostMessage::VoiceList(VoiceList { voices });
                vec![serde_json::to_string(&msg).unwrap()]
            }
            Err(e) => {
                let msg = HostMessage::Error(ErrorMessage {
                    id: None,
                    code: "VOICE_LIST_ERROR".into(),
                    message: e.to_string(),
                });
                vec![serde_json::to_string(&msg).unwrap()]
            }
        }
    }

    #[cfg(not(target_os = "macos"))]
    {
        let msg = HostMessage::Error(ErrorMessage {
            id: None,
            code: "NOT_SUPPORTED".into(),
            message: "TTS not supported on this platform yet".into(),
        });
        vec![serde_json::to_string(&msg).unwrap()]
    }
}

fn handle_synthesize(req: &SynthesizeRequest) -> Vec<String> {
    let id = req.id.clone();
    let mut responses = Vec::new();

    #[cfg(target_os = "macos")]
    {
        let synth = MacOsSynthesizer::new();
        let options = SynthesisOptions {
            voice_id: req.voice_id.clone(),
            rate: req.rate,
            pitch: req.pitch,
            volume: req.volume,
        };

        match synth.synthesize(&req.text, &id, &options) {
            Ok(output) => {
                for wb in &output.word_boundaries {
                    let msg = HostMessage::WordBoundary(wb.clone());
                    responses.push(serde_json::to_string(&msg).unwrap());
                }

                let chunks = web_vox_native_bridge::audio::encoder::encode_chunks(
                    &id,
                    &output.samples,
                    output.sample_rate,
                    output.channels,
                );
                for chunk in chunks {
                    let msg = HostMessage::AudioChunk(chunk);
                    responses.push(serde_json::to_string(&msg).unwrap());
                }

                let msg = HostMessage::SynthesisComplete(SynthesisComplete {
                    id: id.clone(),
                    total_duration_ms: output.total_duration_ms,
                });
                responses.push(serde_json::to_string(&msg).unwrap());

                println!(
                    "  Synthesized \"{}\" -> {:.1}s, {} samples",
                    truncate(&req.text, 40),
                    output.total_duration_ms / 1000.0,
                    output.samples.len()
                );
            }
            Err(e) => {
                let msg = HostMessage::Error(ErrorMessage {
                    id: Some(id),
                    code: "SYNTHESIS_ERROR".into(),
                    message: e.to_string(),
                });
                responses.push(serde_json::to_string(&msg).unwrap());
            }
        }
    }

    #[cfg(not(target_os = "macos"))]
    {
        let msg = HostMessage::Error(ErrorMessage {
            id: Some(id),
            code: "NOT_SUPPORTED".into(),
            message: "TTS not supported on this platform yet".into(),
        });
        responses.push(serde_json::to_string(&msg).unwrap());
    }

    responses
}

fn truncate(s: &str, max: usize) -> String {
    if s.len() <= max {
        s.to_string()
    } else {
        format!("{}...", &s[..max])
    }
}
