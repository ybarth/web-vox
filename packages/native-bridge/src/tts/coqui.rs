//! Coqui TTS engine — communicates with a persistent Python HTTP server.
//!
//! The Coqui server runs on localhost:21743 and handles model loading
//! and synthesis using Coqui TTS models.
//!
//! Start the server with:
//!   cd packages/native-bridge && python3 coqui_server.py

use std::io::Read as _;

use crate::tts::traits::{SynthesisOptions, SynthesisOutput, TtsError, TtsSynthesizer};
use web_vox_protocol::{VoiceDescriptor, WordBoundary};

const DEFAULT_URL: &str = "http://127.0.0.1:21743";

pub struct CoquiSynthesizer {
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

#[derive(serde::Deserialize)]
struct VoiceInfo {
    id: String,
    name: String,
    language: String,
    #[serde(default)]
    gender: Option<String>,
}

impl CoquiSynthesizer {
    pub fn new(base_url: Option<&str>) -> Self {
        let base_url = base_url.unwrap_or(DEFAULT_URL).to_string();
        Self { base_url }
    }

    /// Check if the Coqui server is running.
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

impl TtsSynthesizer for CoquiSynthesizer {
    fn synthesize(
        &self,
        text: &str,
        request_id: &str,
        options: &SynthesisOptions,
    ) -> Result<SynthesisOutput, TtsError> {
        let voice_code = options
            .voice_id
            .as_deref()
            .and_then(|id| id.strip_prefix("coqui:"))
            .unwrap_or("default");

        let body = serde_json::json!({
            "text": text,
            "voice": voice_code,
        });

        let url = format!("{}/synthesize", self.base_url);
        println!(
            "  [coqui] Synthesizing: \"{}\" voice={}",
            &text[..text.len().min(60)],
            voice_code
        );

        let body_str = body.to_string();
        let mut resp = ureq::post(&url)
            .header("Content-Type", "application/json")
            .send(body_str.as_bytes())
            .map_err(|e| {
                TtsError::SynthesisFailed(format!(
                    "Coqui server request failed (is coqui_server.py running?): {e}"
                ))
            })?;

        let status = resp.status();
        if status != 200 {
            let body = resp.body_mut().read_to_string().unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body) {
                return Err(TtsError::SynthesisFailed(err.error));
            }
            return Err(TtsError::SynthesisFailed(format!(
                "Coqui server returned status {status}"
            )));
        }

        let sample_rate: u32 = resp
            .headers()
            .get("X-Sample-Rate")
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.parse::<u32>().ok())
            .unwrap_or(22050);
        let channels: u16 = resp
            .headers()
            .get("X-Channels")
            .and_then(|v| v.to_str().ok())
            .and_then(|v| v.parse::<u16>().ok())
            .unwrap_or(1);

        let mut pcm_bytes = Vec::new();
        resp.body_mut()
            .as_reader()
            .read_to_end(&mut pcm_bytes)
            .map_err(|e| TtsError::SynthesisFailed(format!("Failed to read PCM data: {e}")))?;

        if pcm_bytes.len() < 4 {
            return Err(TtsError::SynthesisFailed("Coqui produced no audio".into()));
        }

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

        let word_boundaries =
            generate_simple_word_boundaries(text, request_id, total_duration_ms);

        println!(
            "  [coqui] Produced {} samples ({:.1}s) @ {}Hz",
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
        let url = format!("{}/voices", self.base_url);
        let mut resp = ureq::get(&url).call().map_err(|e| {
            TtsError::NotAvailable(format!("Coqui server not reachable: {e}"))
        })?;

        let body = resp
            .body_mut()
            .read_to_string()
            .map_err(|e| TtsError::SynthesisFailed(format!("Failed to read voices: {e}")))?;

        let infos: Vec<VoiceInfo> = serde_json::from_str(&body)
            .map_err(|e| TtsError::SynthesisFailed(format!("Failed to parse voices: {e}")))?;

        Ok(infos
            .into_iter()
            .map(|v| VoiceDescriptor {
                id: format!("coqui:{}", v.id),
                name: format!("Coqui: {}", v.name),
                language: v.language,
                gender: v.gender,
                engine: "coqui".to_string(),
                quality: Some("neural".to_string()),
                description: Some(format!("Coqui TTS — {}", v.name)),
                sample_rate: Some(22050),
            })
            .collect())
    }
}

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
            element_index: None,
            document_char_offset: None,
        })
        .collect()
}
