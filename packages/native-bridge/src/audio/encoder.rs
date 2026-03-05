//! Encode captured PCM audio into base64-chunked messages.

use web_vox_protocol::{AudioChunk, encode_audio_base64};

/// Maximum raw PCM bytes per chunk before base64 encoding (~32KB).
const MAX_CHUNK_BYTES: usize = 32 * 1024;

/// Encode PCM float samples into a series of base64-encoded AudioChunk messages.
pub fn encode_chunks(
    request_id: &str,
    samples: &[f32],
    sample_rate: u32,
    channels: u16,
) -> Vec<AudioChunk> {
    let pcm_bytes: Vec<u8> = samples.iter().flat_map(|&s| s.to_le_bytes()).collect();

    let total_chunks = (pcm_bytes.len() + MAX_CHUNK_BYTES - 1) / MAX_CHUNK_BYTES;
    let mut chunks = Vec::with_capacity(total_chunks.max(1));

    if pcm_bytes.is_empty() {
        chunks.push(AudioChunk {
            id: request_id.to_string(),
            data_base64: String::new(),
            sequence: 0,
            is_final: true,
            sample_rate,
            channels,
        });
        return chunks;
    }

    for (i, chunk_data) in pcm_bytes.chunks(MAX_CHUNK_BYTES).enumerate() {
        let is_final = i == total_chunks - 1;
        chunks.push(AudioChunk {
            id: request_id.to_string(),
            data_base64: encode_audio_base64(chunk_data),
            sequence: i as u32,
            is_final,
            sample_rate,
            channels,
        });
    }

    chunks
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_samples_produce_single_final_chunk() {
        let chunks = encode_chunks("test", &[], 22050, 1);
        assert_eq!(chunks.len(), 1);
        assert!(chunks[0].is_final);
        assert!(chunks[0].data_base64.is_empty());
    }

    #[test]
    fn small_buffer_single_chunk() {
        let samples = vec![0.5f32; 100];
        let chunks = encode_chunks("test", &samples, 22050, 1);
        assert_eq!(chunks.len(), 1);
        assert!(chunks[0].is_final);
        assert!(!chunks[0].data_base64.is_empty());
    }

    #[test]
    fn large_buffer_multiple_chunks() {
        // 32KB / 4 bytes per f32 = 8192 samples per chunk
        let samples = vec![0.1f32; 20000]; // 80000 bytes -> 3 chunks
        let chunks = encode_chunks("test", &samples, 22050, 1);
        assert!(chunks.len() >= 2);
        assert!(!chunks[0].is_final);
        assert!(chunks.last().unwrap().is_final);

        for (i, chunk) in chunks.iter().enumerate() {
            assert_eq!(chunk.sequence, i as u32);
        }
    }
}
