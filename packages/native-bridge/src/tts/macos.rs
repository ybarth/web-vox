//! macOS TTS using AVSpeechSynthesizer.write(toBufferCallback:)
//!
//! Captures audio as PCM buffers via the buffer callback, and word boundary
//! timing via an AVSpeechSynthesizerDelegate. The delegate's
//! willSpeakRangeOfSpeechString callback fires on the same RunLoop thread
//! as the buffer callback, giving us the character range of each word at the
//! moment it begins. We snapshot the current sample count at that point to
//! compute precise timing.

#![cfg(target_os = "macos")]

use std::ptr::NonNull;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use block2::RcBlock;
use objc2::rc::Retained;
use objc2::runtime::{NSObject, NSObjectProtocol, ProtocolObject};
use objc2::{define_class, msg_send, AllocAnyThread, DefinedClass};
use objc2_avf_audio::{
    AVAudioBuffer, AVSpeechSynthesisVoice, AVSpeechSynthesisVoiceGender,
    AVSpeechSynthesizerDelegate, AVSpeechSynthesizer, AVSpeechUtterance,
};
use objc2_foundation::{NSRange, NSString};

use crate::audio::capture::AudioCapture;
use crate::tts::traits::{SynthesisOptions, SynthesisOutput, TtsError, TtsSynthesizer};
use web_vox_protocol::{VoiceDescriptor, WordBoundary};

/// Shared state between the buffer callback and the delegate.
struct SharedState {
    text: String,
    request_id: String,
    sample_rate: u32,
    channels: u16,
    word_boundaries: Vec<WordBoundary>,
}

/// Ivars for TtsDelegate — stored inside the ObjC object.
struct TtsDelegateIvars {
    shared: Arc<Mutex<SharedState>>,
    capture: AudioCapture,
}

define_class!(
    #[unsafe(super(NSObject))]
    #[ivars = TtsDelegateIvars]
    #[name = "WebVoxTtsDelegate"]
    struct TtsDelegate;

    unsafe impl NSObjectProtocol for TtsDelegate {}

    unsafe impl AVSpeechSynthesizerDelegate for TtsDelegate {
        #[unsafe(method(speechSynthesizer:willSpeakRangeOfSpeechString:utterance:))]
        fn speech_synthesizer_will_speak_range(
            &self,
            _synthesizer: &AVSpeechSynthesizer,
            character_range: NSRange,
            _utterance: &AVSpeechUtterance,
        ) {
            let ivars = self.ivars();
            // Snapshot the current sample count to compute timing.
            let current_samples = ivars.capture.sample_count();
            let mut shared = ivars.shared.lock().unwrap();

            let start_time_ms = if shared.sample_rate > 0 && shared.channels > 0 {
                let frames = current_samples as f64 / shared.channels as f64;
                (frames / shared.sample_rate as f64) * 1000.0
            } else {
                0.0
            };

            let word = utf16_range_to_str(
                &shared.text,
                character_range.location,
                character_range.length,
            );

            let req_id = shared.request_id.clone();
            shared.word_boundaries.push(WordBoundary {
                id: req_id,
                word,
                char_offset: character_range.location,
                char_length: character_range.length,
                start_time_ms,
                end_time_ms: start_time_ms, // fixed up after synthesis
            });
        }
    }
);

impl TtsDelegate {
    fn new(shared: Arc<Mutex<SharedState>>, capture: AudioCapture) -> Retained<Self> {
        let this = Self::alloc().set_ivars(TtsDelegateIvars { shared, capture });
        unsafe { msg_send![super(this), init] }
    }
}

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
        request_id: &str,
        options: &SynthesisOptions,
    ) -> Result<SynthesisOutput, TtsError> {
        let capture = AudioCapture::new(22050, 1);
        let finished = Arc::new(AtomicBool::new(false));

        let shared = Arc::new(Mutex::new(SharedState {
            text: text.to_string(),
            request_id: request_id.to_string(),
            sample_rate: 22050,
            channels: 1,
            word_boundaries: Vec::new(),
        }));

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

            // Create and set the delegate for word boundary callbacks
            let delegate = TtsDelegate::new(Arc::clone(&shared), capture.clone());
            let delegate_proto: &ProtocolObject<dyn AVSpeechSynthesizerDelegate> =
                ProtocolObject::from_ref(&*delegate);
            synthesizer.setDelegate(Some(delegate_proto));

            // Buffer callback — accumulates PCM samples
            let capture_clone = capture.clone();
            let finished_clone = Arc::clone(&finished);

            let buffer_block = RcBlock::new(move |buffer: NonNull<AVAudioBuffer>| {
                let buffer_ref = buffer.as_ref();
                let frame_length: u32 = msg_send![buffer_ref, frameLength];

                if frame_length == 0 {
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

            // Call the 2-arg writeUtterance:toBufferCallback: (works on all macOS versions)
            let buffer_ptr: *mut block2::Block<dyn Fn(NonNull<AVAudioBuffer>)> =
                &*buffer_block as *const _ as *mut _;
            synthesizer.writeUtterance_toBufferCallback(&utterance, buffer_ptr);

            // Spin the RunLoop so buffer and delegate callbacks can fire.
            let run_loop: *mut objc2::runtime::AnyObject =
                msg_send![objc2::class!(NSRunLoop), currentRunLoop];

            let timeout_s = 30.0_f64;
            let start = std::time::Instant::now();

            while !finished.load(Ordering::SeqCst) {
                if start.elapsed().as_secs_f64() > timeout_s {
                    return Err(TtsError::SynthesisFailed(
                        "Synthesis timed out after 30s".into(),
                    ));
                }
                let future_date: *mut objc2::runtime::AnyObject =
                    msg_send![objc2::class!(NSDate), dateWithTimeIntervalSinceNow: 0.05_f64];
                let _: () = msg_send![run_loop, runUntilDate: future_date];
            }

            // Keep delegate alive until synthesis completes
            let _ = &delegate;
        }

        let (samples, sample_rate, channels) = capture.take_samples();
        let total_duration_ms = if sample_rate > 0 && channels > 0 {
            let frames = samples.len() as f64 / channels as f64;
            (frames / sample_rate as f64) * 1000.0
        } else {
            0.0
        };

        // Fix up word boundary end times: each word ends when the next begins
        let mut wbs = shared.lock().unwrap().word_boundaries.clone();
        for i in 0..wbs.len() {
            wbs[i].end_time_ms = if i + 1 < wbs.len() {
                wbs[i + 1].start_time_ms
            } else {
                total_duration_ms
            };
        }

        println!(
            "  Word boundaries: {} words captured from TTS engine",
            wbs.len()
        );

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

/// Convert a UTF-16 range (from NSRange) to a Rust String.
/// NSString uses UTF-16 internally; Rust strings are UTF-8.
fn utf16_range_to_str(text: &str, utf16_location: usize, utf16_length: usize) -> String {
    let mut byte_start = None;
    let mut byte_end = None;
    let mut utf16_pos = 0;

    for (byte_idx, ch) in text.char_indices() {
        if utf16_pos == utf16_location && byte_start.is_none() {
            byte_start = Some(byte_idx);
        }
        utf16_pos += ch.len_utf16();
        if utf16_pos >= utf16_location + utf16_length && byte_end.is_none() {
            byte_end = Some(byte_idx + ch.len_utf8());
            break;
        }
    }

    match (byte_start, byte_end) {
        (Some(s), Some(e)) if e <= text.len() => text[s..e].to_string(),
        (Some(s), None) => text[s..].to_string(),
        _ => String::new(),
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
