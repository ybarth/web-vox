//! Quick integration test: synthesize "Hello world" on macOS and verify we get audio back.
//!
//! Run with:
//!   cargo run --example test_synth

#[cfg(target_os = "macos")]
fn main() {
    use web_vox_native_bridge::tts::macos::MacOsSynthesizer;
    use web_vox_native_bridge::tts::traits::{SynthesisOptions, TtsSynthesizer};

    println!("=== web-vox macOS TTS integration test ===\n");

    let synth = MacOsSynthesizer::new();

    // 1. List voices
    println!("1. Listing voices...");
    match synth.list_voices() {
        Ok(voices) => {
            println!("   Found {} voices", voices.len());
            for v in voices.iter().take(5) {
                println!("   - {} ({}, {})", v.name, v.language, v.id);
            }
            if voices.len() > 5 {
                println!("   ... and {} more", voices.len() - 5);
            }
        }
        Err(e) => {
            eprintln!("   ERROR listing voices: {e}");
            std::process::exit(1);
        }
    }

    // 2. Synthesize text
    let text = "Hello world. This is a test of web vox audio capture.";
    println!("\n2. Synthesizing: \"{text}\"");

    let options = SynthesisOptions::default();
    match synth.synthesize(text, "test-1", &options) {
        Ok(output) => {
            let duration_s = output.total_duration_ms / 1000.0;
            println!("   Sample rate:  {} Hz", output.sample_rate);
            println!("   Channels:     {}", output.channels);
            println!("   Samples:      {}", output.samples.len());
            println!("   Duration:     {:.2}s ({:.0}ms)", duration_s, output.total_duration_ms);
            println!("   Word bounds:  {}", output.word_boundaries.len());

            for wb in &output.word_boundaries {
                println!(
                    "   [{:6.0}ms - {:6.0}ms] \"{}\"",
                    wb.start_time_ms, wb.end_time_ms, wb.word
                );
            }

            // Verify we got actual audio
            if output.samples.is_empty() {
                eprintln!("\n   FAIL: No audio samples captured!");
                std::process::exit(1);
            }

            // Check samples aren't all zero
            let non_zero = output.samples.iter().filter(|&&s| s.abs() > 0.001).count();
            let pct = (non_zero as f64 / output.samples.len() as f64) * 100.0;
            println!("   Non-zero:     {non_zero} ({pct:.1}%)");

            if non_zero == 0 {
                eprintln!("\n   FAIL: All samples are silent!");
                std::process::exit(1);
            }

            // Encode to protocol chunks
            let chunks = web_vox_native_bridge::audio::encoder::encode_chunks(
                "test-1",
                &output.samples,
                output.sample_rate,
                output.channels,
            );
            println!("   Chunks:       {} (base64-encoded)", chunks.len());

            println!("\n   PASS: Audio captured successfully!");
        }
        Err(e) => {
            eprintln!("   ERROR: {e}");
            eprintln!("\n   Note: AVSpeechSynthesizer.write() may need to run on");
            eprintln!("   the main thread with a running RunLoop. If this fails,");
            eprintln!("   try the RunLoop variant or dispatch to main thread.");
            std::process::exit(1);
        }
    }
}

#[cfg(not(target_os = "macos"))]
fn main() {
    eprintln!("This test only runs on macOS (requires AVSpeechSynthesizer).");
    std::process::exit(0);
}
