//! Kokoro TTS engine — communicates with a persistent Python HTTP server.
//!
//! The Kokoro server runs on localhost:21742 and handles model loading
//! and synthesis using the hexgrad/Kokoro-82M neural TTS model.
//!
//! Start the server with:
//!   cd packages/native-bridge && python3 kokoro_server.py

use std::io::Read as _;

use crate::tts::traits::{SynthesisOptions, SynthesisOutput, TtsError, TtsSynthesizer};
use web_vox_protocol::{VoiceDescriptor, WordBoundary};

const DEFAULT_URL: &str = "http://127.0.0.1:21742";

pub struct KokoroSynthesizer {
    base_url: String,
}

#[derive(serde::Deserialize)]
struct HealthResponse {
    status: String,
    #[allow(dead_code)]
    model_loaded: bool,
}

#[derive(serde::Deserialize)]
struct ErrorResponse {
    error: String,
}

impl KokoroSynthesizer {
    pub fn new(base_url: Option<&str>) -> Self {
        let base_url = base_url.unwrap_or(DEFAULT_URL).to_string();
        Self { base_url }
    }

    /// Check if the Kokoro server is running.
    pub fn probe(&self) -> bool {
        let url = format!("{}/health", self.base_url);
        match ureq::get(&url).call() {
            Ok(mut resp) => {
                if let Ok(body) = resp.body_mut().read_to_string() {
                    if let Ok(health) = serde_json::from_str::<HealthResponse>(&body) {
                        return health.status == "ok";
                    }
                }
                false
            }
            Err(_) => false,
        }
    }
}

impl TtsSynthesizer for KokoroSynthesizer {
    fn synthesize(
        &self,
        text: &str,
        request_id: &str,
        options: &SynthesisOptions,
    ) -> Result<SynthesisOutput, TtsError> {
        // Strip "kokoro:" prefix to get the raw Kokoro voice code (e.g. "am_onyx")
        let voice_code = options
            .voice_id
            .as_deref()
            .and_then(|id| id.strip_prefix("kokoro:"))
            .unwrap_or("am_onyx");

        let body = serde_json::json!({
            "text": text,
            "voice": voice_code,
        });

        let url = format!("{}/synthesize", self.base_url);
        println!(
            "  [kokoro] Synthesizing: \"{}\" voice={}",
            &text[..text.len().min(60)],
            voice_code
        );

        let body_str = body.to_string();
        let mut resp = ureq::post(&url)
            .header("Content-Type", "application/json")
            .send(body_str.as_bytes())
            .map_err(|e| {
                TtsError::SynthesisFailed(format!(
                    "Kokoro server request failed (is kokoro_server.py running?): {e}"
                ))
            })?;

        let status = resp.status();
        if status != 200 {
            let body = resp.body_mut().read_to_string().unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body) {
                return Err(TtsError::SynthesisFailed(err.error));
            }
            return Err(TtsError::SynthesisFailed(format!(
                "Kokoro server returned status {status}"
            )));
        }

        // Read headers
        let sample_rate: u32 = resp
            .headers()
            .get("X-Sample-Rate")
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.parse::<u32>().ok())
            .unwrap_or(24000);
        let channels: u16 = resp
            .headers()
            .get("X-Channels")
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.parse::<u16>().ok())
            .unwrap_or(1);

        // Read raw PCM f32 LE bytes
        let mut pcm_bytes = Vec::new();
        resp.body_mut()
            .as_reader()
            .read_to_end(&mut pcm_bytes)
            .map_err(|e| TtsError::SynthesisFailed(format!("Failed to read PCM data: {e}")))?;

        if pcm_bytes.len() < 4 {
            return Err(TtsError::SynthesisFailed("Kokoro produced no audio".into()));
        }

        // Convert f32 LE bytes to f32 samples
        let num_samples = pcm_bytes.len() / 4;
        let mut samples = Vec::with_capacity(num_samples);
        for i in 0..num_samples {
            let bytes: [u8; 4] = [
                pcm_bytes[i * 4],
                pcm_bytes[i * 4 + 1],
                pcm_bytes[i * 4 + 2],
                pcm_bytes[i * 4 + 3],
            ];
            samples.push(f32::from_le_bytes(bytes));
        }

        let total_duration_ms =
            (samples.len() as f64 / channels as f64 / sample_rate as f64) * 1000.0;

        // Generate approximate word boundaries
        let word_boundaries =
            generate_simple_word_boundaries(text, request_id, total_duration_ms);

        println!(
            "  [kokoro] Produced {} samples ({:.1}s) @ {}Hz",
            samples.len(),
            total_duration_ms / 1000.0,
            sample_rate
        );

        Ok(SynthesisOutput {
            samples,
            sample_rate,
            channels,
            word_boundaries,
            total_duration_ms,
        })
    }

    fn list_voices(&self) -> Result<Vec<VoiceDescriptor>, TtsError> {
        Ok(kokoro_voices())
    }
}

/// All built-in Kokoro-82M voices.
pub fn kokoro_voices() -> Vec<VoiceDescriptor> {
    vec![
        // ── American Female ──────────────────────────────────────────────
        vd("af_heart",   "Heart (American Female)",    "en-US", "Female"),
        vd("af_bella",   "Bella (American Female)",    "en-US", "Female"),
        vd("af_nicole",  "Nicole (American Female)",   "en-US", "Female"),
        vd("af_sarah",   "Sarah (American Female)",    "en-US", "Female"),
        vd("af_sky",     "Sky (American Female)",      "en-US", "Female"),
        // ── American Male ────────────────────────────────────────────────
        vd("am_onyx",    "Onyx (American Male)",       "en-US", "Male"),
        vd("am_adam",    "Adam (American Male)",       "en-US", "Male"),
        vd("am_echo",    "Echo (American Male)",       "en-US", "Male"),
        vd("am_eric",    "Eric (American Male)",       "en-US", "Male"),
        vd("am_fenrir",  "Fenrir (American Male)",     "en-US", "Male"),
        vd("am_liam",    "Liam (American Male)",       "en-US", "Male"),
        vd("am_michael", "Michael (American Male)",    "en-US", "Male"),
        vd("am_puck",    "Puck (American Male)",       "en-US", "Male"),
        // ── British Female ───────────────────────────────────────────────
        vd("bf_alice",    "Alice (British Female)",    "en-GB", "Female"),
        vd("bf_emma",     "Emma (British Female)",     "en-GB", "Female"),
        vd("bf_isabella", "Isabella (British Female)", "en-GB", "Female"),
        vd("bf_lily",     "Lily (British Female)",     "en-GB", "Female"),
        // ── British Male ─────────────────────────────────────────────────
        vd("bm_daniel",  "Daniel (British Male)",      "en-GB", "Male"),
        vd("bm_fable",   "Fable (British Male)",       "en-GB", "Male"),
        vd("bm_george",  "George (British Male)",      "en-GB", "Male"),
        vd("bm_lewis",   "Lewis (British Male)",       "en-GB", "Male"),
    ]
}

fn vd(code: &str, name: &str, lang: &str, gender: &str) -> VoiceDescriptor {
    VoiceDescriptor {
        id: format!("kokoro:{code}"),
        name: format!("Kokoro: {name}"),
        language: lang.to_string(),
        gender: Some(gender.to_string()),
        engine: "kokoro".to_string(),
        quality: Some("neural".to_string()),
        description: Some(format!("Kokoro neural TTS — {name}")),
        sample_rate: Some(24000),
    }
}

/// Generate approximate word boundaries by evenly distributing time across words.
fn generate_simple_word_boundaries(
    text: &str,
    request_id: &str,
    total_duration_ms: f64,
) -> Vec<WordBoundary> {
    let words: Vec<(usize, &str)> = text
        .split_whitespace()
        .map(|w| {
            let offset = w.as_ptr() as usize - text.as_ptr() as usize;
            (offset, w)
        })
        .collect();

    if words.is_empty() {
        return Vec::new();
    }

    let time_per_word = total_duration_ms / words.len() as f64;
    words
        .iter()
        .enumerate()
        .map(|(i, (offset, word))| WordBoundary {
            id: request_id.to_string(),
            word: word.to_string(),
            char_offset: *offset,
            char_length: word.len(),
            start_time_ms: i as f64 * time_per_word,
            end_time_ms: (i + 1) as f64 * time_per_word,
            confidence: None,
            phonemes: None,
            syllables: None,
        })
        .collect()
}
