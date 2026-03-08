//! Forced alignment client — calls the alignment_server.py HTTP service
//! to get accurate word-level (and optionally syllable/phoneme) timestamps
//! for synthesized audio.

use std::time::Duration;

use web_vox_protocol::{PhonemeBoundary, SyllableBoundary, WordBoundary};

const DEFAULT_URL: &str = "http://127.0.0.1:21747";
const ALIGNMENT_TIMEOUT: Duration = Duration::from_secs(60);

pub struct AlignmentClient {
    base_url: String,
    agent: ureq::Agent,
}

#[derive(serde::Deserialize)]
struct AlignmentResponse {
    words: Vec<AlignedWord>,
    #[allow(dead_code)]
    total_duration_ms: f64,
}

#[derive(serde::Deserialize)]
struct AlignedWord {
    word: String,
    char_offset: usize,
    char_length: usize,
    start_time_ms: f64,
    end_time_ms: f64,
    #[serde(default)]
    confidence: Option<f32>,
    #[serde(default)]
    syllables: Option<Vec<AlignedSyllable>>,
    #[serde(default)]
    phonemes: Option<Vec<AlignedPhoneme>>,
}

#[derive(serde::Deserialize)]
struct AlignedSyllable {
    text: String,
    #[serde(default)]
    char_offset: Option<usize>,
    start_time_ms: f64,
    end_time_ms: f64,
}

#[derive(serde::Deserialize)]
struct AlignedPhoneme {
    phoneme: String,
    start_time_ms: f64,
    end_time_ms: f64,
}

impl AlignmentClient {
    pub fn new(base_url: Option<&str>) -> Self {
        let base_url = base_url.unwrap_or(DEFAULT_URL).to_string();
        let agent = ureq::Agent::config_builder()
            .timeout_global(Some(ALIGNMENT_TIMEOUT))
            .http_status_as_error(false)
            .build()
            .new_agent();
        Self { base_url, agent }
    }

    /// Check if the alignment server is running.
    pub fn probe(&self) -> bool {
        let url = format!("{}/health", self.base_url);
        matches!(ureq::get(&url).call(), Ok(resp) if resp.status() == 200)
    }

    /// Run forced alignment on synthesized audio.
    ///
    /// Returns aligned word boundaries with confidence scores and optional
    /// syllable/phoneme data, depending on the requested granularity.
    pub fn align(
        &self,
        samples: &[f32],
        sample_rate: u32,
        channels: u16,
        transcript: &str,
        request_id: &str,
        granularity: &str,
    ) -> Result<Vec<WordBoundary>, AlignmentError> {
        // Convert f32 samples to LE bytes for the HTTP body
        let mut pcm_bytes = Vec::with_capacity(samples.len() * 4);
        for &s in samples {
            pcm_bytes.extend_from_slice(&s.to_le_bytes());
        }

        let url = format!("{}/align", self.base_url);

        println!(
            "  [alignment] Requesting alignment: {} samples @ {}Hz, granularity={}",
            samples.len(),
            sample_rate,
            granularity
        );

        let mut resp = self
            .agent
            .post(&url)
            .header("Content-Type", "application/octet-stream")
            .header("X-Sample-Rate", &sample_rate.to_string())
            .header("X-Channels", &channels.to_string())
            .header("X-Transcript", transcript)
            .header("X-Request-Id", request_id)
            .header("X-Granularity", granularity)
            .send(&pcm_bytes[..])
            .map_err(|e| {
                AlignmentError::ServerError(format!(
                    "Alignment server request failed (is alignment_server.py running?): {e}"
                ))
            })?;

        let status = resp.status();
        if status != 200 {
            let body = resp.body_mut().read_to_string().unwrap_or_default();
            return Err(AlignmentError::ServerError(format!(
                "Alignment server returned status {status}: {body}"
            )));
        }

        let body = resp
            .body_mut()
            .read_to_string()
            .map_err(|e| AlignmentError::ServerError(format!("Failed to read response: {e}")))?;

        let result: AlignmentResponse = serde_json::from_str(&body)
            .map_err(|e| AlignmentError::ServerError(format!("Failed to parse response: {e}")))?;

        // Convert to protocol WordBoundary types
        let boundaries: Vec<WordBoundary> = result
            .words
            .into_iter()
            .map(|w| WordBoundary {
                id: request_id.to_string(),
                word: w.word,
                char_offset: w.char_offset,
                char_length: w.char_length,
                start_time_ms: w.start_time_ms,
                end_time_ms: w.end_time_ms,
                confidence: w.confidence,
                phonemes: w.phonemes.map(|pp| {
                    pp.into_iter()
                        .map(|p| PhonemeBoundary {
                            phoneme: p.phoneme,
                            start_time_ms: p.start_time_ms,
                            end_time_ms: p.end_time_ms,
                        })
                        .collect()
                }),
                syllables: w.syllables.map(|ss| {
                    ss.into_iter()
                        .map(|s| SyllableBoundary {
                            text: s.text,
                            char_offset: s.char_offset,
                            start_time_ms: s.start_time_ms,
                            end_time_ms: s.end_time_ms,
                        })
                        .collect()
                }),
                element_index: None,
                document_char_offset: None,
            })
            .collect();

        println!(
            "  [alignment] Got {} aligned word boundaries",
            boundaries.len()
        );

        Ok(boundaries)
    }
}

#[derive(Debug)]
pub enum AlignmentError {
    ServerError(String),
}

impl std::fmt::Display for AlignmentError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            AlignmentError::ServerError(msg) => write!(f, "Alignment error: {msg}"),
        }
    }
}
