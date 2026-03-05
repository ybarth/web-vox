import type { EffectConfig, RawSynthesisResult } from '../types.js';
import type { AudioEffect } from './EffectsChain.js';

export class GainEffect implements AudioEffect {
  readonly id = 'gain';
  readonly type = 'gain';

  processBuffer(input: RawSynthesisResult, config: EffectConfig): RawSynthesisResult {
    const gain = config.params.gain ?? 1.0;
    if (gain === 1.0) return input;

    const output = new Float32Array(input.samples.length);
    for (let i = 0; i < input.samples.length; i++) {
      output[i] = Math.max(-1, Math.min(1, input.samples[i] * gain));
    }

    return { ...input, samples: output };
  }

  connectRealtime(
    source: AudioNode,
    _destination: AudioNode,
    ctx: AudioContext,
    config: EffectConfig,
  ): AudioNode {
    const gainNode = ctx.createGain();
    gainNode.gain.value = config.params.gain ?? 1.0;
    source.connect(gainNode);
    return gainNode;
  }
}
