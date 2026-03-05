//! Cross-platform TTS synthesizer trait.

use web_vox_protocol::{VoiceDescriptor, WordBoundary};

/// Result of a synthesis operation.
pub struct SynthesisOutput {
    /// Raw PCM float32 samples (mono or multi-channel interleaved).
    pub samples: Vec<f32>,
    /// Sample rate of the audio.
    pub sample_rate: u32,
    /// Number of audio channels.
    pub channels: u16,
    /// Word boundary events with timing.
    pub word_boundaries: Vec<WordBoundary>,
    /// Total duration in milliseconds.
    pub total_duration_ms: f64,
}

/// Options for a synthesis request.
#[derive(Debug, Clone)]
pub struct SynthesisOptions {
    pub voice_id: Option<String>,
    pub rate: f32,
    pub pitch: f32,
    pub volume: f32,
}

impl Default for SynthesisOptions {
    fn default() -> Self {
        Self {
            voice_id: None,
            rate: 1.0,
            pitch: 1.0,
            volume: 1.0,
        }
    }
}

/// Cross-platform trait for OS TTS synthesis with audio capture.
pub trait TtsSynthesizer: Send + Sync {
    /// Synthesize text and capture audio + word boundaries.
    fn synthesize(
        &self,
        text: &str,
        request_id: &str,
        options: &SynthesisOptions,
    ) -> Result<SynthesisOutput, TtsError>;

    /// List available voices on this platform.
    fn list_voices(&self) -> Result<Vec<VoiceDescriptor>, TtsError>;
}

#[derive(Debug, thiserror::Error)]
pub enum TtsError {
    #[error("TTS engine not available: {0}")]
    NotAvailable(String),
    #[error("Voice not found: {0}")]
    VoiceNotFound(String),
    #[error("Synthesis failed: {0}")]
    SynthesisFailed(String),
    #[error("Platform error: {0}")]
    PlatformError(String),
}
