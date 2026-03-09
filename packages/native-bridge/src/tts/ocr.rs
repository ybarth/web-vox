//! OCR client — calls ocr_server.py HTTP service to extract text from
//! images with spatial bounding box coordinates.

use std::time::Duration;

const DEFAULT_URL: &str = "http://127.0.0.1:21751";
const OCR_TIMEOUT: Duration = Duration::from_secs(60);

pub struct OcrClient {
    base_url: String,
    agent: ureq::Agent,
}

// ── Response types ───────────────────────────────────────────────────

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct OcrExtraction {
    pub success: bool,
    #[serde(default)]
    pub text: String,
    #[serde(default)]
    pub confidence: f32,
    #[serde(default)]
    pub bounding_boxes: Vec<OcrBoundingBox>,
    #[serde(default)]
    pub total_regions: usize,
    #[serde(default)]
    pub image_width: Option<u32>,
    #[serde(default)]
    pub image_height: Option<u32>,
    #[serde(default)]
    pub processing_time_ms: f64,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
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

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct OcrRegionResult {
    pub success: bool,
    #[serde(default)]
    pub regions: Vec<OcrRegion>,
    #[serde(default)]
    pub total_regions: usize,
    #[serde(default)]
    pub image_width: Option<u32>,
    #[serde(default)]
    pub image_height: Option<u32>,
    #[serde(default)]
    pub processing_time_ms: f64,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct OcrRegion {
    pub label: String,
    pub region: OcrRect,
    pub text: String,
    pub confidence: f32,
    #[serde(default)]
    pub bounding_boxes: Vec<OcrBoundingBox>,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct OcrRect {
    pub left: f32,
    pub top: f32,
    pub right: f32,
    pub bottom: f32,
}

// ── Client ───────────────────────────────────────────────────────────

impl OcrClient {
    pub fn new(base_url: Option<&str>) -> Self {
        let base_url = base_url.unwrap_or(DEFAULT_URL).to_string();
        let agent = ureq::Agent::config_builder()
            .timeout_global(Some(OCR_TIMEOUT))
            .http_status_as_error(false)
            .build()
            .new_agent();
        Self { base_url, agent }
    }

    pub fn probe(&self) -> bool {
        let url = format!("{}/health", self.base_url);
        matches!(ureq::get(&url).call(), Ok(resp) if resp.status() == 200)
    }

    pub fn extract(
        &self,
        image_base64: &str,
        image_format: &str,
        min_confidence: f32,
    ) -> Result<OcrExtraction, OcrError> {
        let url = format!("{}/extract", self.base_url);

        println!(
            "  [ocr] Requesting OCR extraction: format={}, min_confidence={}",
            image_format, min_confidence,
        );

        let body = serde_json::json!({
            "image_base64": image_base64,
            "image_format": image_format,
            "min_confidence": min_confidence,
        });

        let mut resp = self
            .agent
            .post(&url)
            .header("Content-Type", "application/json")
            .send(body.to_string().as_bytes())
            .map_err(|e| {
                OcrError::ServerError(format!(
                    "OCR request failed (is ocr_server.py running?): {e}"
                ))
            })?;

        let status = resp.status();
        if status != 200 {
            let body = resp.body_mut().read_to_string().unwrap_or_default();
            return Err(OcrError::ServerError(format!(
                "OCR server returned status {status}: {body}"
            )));
        }

        let body = resp
            .body_mut()
            .read_to_string()
            .map_err(|e| OcrError::ServerError(format!("Failed to read response: {e}")))?;

        let extraction: OcrExtraction = serde_json::from_str(&body)
            .map_err(|e| OcrError::ServerError(format!("Failed to parse response: {e}")))?;

        println!(
            "  [ocr] Got {} regions, confidence={:.2}",
            extraction.bounding_boxes.len(),
            extraction.confidence,
        );

        Ok(extraction)
    }

    pub fn extract_regions(
        &self,
        image_base64: &str,
        image_format: &str,
        regions: &[serde_json::Value],
    ) -> Result<OcrRegionResult, OcrError> {
        let url = format!("{}/extract_regions", self.base_url);

        let body = serde_json::json!({
            "image_base64": image_base64,
            "image_format": image_format,
            "regions": regions,
        });

        let mut resp = self
            .agent
            .post(&url)
            .header("Content-Type", "application/json")
            .send(body.to_string().as_bytes())
            .map_err(|e| {
                OcrError::ServerError(format!("OCR region request failed: {e}"))
            })?;

        let status = resp.status();
        if status != 200 {
            let body = resp.body_mut().read_to_string().unwrap_or_default();
            return Err(OcrError::ServerError(format!(
                "OCR server returned status {status}: {body}"
            )));
        }

        let body = resp
            .body_mut()
            .read_to_string()
            .map_err(|e| OcrError::ServerError(format!("Failed to read response: {e}")))?;

        let result: OcrRegionResult = serde_json::from_str(&body)
            .map_err(|e| OcrError::ServerError(format!("Failed to parse response: {e}")))?;

        Ok(result)
    }
}

#[derive(Debug)]
pub enum OcrError {
    ServerError(String),
}

impl std::fmt::Display for OcrError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            OcrError::ServerError(msg) => write!(f, "OCR error: {msg}"),
        }
    }
}
