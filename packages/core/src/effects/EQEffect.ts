import type { EffectConfig, RawSynthesisResult } from '../types.js';
import type { AudioEffect } from './EffectsChain.js';

export class EQEffect implements AudioEffect {
  readonly id = 'eq';
  readonly type = 'eq';

  processBuffer(input: RawSynthesisResult, _config: EffectConfig): RawSynthesisResult {
    // EQ is best applied in realtime via BiquadFilterNode
    return input;
  }

  connectRealtime(
    source: AudioNode,
    _destination: AudioNode,
    ctx: AudioContext,
    config: EffectConfig,
  ): AudioNode {
    const frequency = config.params.frequency ?? 1000;
    const gain = config.params.gain ?? 0;
    const q = config.params.q ?? 1;
    const filterType = (config.params.filterType ?? 0) as number;
    const types: BiquadFilterType[] = [
      'lowpass', 'highpass', 'bandpass', 'peaking', 'notch', 'lowshelf', 'highshelf',
    ];

    const filter = ctx.createBiquadFilter();
    filter.type = types[filterType] ?? 'peaking';
    filter.frequency.value = frequency;
    filter.gain.value = gain;
    filter.Q.value = q;
    source.connect(filter);
    return filter;
  }
}
