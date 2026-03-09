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
    #[serde(rename = "analyze_document")]
    AnalyzeDocument(AnalyzeDocumentRequest),
    #[serde(rename = "synthesize_document")]
    SynthesizeDocument(SynthesizeDocumentRequest),
    #[serde(rename = "extract_text")]
    ExtractText(ExtractTextRequest),
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
pub struct AnalyzeDocumentRequest {
    pub id: String,
    pub text: String,
    /// Input format: "auto", "plain", "markdown", "html"
    #[serde(default = "default_doc_format")]
    pub format: String,
    /// Whether to use AI enhancement (requires ollama)
    #[serde(default)]
    pub use_ai: bool,
    /// Optional custom voice scheme override
    #[serde(default)]
    pub voice_scheme: Option<serde_json::Value>,
}

fn default_doc_format() -> String {
    "auto".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SynthesizeDocumentRequest {
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
    #[serde(default = "default_alignment")]
    pub alignment: String,
    #[serde(default)]
    pub analyze_quality: bool,
    #[serde(default)]
    pub quality_analyzers: Vec<String>,
    /// Document format: "auto", "plain", "markdown", "html"
    #[serde(default = "default_doc_format")]
    pub format: String,
    /// Use AI enhancement for document analysis
    #[serde(default)]
    pub use_ai: bool,
    /// Optional custom voice scheme override
    #[serde(default)]
    pub voice_scheme: Option<serde_json::Value>,
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
    /// Whether to run quality analysis after synthesis.
    #[serde(default)]
    pub analyze_quality: bool,
    /// Which quality analyzers to run: "asr", "mos", "prosody", "signal". Empty = all.
    #[serde(default)]
    pub quality_analyzers: Vec<String>,
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
    #[serde(rename = "quality_score")]
    QualityScore(QualityScore),
    #[serde(rename = "document_analysis")]
    DocumentAnalysis(DocumentAnalysisResult),
    #[serde(rename = "element_start")]
    ElementStart(ElementStart),
    #[serde(rename = "element_complete")]
    ElementComplete(ElementComplete),
    #[serde(rename = "document_progress")]
    DocumentProgress(DocumentProgress),
    #[serde(rename = "document_synthesis_complete")]
    DocumentSynthesisComplete(DocumentSynthesisComplete),
    #[serde(rename = "ocr_result")]
    OcrResult(OcrResult),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AudioChunk {
    pub id: String,
    pub data_base64: String,
    pub sequence: u32,
    pub is_final: bool,
    pub sample_rate: u32,
    pub channels: u16,
    /// Element index within a document synthesis (progressive mode only).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub element_index: Option<u32>,
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
    /// Element index within a document synthesis (progressive mode only).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub element_index: Option<u32>,
    /// Character offset within the full document (progressive mode only).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub document_char_offset: Option<usize>,
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
pub struct QualityScore {
    pub id: String,
    pub overall_score: f32,
    pub overall_rating: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub asr_confidence: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub asr_wer: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub asr_hypothesis: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mos: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub mos_rating: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub snr_db: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub clip_ratio: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub silence_ratio: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub f0_mean_hz: Option<f32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub f0_range_hz: Option<f32>,
    #[serde(default)]
    pub artifacts: Vec<QualityArtifact>,
    #[serde(default)]
    pub recommendations: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct QualityArtifact {
    #[serde(rename = "type")]
    pub artifact_type: String,
    pub severity: String,
    pub detail: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentAnalysisResult {
    pub id: String,
    pub success: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub format: Option<String>,
    #[serde(default)]
    pub elements: Vec<DocumentElement>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub stats: Option<DocumentStats>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentElement {
    #[serde(rename = "type")]
    pub element_type: String,
    pub text: String,
    pub char_offset: usize,
    pub char_length: usize,
    #[serde(default)]
    pub level: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub voice: Option<DocumentVoiceMapping>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub position: Option<DocumentPosition>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentVoiceMapping {
    #[serde(default = "default_rate")]
    pub rate: f32,
    #[serde(default = "default_pitch")]
    pub pitch: f32,
    #[serde(default = "default_volume")]
    pub volume: f32,
    #[serde(default)]
    pub pause_before_ms: u32,
    #[serde(default)]
    pub pause_after_ms: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub voice_hint: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentPosition {
    pub word_offset: usize,
    pub word_count: usize,
    pub total_words: usize,
    pub progress: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentStats {
    pub total_elements: usize,
    #[serde(default)]
    pub element_counts: std::collections::HashMap<String, usize>,
    pub total_chars: usize,
    pub total_words: usize,
    pub analysis_time_ms: f64,
    #[serde(default)]
    pub ai_enhanced: bool,
}

// -- Phase 4: Progressive Document Synthesis Messages --

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ElementStart {
    pub id: String,
    pub element_index: u32,
    pub element_type: String,
    pub text_preview: String,
    pub char_offset: usize,
    pub char_length: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub voice: Option<DocumentVoiceMapping>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ElementComplete {
    pub id: String,
    pub element_index: u32,
    pub duration_ms: f64,
    pub pause_after_ms: u32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentProgress {
    pub id: String,
    pub elements_completed: u32,
    pub total_elements: u32,
    pub progress: f32,
    pub phase: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct DocumentSynthesisComplete {
    pub id: String,
    pub total_elements: u32,
    pub total_duration_ms: f64,
}

// -- Phase 5: OCR / Vision Types --

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ExtractTextRequest {
    pub id: String,
    /// Base64-encoded image data
    pub image_base64: String,
    /// Image format: "png", "jpg", "webp", etc.
    #[serde(default = "default_image_format")]
    pub image_format: String,
    /// Minimum confidence threshold (0.0-1.0)
    #[serde(default)]
    pub min_confidence: f32,
    /// Optional regions of interest
    #[serde(default)]
    pub regions: Vec<OcrRegionRequest>,
}

fn default_image_format() -> String {
    "png".to_string()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OcrRegionRequest {
    pub label: String,
    pub left: f32,
    pub top: f32,
    pub right: f32,
    pub bottom: f32,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OcrResult {
    pub id: String,
    pub success: bool,
    #[serde(default)]
    pub text: String,
    #[serde(default)]
    pub confidence: f32,
    #[serde(default)]
    pub bounding_boxes: Vec<OcrBoundingBox>,
    #[serde(default)]
    pub total_regions: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub image_width: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub image_height: Option<u32>,
    #[serde(default)]
    pub processing_time_ms: f64,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OcrBoundingBox {
    pub text: String,
    pub confidence: f32,
    pub left: f32,
    pub top: f32,
    pub right: f32,
    pub bottom: f32,
    pub width: f32,
    pub height: f32,
    #[serde(default)]
    pub polygon: Vec<Vec<f32>>,
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
            analyze_quality: false,
            quality_analyzers: vec![],
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
            element_index: None,
            document_char_offset: None,
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
