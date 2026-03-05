//! macOS TTS using AVSpeechSynthesizer.write(toBufferCallback:)
//!
//! Captures audio as PCM buffers instead of routing to speakers.
//!
//! Key insight: `writeUtterance_toBufferCallback()` dispatches buffer callbacks
//! on the current thread's RunLoop. We must spin the RunLoop while waiting
//! for synthesis to complete, not block with a Condvar.

#![cfg(target_os = "macos")]

use std::ptr::NonNull;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use block2::RcBlock;
use objc2::msg_send;
use objc2::runtime::AnyObject;
use objc2::AllocAnyThread;
use objc2_avf_audio::{
    AVAudioBuffer, AVSpeechSynthesisVoice, AVSpeechSynthesisVoiceGender, AVSpeechSynthesizer,
    AVSpeechUtterance,
};
use objc2_foundation::NSString;

use crate::audio::capture::AudioCapture;
use crate::tts::traits::{SynthesisOptions, SynthesisOutput, TtsError, TtsSynthesizer};
use web_vox_protocol::{VoiceDescriptor, WordBoundary};

/// macOS TTS synthesizer that captures audio via AVSpeechSynthesizer.write().
pub struct MacOsSynthesizer;

impl MacOsSynthesizer {
    pub fn new() -> Self {
        Self
    }
}

impl Default for MacOsSynthesizer {
    fn default() -> Self {
        Self::new()
    }
}

impl TtsSynthesizer for MacOsSynthesizer {
    fn synthesize(
        &self,
        text: &str,
        _request_id: &str,
        options: &SynthesisOptions,
    ) -> Result<SynthesisOutput, TtsError> {
        let capture = AudioCapture::new(22050, 1);
        let word_boundaries: Arc<Mutex<Vec<WordBoundary>>> = Arc::new(Mutex::new(Vec::new()));
        let finished = Arc::new(AtomicBool::new(false));

        unsafe {
            let ns_text = NSString::from_str(text);
            let utterance =
                AVSpeechUtterance::initWithString(AVSpeechUtterance::alloc(), &ns_text);

            // Set voice
            if let Some(ref voice_id) = options.voice_id {
                let ns_voice_id = NSString::from_str(voice_id);
                if let Some(voice) = AVSpeechSynthesisVoice::voiceWithIdentifier(&ns_voice_id) {
                    utterance.setVoice(Some(&voice));
                }
            }

            // Map rate: user 1.0 -> AVSpeech 0.5 (default)
            let av_rate = (options.rate * 0.5).clamp(0.0, 1.0);
            utterance.setRate(av_rate);
            utterance.setPitchMultiplier(options.pitch.clamp(0.5, 2.0));
            utterance.setVolume(options.volume.clamp(0.0, 1.0));

            let synthesizer = AVSpeechSynthesizer::new();

            // Buffer callback — accumulates PCM samples
            let capture_clone = capture.clone();
            let finished_clone = Arc::clone(&finished);

            let block = RcBlock::new(move |buffer: NonNull<AVAudioBuffer>| {
                let buffer_ref = buffer.as_ref();
                let frame_length: u32 = msg_send![buffer_ref, frameLength];

                if frame_length == 0 {
                    // Empty buffer = synthesis complete
                    finished_clone.store(true, Ordering::SeqCst);
                    return;
                }

                // Try int16 channel data (AVSpeech default: int16 @ 22050Hz mono)
                let int16_data: *const *const i16 = msg_send![buffer_ref, int16ChannelData];
                if !int16_data.is_null() {
                    let channel_ptr = *int16_data;
                    if !channel_ptr.is_null() {
                        let samples =
                            std::slice::from_raw_parts(channel_ptr, frame_length as usize);
                        capture_clone.append_int16_samples(samples);
                        return;
                    }
                }

                // Fallback: float channel data
                let float_data: *const *const f32 = msg_send![buffer_ref, floatChannelData];
                if !float_data.is_null() {
                    let channel_ptr = *float_data;
                    if !channel_ptr.is_null() {
                        let samples =
                            std::slice::from_raw_parts(channel_ptr, frame_length as usize);
                        capture_clone.append_samples(samples);
                    }
                }
            });

            // Start synthesis
            let block_ptr: *mut block2::Block<dyn Fn(NonNull<AVAudioBuffer>)> =
                &*block as *const _ as *mut _;
            synthesizer.writeUtterance_toBufferCallback(&utterance, block_ptr);

            // Spin the RunLoop to let callbacks fire.
            // AVSpeechSynthesizer dispatches buffer callbacks on the current
            // thread's RunLoop, so we must run it until synthesis completes.
            // Spin the RunLoop so buffer callbacks can fire.
            // AVSpeechSynthesizer dispatches on the current thread's RunLoop.
            let run_loop: *mut AnyObject = msg_send![objc2::class!(NSRunLoop), currentRunLoop];

            let timeout_s = 30.0_f64;
            let start = std::time::Instant::now();

            while !finished.load(Ordering::SeqCst) {
                if start.elapsed().as_secs_f64() > timeout_s {
                    return Err(TtsError::SynthesisFailed(
                        "Synthesis timed out after 30s".into(),
                    ));
                }
                // Run the RunLoop for 50ms intervals to pump callbacks
                let future_date: *mut AnyObject =
                    msg_send![objc2::class!(NSDate), dateWithTimeIntervalSinceNow: 0.05_f64];
                let _: () = msg_send![run_loop, runUntilDate: future_date];
            }
        }

        let (samples, sample_rate, channels) = capture.take_samples();
        let total_duration_ms = if sample_rate > 0 && channels > 0 {
            let frames = samples.len() as f64 / channels as f64;
            (frames / sample_rate as f64) * 1000.0
        } else {
            0.0
        };

        let wbs = word_boundaries.lock().unwrap().clone();

        Ok(SynthesisOutput {
            samples,
            sample_rate,
            channels,
            word_boundaries: wbs,
            total_duration_ms,
        })
    }

    fn list_voices(&self) -> Result<Vec<VoiceDescriptor>, TtsError> {
        list_avspeech_voices()
    }
}

fn list_avspeech_voices() -> Result<Vec<VoiceDescriptor>, TtsError> {
    let mut result = Vec::new();

    unsafe {
        let voices = AVSpeechSynthesisVoice::speechVoices();

        for voice in voices.iter() {
            let id = voice.identifier().to_string();
            let name = voice.name().to_string();
            let language = voice.language().to_string();
            let gender = voice.gender();
            let gender_str = match gender {
                AVSpeechSynthesisVoiceGender::Male => Some("male".to_string()),
                AVSpeechSynthesisVoiceGender::Female => Some("female".to_string()),
                _ => None,
            };

            result.push(VoiceDescriptor {
                id,
                name,
                language,
                gender: gender_str,
                engine: "macos-avspeech".to_string(),
            });
        }
    }

    Ok(result)
}
