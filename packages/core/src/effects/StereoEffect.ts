import type { EffectConfig, RawSynthesisResult } from '../types.js';
import type { AudioEffect } from './EffectsChain.js';

export class StereoEffect implements AudioEffect {
  readonly id = 'stereo';
  readonly type = 'stereo';

  processBuffer(input: RawSynthesisResult, _config: EffectConfig): RawSynthesisResult {
    // Panning is best applied in realtime via StereoPannerNode
    return input;
  }

  connectRealtime(
    source: AudioNode,
    _destination: AudioNode,
    ctx: AudioContext,
    config: EffectConfig,
  ): AudioNode {
    const panner = new StereoPannerNode(ctx, { pan: config.params.pan ?? 0 });
    source.connect(panner);
    return panner;
  }
}
