//! Document analyzer client — calls document_analyzer_server.py HTTP service
//! to parse text into structured document elements with voice scheme mappings.

use std::time::Duration;

const DEFAULT_URL: &str = "http://127.0.0.1:21750";
const ANALYZER_TIMEOUT: Duration = Duration::from_secs(30);

pub struct DocumentAnalyzerClient {
    base_url: String,
    agent: ureq::Agent,
}

// ── Response types ───────────────────────────────────────────────────

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct DocumentAnalysis {
    pub success: bool,
    #[serde(default)]
    pub format: Option<String>,
    #[serde(default)]
    pub elements: Vec<DocumentElement>,
    #[serde(default)]
    pub stats: Option<DocumentStats>,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct DocumentElement {
    #[serde(rename = "type")]
    pub element_type: String,
    pub text: String,
    pub char_offset: usize,
    pub char_length: usize,
    #[serde(default)]
    pub level: u32,
    #[serde(default)]
    pub voice: Option<VoiceMapping>,
    #[serde(default)]
    pub position: Option<PositionInfo>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct VoiceMapping {
    #[serde(default = "default_one")]
    pub rate: f32,
    #[serde(default = "default_one")]
    pub pitch: f32,
    #[serde(default = "default_one")]
    pub volume: f32,
    #[serde(default)]
    pub pause_before_ms: u32,
    #[serde(default)]
    pub pause_after_ms: u32,
    #[serde(default)]
    pub voice_hint: Option<String>,
}

fn default_one() -> f32 {
    1.0
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct PositionInfo {
    pub word_offset: usize,
    pub word_count: usize,
    pub total_words: usize,
    pub progress: f32,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
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

// ── Client ───────────────────────────────────────────────────────────

impl DocumentAnalyzerClient {
    pub fn new(base_url: Option<&str>) -> Self {
        let base_url = base_url.unwrap_or(DEFAULT_URL).to_string();
        let agent = ureq::Agent::config_builder()
            .timeout_global(Some(ANALYZER_TIMEOUT))
            .http_status_as_error(false)
            .build()
            .new_agent();
        Self { base_url, agent }
    }

    pub fn probe(&self) -> bool {
        let url = format!("{}/health", self.base_url);
        matches!(ureq::get(&url).call(), Ok(resp) if resp.status() == 200)
    }

    pub fn analyze(
        &self,
        text: &str,
        format: Option<&str>,
        use_ai: bool,
    ) -> Result<DocumentAnalysis, DocumentAnalyzerError> {
        let url = format!("{}/analyze", self.base_url);

        println!(
            "  [doc-analyzer] Requesting analysis: {} chars, format={:?}",
            text.len(),
            format.unwrap_or("auto"),
        );

        let body = serde_json::json!({
            "text": text,
            "format": format.unwrap_or("auto"),
            "use_ai": use_ai,
        });

        let mut resp = self
            .agent
            .post(&url)
            .header("Content-Type", "application/json")
            .send(body.to_string().as_bytes())
            .map_err(|e| {
                DocumentAnalyzerError::ServerError(format!(
                    "Document analyzer request failed (is document_analyzer_server.py running?): {e}"
                ))
            })?;

        let status = resp.status();
        if status != 200 {
            let body = resp.body_mut().read_to_string().unwrap_or_default();
            return Err(DocumentAnalyzerError::ServerError(format!(
                "Document analyzer returned status {status}: {body}"
            )));
        }

        let body = resp
            .body_mut()
            .read_to_string()
            .map_err(|e| DocumentAnalyzerError::ServerError(format!("Failed to read response: {e}")))?;

        let analysis: DocumentAnalysis = serde_json::from_str(&body)
            .map_err(|e| DocumentAnalyzerError::ServerError(format!("Failed to parse response: {e}")))?;

        println!(
            "  [doc-analyzer] Got {} elements",
            analysis.elements.len(),
        );

        Ok(analysis)
    }
}

#[derive(Debug)]
pub enum DocumentAnalyzerError {
    ServerError(String),
}

impl std::fmt::Display for DocumentAnalyzerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DocumentAnalyzerError::ServerError(msg) => write!(f, "Document analyzer error: {msg}"),
        }
    }
}
