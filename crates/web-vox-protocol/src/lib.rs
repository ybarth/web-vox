//! Shared protocol types for web-vox native messaging and WebSocket transport.

use serde::{Deserialize, Serialize};

// -- Client -> Host Messages --

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum ClientMessage {
    #[serde(rename = "synthesize")]
    Synthesize(SynthesizeRequest),
    #[serde(rename = "cancel")]
    Cancel(CancelRequest),
    #[serde(rename = "list_voices")]
    ListVoices,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SynthesizeRequest {
    pub id: String,
    pub text: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub voice_id: Option<String>,
    #[serde(default = "default_rate")]
    pub rate: f32,
    #[serde(default = "default_pitch")]
    pub pitch: f32,
    #[serde(default = "default_volume")]
    pub volume: f32,
}

fn default_rate() -> f32 {
    1.0
}
fn default_pitch() -> f32 {
    1.0
}
fn default_volume() -> f32 {
    1.0
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CancelRequest {
    pub id: String,
}

// -- Host -> Client Messages --

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum HostMessage {
    #[serde(rename = "audio_chunk")]
    AudioChunk(AudioChunk),
    #[serde(rename = "word_boundary")]
    WordBoundary(WordBoundary),
    #[serde(rename = "synthesis_complete")]
    SynthesisComplete(SynthesisComplete),
    #[serde(rename = "voice_list")]
    VoiceList(VoiceList),
    #[serde(rename = "error")]
    Error(ErrorMessage),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioChunk {
    pub id: String,
    pub data_base64: String,
    pub sequence: u32,
    pub is_final: bool,
    pub sample_rate: u32,
    pub channels: u16,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct WordBoundary {
    pub id: String,
    pub word: String,
    pub char_offset: usize,
    pub char_length: usize,
    pub start_time_ms: f64,
    pub end_time_ms: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SynthesisComplete {
    pub id: String,
    pub total_duration_ms: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VoiceList {
    pub voices: Vec<VoiceDescriptor>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VoiceDescriptor {
    pub id: String,
    pub name: String,
    pub language: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub gender: Option<String>,
    pub engine: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ErrorMessage {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub id: Option<String>,
    pub code: String,
    pub message: String,
}

// -- Encoding helpers --

/// Encode raw PCM bytes as base64.
pub fn encode_audio_base64(pcm_bytes: &[u8]) -> String {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD.encode(pcm_bytes)
}

/// Decode base64 audio back to raw PCM bytes.
pub fn decode_audio_base64(b64: &str) -> Result<Vec<u8>, base64::DecodeError> {
    use base64::Engine;
    base64::engine::general_purpose::STANDARD.decode(b64)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn serialize_synthesize_request() {
        let msg = ClientMessage::Synthesize(SynthesizeRequest {
            id: "req-1".into(),
            text: "Hello world".into(),
            voice_id: Some("com.apple.voice.compact.en-US.Samantha".into()),
            rate: 1.0,
            pitch: 1.0,
            volume: 1.0,
        });
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains("\"type\":\"synthesize\""));
        assert!(json.contains("Hello world"));
    }

    #[test]
    fn serialize_word_boundary() {
        let msg = HostMessage::WordBoundary(WordBoundary {
            id: "req-1".into(),
            word: "Hello".into(),
            char_offset: 0,
            char_length: 5,
            start_time_ms: 0.0,
            end_time_ms: 350.0,
        });
        let json = serde_json::to_string(&msg).unwrap();
        assert!(json.contains("\"type\":\"word_boundary\""));
    }

    #[test]
    fn audio_base64_roundtrip() {
        let pcm = vec![0u8, 1, 2, 3, 4, 5];
        let encoded = encode_audio_base64(&pcm);
        let decoded = decode_audio_base64(&encoded).unwrap();
        assert_eq!(pcm, decoded);
    }
}
