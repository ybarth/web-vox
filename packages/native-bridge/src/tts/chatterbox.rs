//! Chatterbox TTS engine — communicates with a persistent Python HTTP server.
//!
//! The Chatterbox server runs on localhost:21741 and handles model loading,
//! synthesis, and voice sample management.
//!
//! Start the server with:
//!   cd packages/native-bridge && python3 chatterbox_server.py

use std::io::Read as _;
use std::path::Path;
use std::time::Duration;

use crate::tts::traits::{SynthesisOptions, SynthesisOutput, TtsError, TtsSynthesizer};
use web_vox_protocol::{VoiceDescriptor, WordBoundary};

const DEFAULT_URL: &str = "http://127.0.0.1:21741";

/// Timeout for synthesis requests (model loading + inference can be slow).
const SYNTHESIS_TIMEOUT: Duration = Duration::from_secs(300);

pub struct ChatterboxSynthesizer {
    base_url: String,
    /// Agent with long timeout for synthesis requests.
    synth_agent: ureq::Agent,
}

#[derive(serde::Deserialize)]
struct HealthResponse {
    status: String,
    #[allow(dead_code)]
    model_loaded: bool,
    #[allow(dead_code)]
    sample_rate: u32,
}

#[derive(serde::Deserialize)]
pub struct VoiceSample {
    pub name: String,
    pub filename: String,
    pub size_bytes: u64,
}

#[derive(serde::Deserialize)]
struct VoiceSamplesResponse {
    samples: Vec<VoiceSample>,
}

#[derive(serde::Deserialize)]
struct ErrorResponse {
    error: String,
}

impl ChatterboxSynthesizer {
    pub fn new(base_url: Option<&str>, _samples_dir: &Path) -> Result<Self, TtsError> {
        let base_url = base_url.unwrap_or(DEFAULT_URL).to_string();
        let synth_agent = ureq::Agent::config_builder()
            .timeout_global(Some(SYNTHESIS_TIMEOUT))
            .http_status_as_error(false)
            .build()
            .new_agent();
        Ok(Self { base_url, synth_agent })
    }

    /// Check if the Chatterbox server is running.
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

    /// List voice samples available on the server.
    pub fn list_samples(&self) -> Result<Vec<VoiceSample>, TtsError> {
        let url = format!("{}/voices", self.base_url);
        let mut resp = ureq::get(&url)
            .call()
            .map_err(|e| TtsError::SynthesisFailed(format!("Chatterbox server request failed: {e}")))?;
        let body = resp
            .body_mut()
            .read_to_string()
            .map_err(|e| TtsError::SynthesisFailed(format!("Failed to read response: {e}")))?;
        let parsed: VoiceSamplesResponse = serde_json::from_str(&body)
            .map_err(|e| TtsError::SynthesisFailed(format!("Failed to parse response: {e}")))?;
        Ok(parsed.samples)
    }

    /// Upload a voice sample WAV file.
    pub fn upload_sample(&self, name: &str, wav_data: &[u8]) -> Result<(), TtsError> {
        let url = format!("{}/upload_sample?name={}", self.base_url, name);
        let mut resp = ureq::post(&url)
            .header("Content-Type", "application/octet-stream")
            .send(wav_data)
            .map_err(|e| TtsError::SynthesisFailed(format!("Upload failed: {e}")))?;
        let body = resp
            .body_mut()
            .read_to_string()
            .map_err(|e| TtsError::SynthesisFailed(format!("Failed to read response: {e}")))?;

        // Check for error
        if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body) {
            if !err.error.is_empty() {
                return Err(TtsError::SynthesisFailed(format!("Upload error: {}", err.error)));
            }
        }

        Ok(())
    }

    /// Delete a voice sample.
    pub fn delete_sample(&self, name: &str) -> Result<(), TtsError> {
        let url = format!("{}/sample/{}", self.base_url, name);
        ureq::delete(&url)
            .call()
            .map_err(|e| TtsError::SynthesisFailed(format!("Delete failed: {e}")))?;
        Ok(())
    }
}

impl TtsSynthesizer for ChatterboxSynthesizer {
    fn synthesize(
        &self,
        text: &str,
        request_id: &str,
        options: &SynthesisOptions,
    ) -> Result<SynthesisOutput, TtsError> {
        // Extract voice sample name from voice_id (format: "chatterbox:<sample_name>" or "chatterbox:default")
        let voice_sample = options.voice_id.as_deref().and_then(|id| {
            id.strip_prefix("chatterbox:").and_then(|name| {
                if name == "default" { None } else { Some(name.to_string()) }
            })
        });

        // Build JSON body
        let body = serde_json::json!({
            "text": text,
            "voice_sample": voice_sample,
            "exaggeration": 0.5,
            "cfg_weight": 0.5,
            "temperature": 0.8,
        });

        let url = format!("{}/synthesize", self.base_url);
        println!("  [chatterbox] Synthesizing: \"{}\"", &text[..text.len().min(60)]);

        let body_str = body.to_string();
        let mut resp = self.synth_agent
            .post(&url)
            .header("Content-Type", "application/json")
            .send(body_str.as_bytes())
            .map_err(|e| {
                TtsError::SynthesisFailed(format!(
                    "Chatterbox server request failed (is chatterbox_server.py running?): {e}"
                ))
            })?;

        let status = resp.status();
        if status != 200 {
            let err_body = resp.body_mut().read_to_string().unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&err_body) {
                return Err(TtsError::SynthesisFailed(format!(
                    "Chatterbox synthesis error: {}", err.error
                )));
            }
            return Err(TtsError::SynthesisFailed(format!(
                "Chatterbox server returned status {status}: {err_body}"
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
            return Err(TtsError::SynthesisFailed("Chatterbox produced no audio".into()));
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
            "  [chatterbox] Produced {} samples ({:.1}s) @ {}Hz",
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
        let mut voices = vec![VoiceDescriptor {
            id: "chatterbox:default".to_string(),
            name: "Chatterbox (Default)".to_string(),
            language: "en".to_string(),
            gender: None,
            engine: "chatterbox".to_string(),
            quality: Some("neural".to_string()),
            description: Some("Chatterbox neural TTS — built-in default voice".to_string()),
            sample_rate: Some(24000),
        }];

        // Add voice samples as cloned voices
        if let Ok(samples) = self.list_samples() {
            for sample in samples {
                voices.push(VoiceDescriptor {
                    id: format!("chatterbox:{}", sample.name),
                    name: format!("Chatterbox: {}", sample.name),
                    language: "en".to_string(),
                    gender: None,
                    engine: "chatterbox".to_string(),
                    quality: Some("neural-clone".to_string()),
                    description: Some(format!(
                        "Chatterbox voice clone from sample \"{}\"",
                        sample.name
                    )),
                    sample_rate: Some(24000),
                });
            }
        }

        Ok(voices)
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
