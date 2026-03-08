//! Piper TTS engine — shells out to the `piper` CLI binary.
//!
//! Expects:
//!   - `piper` binary at `test-engines/piper/piper`
//!   - Voice models (`.onnx` + `.onnx.json`) in `test-engines/piper/voices/`
//!
//! Piper outputs raw 16-bit PCM to stdout when given `--output-raw`.

use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use crate::tts::traits::{SynthesisOptions, SynthesisOutput, TtsError, TtsSynthesizer};
use web_vox_protocol::{VoiceDescriptor, WordBoundary};

pub struct PiperSynthesizer {
    piper_bin: PathBuf,
    voices_dirs: Vec<PathBuf>,
}

impl PiperSynthesizer {
    /// Create a new Piper synthesizer. `base_dir` should contain a `piper` binary
    /// and a `voices/` subdirectory. Additional voice directories can be added
    /// with `add_voices_dir`.
    pub fn new(base_dir: &Path) -> Result<Self, TtsError> {
        let piper_bin = base_dir.join("piper");
        if !piper_bin.exists() {
            return Err(TtsError::NotAvailable(format!(
                "Piper binary not found at {}. Run: bash test-engines/setup.sh",
                piper_bin.display()
            )));
        }
        let voices_dir = base_dir.join("voices");
        Ok(Self {
            piper_bin,
            voices_dirs: vec![voices_dir],
        })
    }

    /// Returns the voice directories being scanned.
    pub fn voices_dirs(&self) -> &[PathBuf] {
        &self.voices_dirs
    }

    /// Add an extra directory to scan for voice models.
    pub fn add_voices_dir(&mut self, dir: PathBuf) {
        if dir.is_dir() && !self.voices_dirs.contains(&dir) {
            self.voices_dirs.push(dir);
        }
    }

    fn discover_voices(&self) -> Vec<PiperVoice> {
        let mut voices = Vec::new();
        let mut seen_ids = std::collections::HashSet::new();

        for voices_dir in &self.voices_dirs {
            let entries = match std::fs::read_dir(voices_dir) {
                Ok(e) => e,
                Err(_) => continue,
            };

            for entry in entries.flatten() {
                let path = entry.path();
                if path.extension().map(|e| e == "onnx").unwrap_or(false) {
                    // Check that the companion .onnx.json exists
                    let json_path = PathBuf::from(format!("{}.json", path.display()));
                    if json_path.exists() {
                        let stem = path.file_stem().unwrap().to_string_lossy().to_string();
                        let id = format!("piper:{}", stem);
                        if seen_ids.insert(id.clone()) {
                            voices.push(PiperVoice {
                                id,
                                name: stem.replace('-', " ").replace('_', " "),
                                model_path: path,
                            });
                        }
                    }
                }
            }
        }
        voices
    }
}

struct PiperVoice {
    id: String,
    name: String,
    model_path: PathBuf,
}

impl TtsSynthesizer for PiperSynthesizer {
    fn synthesize(
        &self,
        text: &str,
        request_id: &str,
        options: &SynthesisOptions,
    ) -> Result<SynthesisOutput, TtsError> {
        let voices = self.discover_voices();

        // Find the requested voice or use the first available
        let voice = if let Some(ref voice_id) = options.voice_id {
            voices
                .iter()
                .find(|v| v.id == *voice_id)
                .ok_or_else(|| TtsError::VoiceNotFound(voice_id.clone()))?
        } else {
            voices
                .first()
                .ok_or_else(|| TtsError::NotAvailable("No Piper voice models found".into()))?
        };

        println!("  [piper] Synthesizing with model: {}", voice.model_path.display());

        // Piper reads text from stdin, writes raw 16-bit PCM to stdout
        let mut child = Command::new(&self.piper_bin)
            .arg("--model")
            .arg(&voice.model_path)
            .arg("--output-raw")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| TtsError::SynthesisFailed(format!("Failed to spawn piper: {e}")))?;

        // Write text to stdin
        {
            use std::io::Write;
            let stdin = child.stdin.as_mut().unwrap();
            stdin
                .write_all(text.as_bytes())
                .map_err(|e| TtsError::SynthesisFailed(format!("Failed to write to piper stdin: {e}")))?;
        }

        let output = child
            .wait_with_output()
            .map_err(|e| TtsError::SynthesisFailed(format!("Piper process failed: {e}")))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(TtsError::SynthesisFailed(format!(
                "Piper exited with {}: {}",
                output.status, stderr
            )));
        }

        // Piper outputs 16-bit signed PCM at 22050 Hz mono by default
        let sample_rate = 22050u32;
        let channels = 1u16;
        let raw_bytes = &output.stdout;

        if raw_bytes.len() < 2 {
            return Err(TtsError::SynthesisFailed("Piper produced no audio".into()));
        }

        // Convert i16 PCM bytes to f32 samples
        let num_samples = raw_bytes.len() / 2;
        let mut samples = Vec::with_capacity(num_samples);
        for i in 0..num_samples {
            let lo = raw_bytes[i * 2] as i16;
            let hi = (raw_bytes[i * 2 + 1] as i16) << 8;
            let sample_i16 = lo | hi;
            let sample_f32 = if sample_i16 < 0 {
                sample_i16 as f32 / 32768.0
            } else {
                sample_i16 as f32 / 32767.0
            };
            samples.push(sample_f32);
        }

        let total_duration_ms = (samples.len() as f64 / channels as f64 / sample_rate as f64) * 1000.0;

        // Piper CLI doesn't provide word boundaries, so we generate simple ones
        let word_boundaries = generate_simple_word_boundaries(text, request_id, total_duration_ms);

        println!(
            "  [piper] Produced {} samples ({:.1}s)",
            samples.len(),
            total_duration_ms / 1000.0
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
        let voices = self.discover_voices();
        Ok(voices
            .into_iter()
            .map(|v| VoiceDescriptor {
                id: v.id,
                name: format!("Piper: {}", v.name),
                language: "en-US".to_string(),
                gender: None,
                engine: "piper".to_string(),
                quality: Some("neural".to_string()),
                description: Some("Piper neural TTS voice (ONNX model)".to_string()),
                sample_rate: Some(22050),
            })
            .collect())
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
            element_index: None,
            document_char_offset: None,
        })
        .collect()
}
