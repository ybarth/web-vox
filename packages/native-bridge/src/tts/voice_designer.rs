//! Voice designer client — calls voice_designer_server.py HTTP service
//! for text-prompted voice creation (Parler-TTS), speaker embedding
//! extraction, and multi-sample blending.

use std::time::Duration;

const DEFAULT_URL: &str = "http://127.0.0.1:21749";
const DESIGNER_TIMEOUT: Duration = Duration::from_secs(180);

pub struct VoiceDesignerClient {
    base_url: String,
    agent: ureq::Agent,
}

// ── Response types ──────────────────────────────────────────────────

#[derive(Debug, Clone, serde::Deserialize)]
pub struct DesignResult {
    pub success: bool,
    #[serde(default)]
    pub audio_base64: Option<String>,
    #[serde(default)]
    pub sample_rate: Option<u32>,
    #[serde(default)]
    pub duration_ms: Option<f64>,
    #[serde(default)]
    pub num_samples: Option<usize>,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct EmbeddingResult {
    pub success: bool,
    #[serde(default)]
    pub embedding: Option<Vec<f32>>,
    #[serde(default)]
    pub dimensions: Option<usize>,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct BlendResult {
    pub success: bool,
    #[serde(default)]
    pub embedding: Option<Vec<f32>>,
    #[serde(default)]
    pub dimensions: Option<usize>,
    #[serde(default)]
    pub weights_normalized: Option<Vec<f32>>,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct SaveProfileResult {
    pub success: bool,
    #[serde(default)]
    pub profile_id: Option<String>,
    #[serde(default)]
    pub error: Option<String>,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct VoiceProfileSummary {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub sample_rate: Option<u32>,
    #[serde(default)]
    pub has_embedding: Option<bool>,
    #[serde(default)]
    pub has_reference_audio: Option<bool>,
    #[serde(default)]
    pub created_at: Option<f64>,
}

#[derive(Debug, Clone, serde::Deserialize)]
struct ProfileListResponse {
    profiles: Vec<VoiceProfileSummary>,
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct DeleteProfileResult {
    pub success: bool,
    #[serde(default)]
    pub error: Option<String>,
}

// ── Client implementation ───────────────────────────────────────────

impl VoiceDesignerClient {
    pub fn new(base_url: Option<&str>) -> Self {
        let base_url = base_url.unwrap_or(DEFAULT_URL).to_string();
        let agent = ureq::Agent::config_builder()
            .timeout_global(Some(DESIGNER_TIMEOUT))
            .http_status_as_error(false)
            .build()
            .new_agent();
        Self { base_url, agent }
    }

    /// Check if the voice designer server is running.
    pub fn probe(&self) -> bool {
        let url = format!("{}/health", self.base_url);
        matches!(ureq::get(&url).call(), Ok(resp) if resp.status() == 200)
    }

    /// Design a voice from a text description using Parler-TTS.
    pub fn design(
        &self,
        description: &str,
        preview_text: &str,
    ) -> Result<DesignResult, VoiceDesignerError> {
        let url = format!("{}/design", self.base_url);

        println!(
            "  [voice-designer] Requesting design: '{}'",
            &description[..description.len().min(60)]
        );

        let body = serde_json::json!({
            "description": description,
            "preview_text": preview_text,
        });

        let mut resp = self
            .agent
            .post(&url)
            .header("Content-Type", "application/json")
            .send(body.to_string().as_bytes())
            .map_err(|e| {
                VoiceDesignerError::ServerError(format!(
                    "Voice designer request failed (is voice_designer_server.py running?): {e}"
                ))
            })?;

        self.parse_json_response(&mut resp)
    }

    /// Extract a speaker embedding from audio samples.
    pub fn extract_embedding(
        &self,
        samples: &[f32],
        sample_rate: u32,
    ) -> Result<EmbeddingResult, VoiceDesignerError> {
        let mut pcm_bytes = Vec::with_capacity(samples.len() * 4);
        for &s in samples {
            pcm_bytes.extend_from_slice(&s.to_le_bytes());
        }

        let url = format!("{}/extract_embedding", self.base_url);

        println!(
            "  [voice-designer] Extracting embedding from {} samples @ {}Hz",
            samples.len(),
            sample_rate,
        );

        let mut resp = self
            .agent
            .post(&url)
            .header("Content-Type", "application/octet-stream")
            .header("X-Sample-Rate", &sample_rate.to_string())
            .send(&pcm_bytes[..])
            .map_err(|e| {
                VoiceDesignerError::ServerError(format!(
                    "Embedding extraction failed: {e}"
                ))
            })?;

        self.parse_json_response(&mut resp)
    }

    /// Blend multiple speaker embeddings with weights.
    pub fn blend(
        &self,
        embeddings: &[Vec<f32>],
        weights: &[f32],
    ) -> Result<BlendResult, VoiceDesignerError> {
        let url = format!("{}/blend", self.base_url);

        println!(
            "  [voice-designer] Blending {} embeddings",
            embeddings.len()
        );

        let body = serde_json::json!({
            "embeddings": embeddings,
            "weights": weights,
        });

        let mut resp = self
            .agent
            .post(&url)
            .header("Content-Type", "application/json")
            .send(body.to_string().as_bytes())
            .map_err(|e| {
                VoiceDesignerError::ServerError(format!("Blend request failed: {e}"))
            })?;

        self.parse_json_response(&mut resp)
    }

    /// Save a voice profile.
    pub fn save_profile(
        &self,
        profile_id: &str,
        name: &str,
        description: &str,
        embedding: Option<&[f32]>,
        reference_audio_b64: Option<&str>,
        sample_rate: u32,
    ) -> Result<SaveProfileResult, VoiceDesignerError> {
        let url = format!("{}/save_profile", self.base_url);

        let body = serde_json::json!({
            "profile_id": profile_id,
            "name": name,
            "description": description,
            "embedding": embedding,
            "reference_audio_base64": reference_audio_b64,
            "sample_rate": sample_rate,
        });

        let mut resp = self
            .agent
            .post(&url)
            .header("Content-Type", "application/json")
            .send(body.to_string().as_bytes())
            .map_err(|e| {
                VoiceDesignerError::ServerError(format!("Save profile failed: {e}"))
            })?;

        self.parse_json_response(&mut resp)
    }

    /// List saved voice profiles.
    pub fn list_profiles(&self) -> Result<Vec<VoiceProfileSummary>, VoiceDesignerError> {
        let url = format!("{}/list_profiles", self.base_url);

        let mut resp = ureq::get(&url).call().map_err(|e| {
            VoiceDesignerError::ServerError(format!("List profiles failed: {e}"))
        })?;

        let body = resp
            .body_mut()
            .read_to_string()
            .map_err(|e| VoiceDesignerError::ServerError(format!("Failed to read response: {e}")))?;

        let result: ProfileListResponse = serde_json::from_str(&body)
            .map_err(|e| VoiceDesignerError::ServerError(format!("Failed to parse response: {e}")))?;

        Ok(result.profiles)
    }

    /// Delete a voice profile.
    pub fn delete_profile(
        &self,
        profile_id: &str,
    ) -> Result<DeleteProfileResult, VoiceDesignerError> {
        let url = format!("{}/delete_profile", self.base_url);

        let body = serde_json::json!({ "profile_id": profile_id });

        let mut resp = self
            .agent
            .post(&url)
            .header("Content-Type", "application/json")
            .send(body.to_string().as_bytes())
            .map_err(|e| {
                VoiceDesignerError::ServerError(format!("Delete profile failed: {e}"))
            })?;

        self.parse_json_response(&mut resp)
    }

    fn parse_json_response<T: serde::de::DeserializeOwned>(
        &self,
        resp: &mut ureq::http::Response<ureq::Body>,
    ) -> Result<T, VoiceDesignerError> {
        let status = resp.status();
        let body = resp
            .body_mut()
            .read_to_string()
            .map_err(|e| VoiceDesignerError::ServerError(format!("Failed to read response: {e}")))?;

        if status != 200 {
            return Err(VoiceDesignerError::ServerError(format!(
                "Server returned status {status}: {body}"
            )));
        }

        serde_json::from_str(&body)
            .map_err(|e| VoiceDesignerError::ServerError(format!("Failed to parse response: {e}")))
    }
}

#[derive(Debug)]
pub enum VoiceDesignerError {
    ServerError(String),
}

impl std::fmt::Display for VoiceDesignerError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            VoiceDesignerError::ServerError(msg) => write!(f, "Voice designer error: {msg}"),
        }
    }
}
