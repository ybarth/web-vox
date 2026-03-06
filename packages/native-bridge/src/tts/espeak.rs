//! espeak-ng TTS engine — shells out to the `espeak-ng` CLI.
//!
//! Expects `espeak-ng` to be installed (e.g. `brew install espeak-ng`).
//! Uses `--stdout` to get raw WAV output, then parses the PCM from it.

use std::process::{Command, Stdio};

use crate::tts::traits::{SynthesisOptions, SynthesisOutput, TtsError, TtsSynthesizer};
use web_vox_protocol::{VoiceDescriptor, WordBoundary};

pub struct EspeakSynthesizer {
    bin_path: String,
}

impl EspeakSynthesizer {
    pub fn new() -> Result<Self, TtsError> {
        // Check if espeak-ng is available
        let bin_path = which_espeak_ng().ok_or_else(|| {
            TtsError::NotAvailable(
                "espeak-ng not found. Install with: brew install espeak-ng".into(),
            )
        })?;
        Ok(Self { bin_path })
    }
}

fn which_espeak_ng() -> Option<String> {
    Command::new("which")
        .arg("espeak-ng")
        .output()
        .ok()
        .and_then(|o| {
            if o.status.success() {
                Some(String::from_utf8_lossy(&o.stdout).trim().to_string())
            } else {
                None
            }
        })
}

impl TtsSynthesizer for EspeakSynthesizer {
    fn synthesize(
        &self,
        text: &str,
        request_id: &str,
        options: &SynthesisOptions,
    ) -> Result<SynthesisOutput, TtsError> {
        let voice_id = options
            .voice_id
            .as_deref()
            .unwrap_or("espeak-ng:en-us");

        // Strip the "espeak-ng:" prefix to get the actual espeak voice name
        let espeak_voice = voice_id.strip_prefix("espeak-ng:").unwrap_or(voice_id);

        // Map rate: 1.0 = 175 wpm (espeak default)
        let wpm = (175.0 * options.rate).clamp(80.0, 500.0) as u32;

        // Map pitch: 1.0 = 50 (espeak default, range 0-99)
        let pitch_val = (50.0 * options.pitch).clamp(0.0, 99.0) as u32;

        println!("  [espeak-ng] voice={}, wpm={}, pitch={}", espeak_voice, wpm, pitch_val);

        // espeak-ng --stdout outputs a WAV file to stdout
        let output = Command::new(&self.bin_path)
            .arg("--stdout")
            .arg("-v")
            .arg(espeak_voice)
            .arg("-s")
            .arg(wpm.to_string())
            .arg("-p")
            .arg(pitch_val.to_string())
            .arg(text)
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .map_err(|e| TtsError::SynthesisFailed(format!("Failed to run espeak-ng: {e}")))?;

        if !output.status.success() {
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(TtsError::SynthesisFailed(format!(
                "espeak-ng exited with {}: {}",
                output.status, stderr
            )));
        }

        let wav_data = &output.stdout;
        let (samples, sample_rate, channels) = parse_wav_pcm(wav_data)?;

        let total_duration_ms =
            (samples.len() as f64 / channels as f64 / sample_rate as f64) * 1000.0;

        let word_boundaries =
            generate_simple_word_boundaries(text, request_id, total_duration_ms);

        println!(
            "  [espeak-ng] Produced {} samples @ {}Hz ({:.1}s)",
            samples.len(),
            sample_rate,
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
        let output = Command::new(&self.bin_path)
            .arg("--voices")
            .output()
            .map_err(|e| TtsError::SynthesisFailed(format!("Failed to list espeak-ng voices: {e}")))?;

        if !output.status.success() {
            return Err(TtsError::SynthesisFailed(
                "espeak-ng --voices failed".into(),
            ));
        }

        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut voices = Vec::new();

        // espeak-ng --voices output format:
        // Pty Language       Age/Gender VoiceName          File          Other Languages
        //  5  af             M  Afrikaans                default
        for line in stdout.lines().skip(1) {
            let parts: Vec<&str> = line.split_whitespace().collect();
            if parts.len() >= 4 {
                let language = parts[1].to_string();
                let gender_code = parts[2];
                let name = parts[3..].join(" ").split("  ").next().unwrap_or("").to_string();

                // Only include a curated set of voices to avoid flooding the dropdown
                let dominated_langs = [
                    "en", "en-us", "en-gb", "es", "fr", "de", "it", "pt", "ja", "zh", "ko", "ru",
                ];
                if !dominated_langs.iter().any(|l| language.starts_with(l)) {
                    continue;
                }

                let gender = match gender_code {
                    "M" => Some("male".to_string()),
                    "F" => Some("female".to_string()),
                    _ => None,
                };

                let voice_name = if name.is_empty() {
                    language.clone()
                } else {
                    name
                };

                voices.push(VoiceDescriptor {
                    id: format!("espeak-ng:{}", language),
                    name: format!("espeak-ng: {}", voice_name),
                    language: language.replace('-', "_"),
                    gender,
                    engine: "espeak-ng".to_string(),
                    quality: Some("formant".to_string()),
                    description: Some("eSpeak NG formant-based synthesizer".to_string()),
                    sample_rate: Some(22050),
                });
            }
        }

        Ok(voices)
    }
}

/// Parse a WAV file and extract PCM samples as f32.
fn parse_wav_pcm(wav: &[u8]) -> Result<(Vec<f32>, u32, u16), TtsError> {
    if wav.len() < 44 {
        return Err(TtsError::SynthesisFailed("WAV too short".into()));
    }
    if &wav[0..4] != b"RIFF" || &wav[8..12] != b"WAVE" {
        return Err(TtsError::SynthesisFailed("Not a valid WAV file".into()));
    }

    let channels = u16::from_le_bytes([wav[22], wav[23]]);
    let sample_rate = u32::from_le_bytes([wav[24], wav[25], wav[26], wav[27]]);
    let bits_per_sample = u16::from_le_bytes([wav[34], wav[35]]);

    // Find the "data" chunk
    let mut pos = 12;
    while pos + 8 <= wav.len() {
        let chunk_id = &wav[pos..pos + 4];
        let chunk_size = u32::from_le_bytes([wav[pos + 4], wav[pos + 5], wav[pos + 6], wav[pos + 7]]) as usize;

        if chunk_id == b"data" {
            let data_start = pos + 8;
            let data_end = (data_start + chunk_size).min(wav.len());
            let pcm_data = &wav[data_start..data_end];

            let samples = match bits_per_sample {
                16 => {
                    let num = pcm_data.len() / 2;
                    let mut s = Vec::with_capacity(num);
                    for i in 0..num {
                        let lo = pcm_data[i * 2] as i16;
                        let hi = (pcm_data[i * 2 + 1] as i16) << 8;
                        let val = lo | hi;
                        s.push(if val < 0 {
                            val as f32 / 32768.0
                        } else {
                            val as f32 / 32767.0
                        });
                    }
                    s
                }
                8 => {
                    pcm_data
                        .iter()
                        .map(|&b| (b as f32 - 128.0) / 128.0)
                        .collect()
                }
                _ => {
                    return Err(TtsError::SynthesisFailed(format!(
                        "Unsupported bits per sample: {}",
                        bits_per_sample
                    )));
                }
            };

            return Ok((samples, sample_rate, channels));
        }

        pos += 8 + chunk_size;
        // Chunks are word-aligned
        if chunk_size % 2 != 0 {
            pos += 1;
        }
    }

    Err(TtsError::SynthesisFailed("No data chunk in WAV".into()))
}

/// Generate approximate word boundaries by distributing time evenly across words.
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
