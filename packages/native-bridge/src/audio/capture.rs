//! PCM buffer accumulation from OS TTS callbacks.

use std::sync::{Arc, Mutex};

/// Accumulates PCM audio samples from TTS callbacks.
#[derive(Clone)]
pub struct AudioCapture {
    inner: Arc<Mutex<CaptureInner>>,
}

struct CaptureInner {
    samples: Vec<f32>,
    sample_rate: u32,
    channels: u16,
}

impl AudioCapture {
    pub fn new(sample_rate: u32, channels: u16) -> Self {
        Self {
            inner: Arc::new(Mutex::new(CaptureInner {
                samples: Vec::new(),
                sample_rate,
                channels,
            })),
        }
    }

    /// Append PCM float samples from a TTS callback.
    pub fn append_samples(&self, samples: &[f32]) {
        let mut inner = self.inner.lock().unwrap();
        inner.samples.extend_from_slice(samples);
    }

    /// Append PCM int16 samples (common from AVSpeechSynthesizer), converting to f32.
    pub fn append_int16_samples(&self, samples: &[i16]) {
        let mut inner = self.inner.lock().unwrap();
        inner.samples.extend(samples.iter().map(|&s| s as f32 / 32768.0));
    }

    /// Get the total number of samples captured so far.
    pub fn sample_count(&self) -> usize {
        self.inner.lock().unwrap().samples.len()
    }

    /// Get current duration in milliseconds.
    pub fn duration_ms(&self) -> f64 {
        let inner = self.inner.lock().unwrap();
        if inner.sample_rate == 0 || inner.channels == 0 {
            return 0.0;
        }
        let frames = inner.samples.len() as f64 / inner.channels as f64;
        (frames / inner.sample_rate as f64) * 1000.0
    }

    /// Take the accumulated samples, leaving the capture empty.
    pub fn take_samples(&self) -> (Vec<f32>, u32, u16) {
        let mut inner = self.inner.lock().unwrap();
        let samples = std::mem::take(&mut inner.samples);
        (samples, inner.sample_rate, inner.channels)
    }

    /// Get a copy of accumulated samples without consuming.
    pub fn get_samples(&self) -> (Vec<f32>, u32, u16) {
        let inner = self.inner.lock().unwrap();
        (inner.samples.clone(), inner.sample_rate, inner.channels)
    }

    pub fn sample_rate(&self) -> u32 {
        self.inner.lock().unwrap().sample_rate
    }

    pub fn channels(&self) -> u16 {
        self.inner.lock().unwrap().channels
    }
}
