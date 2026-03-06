//! Quality analysis client — calls quality_server.py HTTP service
//! to get audio quality scores (ASR verification, MOS prediction,
//! prosody analysis, signal quality metrics).

use std::time::Duration;

const DEFAULT_URL: &str = "http://127.0.0.1:21748";
const QUALITY_TIMEOUT: Duration = Duration::from_secs(120);

pub struct QualityClient {
    base_url: String,
    agent: ureq::Agent,
}

// ── Response types (deserialized from quality_server.py JSON) ────────

#[derive(Debug, Clone, serde::Deserialize)]
pub struct QualityAnalysis {
    #[serde(default)]
    pub asr: Option<AsrResult>,
    #[serde(default)]
    pub mos: Option<MosResult>,
    #[serde(default)]
    pub prosody: Option<ProsodyResult>,
    #[serde(default)]
    pub signal: Option<SignalResult>,
    pub overall: OverallScore,
    #[serde(default)]
    pub recommendations: Vec<String>,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct AsrResult {
    pub available: bool,
    #[serde(default)]
    pub hypothesis: Option<String>,
    #[serde(default)]
    pub wer: Option<f32>,
    #[serde(default)]
    pub confidence: Option<f32>,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct MosResult {
    pub available: bool,
    #[serde(default)]
    pub mos: Option<f32>,
    #[serde(default)]
    pub rating: Option<String>,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct ProsodyResult {
    pub available: bool,
    #[serde(default)]
    pub f0: Option<F0Stats>,
    #[serde(default)]
    pub energy: Option<EnergyStats>,
    #[serde(default)]
    pub brightness: Option<BrightnessStats>,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct F0Stats {
    #[serde(default)]
    pub mean_hz: Option<f32>,
    #[serde(default)]
    pub std_hz: Option<f32>,
    #[serde(default)]
    pub min_hz: Option<f32>,
    #[serde(default)]
    pub max_hz: Option<f32>,
    #[serde(default)]
    pub range_hz: Option<f32>,
    #[serde(default)]
    pub voiced_ratio: Option<f32>,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct EnergyStats {
    #[serde(default)]
    pub mean_db: Option<f32>,
    #[serde(default)]
    pub max_db: Option<f32>,
    #[serde(default)]
    pub dynamic_range_db: Option<f32>,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct BrightnessStats {
    #[serde(default)]
    pub mean_hz: Option<f32>,
    #[serde(default)]
    pub std_hz: Option<f32>,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct SignalResult {
    pub snr_db: f32,
    pub clip_ratio: f32,
    pub silence_ratio: f32,
    #[serde(default)]
    pub artifacts: Vec<Artifact>,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct Artifact {
    #[serde(rename = "type")]
    pub artifact_type: String,
    pub severity: String,
    pub detail: String,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct OverallScore {
    pub score: f32,
    pub rating: String,
    pub num_analyzers: u32,
}

// ── Client implementation ────────────────────────────────────────────

impl QualityClient {
    pub fn new(base_url: Option<&str>) -> Self {
        let base_url = base_url.unwrap_or(DEFAULT_URL).to_string();
        let agent = ureq::Agent::config_builder()
            .timeout_global(Some(QUALITY_TIMEOUT))
            .http_status_as_error(false)
            .build()
            .new_agent();
        Self { base_url, agent }
    }

    /// Check if the quality server is running.
    pub fn probe(&self) -> bool {
        let url = format!("{}/health", self.base_url);
        matches!(ureq::get(&url).call(), Ok(resp) if resp.status() == 200)
    }

    /// Analyze audio quality.
    ///
    /// Returns a comprehensive quality analysis including ASR verification,
    /// MOS prediction, prosody analysis, and signal quality metrics.
    pub fn analyze(
        &self,
        samples: &[f32],
        sample_rate: u32,
        channels: u16,
        transcript: &str,
        request_id: &str,
        analyzers: Option<&[&str]>,
    ) -> Result<QualityAnalysis, QualityError> {
        let mut pcm_bytes = Vec::with_capacity(samples.len() * 4);
        for &s in samples {
            pcm_bytes.extend_from_slice(&s.to_le_bytes());
        }

        let url = format!("{}/analyze", self.base_url);

        println!(
            "  [quality] Requesting analysis: {} samples @ {}Hz",
            samples.len(),
            sample_rate,
        );

        let analyzers_str = analyzers
            .map(|a| a.join(","))
            .unwrap_or_default();

        let mut req = self
            .agent
            .post(&url)
            .header("Content-Type", "application/octet-stream")
            .header("X-Sample-Rate", &sample_rate.to_string())
            .header("X-Channels", &channels.to_string())
            .header("X-Transcript", transcript)
            .header("X-Request-Id", request_id);

        if !analyzers_str.is_empty() {
            req = req.header("X-Analyzers", &analyzers_str);
        }

        let mut resp = req.send(&pcm_bytes[..]).map_err(|e| {
            QualityError::ServerError(format!(
                "Quality server request failed (is quality_server.py running?): {e}"
            ))
        })?;

        let status = resp.status();
        if status != 200 {
            let body = resp.body_mut().read_to_string().unwrap_or_default();
            return Err(QualityError::ServerError(format!(
                "Quality server returned status {status}: {body}"
            )));
        }

        let body = resp
            .body_mut()
            .read_to_string()
            .map_err(|e| QualityError::ServerError(format!("Failed to read response: {e}")))?;

        let analysis: QualityAnalysis = serde_json::from_str(&body)
            .map_err(|e| QualityError::ServerError(format!("Failed to parse response: {e}")))?;

        println!(
            "  [quality] Analysis complete — overall={:.2} ({}), {} recommendations",
            analysis.overall.score,
            analysis.overall.rating,
            analysis.recommendations.len(),
        );

        Ok(analysis)
    }
}

#[derive(Debug)]
pub enum QualityError {
    ServerError(String),
}

impl std::fmt::Display for QualityError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            QualityError::ServerError(msg) => write!(f, "Quality error: {msg}"),
        }
    }
}
