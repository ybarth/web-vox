/** Decode base64-encoded PCM Float32LE data back to Float32Array. */
export function decodeBase64Pcm(base64: string): Float32Array {
  if (!base64) return new Float32Array(0);

  const binaryString = atob(base64);
  const bytes = new Uint8Array(binaryString.length);
  for (let i = 0; i < binaryString.length; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }

  return new Float32Array(bytes.buffer);
}

/** Encode Float32Array as base64 PCM Float32LE. */
export function encodeBase64Pcm(samples: Float32Array): string {
  const bytes = new Uint8Array(samples.buffer, samples.byteOffset, samples.byteLength);
  let binary = '';
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

/** Convert Float32Array PCM to Int16Array PCM. */
export function float32ToInt16(samples: Float32Array): Int16Array {
  const output = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    output[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }
  return output;
}

/** Convert Int16Array PCM to Float32Array. */
export function int16ToFloat32(samples: Int16Array): Float32Array {
  const output = new Float32Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    output[i] = samples[i] / 32768;
  }
  return output;
}
