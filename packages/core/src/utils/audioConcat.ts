/** Concatenate multiple Float32Arrays into one. */
export function concatFloat32Arrays(arrays: Float32Array[]): Float32Array {
  const totalLength = arrays.reduce((sum, arr) => sum + arr.length, 0);
  const result = new Float32Array(totalLength);
  let offset = 0;
  for (const arr of arrays) {
    result.set(arr, offset);
    offset += arr.length;
  }
  return result;
}

/** Create an AudioBuffer from raw PCM samples. */
export function samplesToAudioBuffer(
  samples: Float32Array,
  sampleRate: number,
  channels: number,
  ctx: BaseAudioContext,
): AudioBuffer {
  const framesPerChannel = Math.floor(samples.length / channels);
  const buffer = ctx.createBuffer(channels, framesPerChannel, sampleRate);

  if (channels === 1) {
    buffer.getChannelData(0).set(samples.subarray(0, framesPerChannel));
  } else {
    // De-interleave
    for (let ch = 0; ch < channels; ch++) {
      const channelData = buffer.getChannelData(ch);
      for (let i = 0; i < framesPerChannel; i++) {
        channelData[i] = samples[i * channels + ch];
      }
    }
  }

  return buffer;
}
