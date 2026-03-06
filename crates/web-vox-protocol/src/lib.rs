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
    #[serde(rename = "get_system_info")]
    GetSystemInfo,
    #[serde(rename = "validate_voice")]
    ValidateVoice(ValidateVoiceRequest),
    #[serde(rename = "list_piper_catalog")]
    ListPiperCatalog,
    #[serde(rename = "download_piper_voice")]
    DownloadPiperVoice(DownloadPiperVoiceRequest),
    #[serde(rename = "list_voice_samples")]
    ListVoiceSamples,
    #[serde(rename = "upload_voice_sample")]
    UploadVoiceSample(UploadVoiceSampleRequest),
    #[serde(rename = "delete_voice_sample")]
    DeleteVoiceSample(DeleteVoiceSampleRequest),
    #[serde(rename = "manage_server")]
    ManageServer(ManageServerRequest),
    #[serde(rename = "get_server_stats")]
    GetServerStats,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidateVoiceRequest {
    pub voice_id: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DownloadPiperVoiceRequest {
    pub key: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UploadVoiceSampleRequest {
    pub name: String,
    /// Base64-encoded WAV data
    pub data_base64: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DeleteVoiceSampleRequest {
    pub name: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ManageServerRequest {
    pub engine: String,
    pub action: String, // "start", "stop", "restart"
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
    /// Alignment granularity: "none", "word", "word+syllable", "word+phoneme", "full"
    #[serde(default = "default_alignment")]
    pub alignment: String,
}

fn default_alignment() -> String {
    "word".to_string()
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
    #[serde(rename = "system_info")]
    SystemInfo(SystemInfo),
    #[serde(rename = "voice_validation")]
    VoiceValidation(VoiceValidation),
    #[serde(rename = "piper_catalog")]
    PiperCatalog(PiperCatalog),
    #[serde(rename = "piper_download_complete")]
    PiperDownloadComplete(PiperDownloadResult),
    #[serde(rename = "voice_samples")]
    VoiceSamples(VoiceSampleList),
    #[serde(rename = "voice_sample_result")]
    VoiceSampleResult(VoiceSampleResult),
    #[serde(rename = "server_manage_result")]
    ServerManageResult(ServerManageResult),
    #[serde(rename = "server_stats")]
    ServerStats(ServerStatsResponse),
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
    /// Alignment confidence score (0.0-1.0), present when forced alignment is used.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub confidence: Option<f32>,
    /// Phoneme-level boundaries within this word.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub phonemes: Option<Vec<PhonemeBoundary>>,
    /// Syllable-level boundaries within this word.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub syllables: Option<Vec<SyllableBoundary>>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PhonemeBoundary {
    pub phoneme: String,
    pub start_time_ms: f64,
    pub end_time_ms: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyllableBoundary {
    pub text: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub char_offset: Option<usize>,
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
    #[serde(skip_serializing_if = "Option::is_none")]
    pub quality: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sample_rate: Option<u32>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SystemInfo {
    pub os: String,
    pub os_version: String,
    pub arch: String,
    pub cpu_cores: usize,
    pub available_engines: Vec<String>,
    pub hostname: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VoiceValidation {
    pub voice_id: String,
    pub valid: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub suggestion: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PiperCatalog {
    pub voices: Vec<PiperCatalogVoice>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PiperCatalogVoice {
    pub key: String,
    pub name: String,
    pub language: String,
    pub language_name: String,
    pub quality: String,
    pub num_speakers: u32,
    pub size_bytes: u64,
    pub installed: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PiperDownloadResult {
    pub key: String,
    pub success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VoiceSampleList {
    pub samples: Vec<VoiceSampleInfo>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VoiceSampleInfo {
    pub name: String,
    pub filename: String,
    pub size_bytes: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VoiceSampleResult {
    pub name: String,
    pub success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerManageResult {
    pub engine: String,
    pub action: String,
    pub success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerStatsResponse {
    pub servers: Vec<ServerProcessStats>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ServerProcessStats {
    pub engine: String,
    pub name: String,
    pub port: u16,
    pub online: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pid: Option<u32>,
    pub cpu_percent: f32,
    pub memory_mb: f64,
    pub uptime_secs: u64,
    /// Historical CPU usage samples (last 60, one per ~10s)
    pub cpu_history: Vec<f32>,
    /// Historical memory usage samples (last 60, one per ~10s)
    pub memory_history: Vec<f64>,
    /// Timestamped usage log (last ~1 hour, one per ~10s)
    pub usage_log: Vec<UsageLogEntry>,
    pub managed: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UsageLogEntry {
    pub timestamp: u64,
    pub cpu_percent: f32,
    pub memory_mb: f64,
    pub online: bool,
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
            alignment: "word".to_string(),
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
            confidence: None,
            phonemes: None,
            syllables: None,
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
