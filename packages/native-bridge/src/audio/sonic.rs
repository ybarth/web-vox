//! Safe Rust wrapper around libsonic for pitch-preserving time-stretching.

use std::os::raw::c_int;

// FFI bindings to sonic.c (compiled via build.rs)
unsafe extern "C" {
    fn sonicCreateStream(sampleRate: c_int, numChannels: c_int) -> *mut std::ffi::c_void;
    fn sonicDestroyStream(stream: *mut std::ffi::c_void);
    fn sonicSetSpeed(stream: *mut std::ffi::c_void, speed: f32);
    fn sonicSetPitch(stream: *mut std::ffi::c_void, pitch: f32);
    fn sonicSetVolume(stream: *mut std::ffi::c_void, volume: f32);
    fn sonicWriteFloatToStream(
        stream: *mut std::ffi::c_void,
        samples: *const f32,
        numSamples: c_int,
    ) -> c_int;
    fn sonicReadFloatFromStream(
        stream: *mut std::ffi::c_void,
        samples: *mut f32,
        maxSamples: c_int,
    ) -> c_int;
    fn sonicFlushStream(stream: *mut std::ffi::c_void) -> c_int;
    fn sonicSamplesAvailable(stream: *mut std::ffi::c_void) -> c_int;
}

/// Apply pitch-preserving speed change to PCM float32 audio using libsonic.
///
/// `speed` > 1.0 speeds up, < 1.0 slows down. Pitch is preserved.
/// Returns the time-stretched samples.
pub fn time_stretch(
    samples: &[f32],
    sample_rate: u32,
    channels: u16,
    speed: f32,
) -> Vec<f32> {
    if samples.is_empty() || (speed - 1.0).abs() < 0.01 {
        return samples.to_vec();
    }

    let speed = speed.clamp(0.05, 20.0);

    unsafe {
        let stream = sonicCreateStream(sample_rate as c_int, channels as c_int);
        if stream.is_null() {
            // Allocation failed — return original samples
            return samples.to_vec();
        }

        sonicSetSpeed(stream, speed);
        // Keep pitch at 1.0 — this is the whole point (no chipmunk)
        sonicSetPitch(stream, 1.0);
        sonicSetVolume(stream, 1.0);

        // Write all input samples (numSamples is per-channel frames)
        let num_frames = samples.len() as c_int / channels as c_int;
        let wrote = sonicWriteFloatToStream(stream, samples.as_ptr(), num_frames);
        if wrote == 0 {
            sonicDestroyStream(stream);
            return samples.to_vec();
        }

        sonicFlushStream(stream);

        // Read all output
        let available = sonicSamplesAvailable(stream);
        let out_len = available as usize * channels as usize;
        let mut output = vec![0.0f32; out_len];
        let read = sonicReadFloatFromStream(stream, output.as_mut_ptr(), available);
        output.truncate(read as usize * channels as usize);

        sonicDestroyStream(stream);
        output
    }
}
