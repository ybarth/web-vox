import type { EffectConfig, RawSynthesisResult } from '../types.js';

export interface AudioEffect {
  readonly id: string;
  readonly type: string;

  /** Offline processing: transform the entire buffer + metadata */
  processBuffer(input: RawSynthesisResult, config: EffectConfig): RawSynthesisResult;

  /** Realtime processing: create/connect Web Audio nodes */
  connectRealtime?(
    source: AudioNode,
    destination: AudioNode,
    ctx: AudioContext,
    config: EffectConfig,
  ): AudioNode;
}

export class EffectsChain {
  private effects: AudioEffect[] = [];
  private configs: EffectConfig[] = [];

  addEffect(effect: AudioEffect, config: EffectConfig): void {
    this.effects.push(effect);
    this.configs.push(config);
  }

  removeEffect(type: string): void {
    const idx = this.effects.findIndex(e => e.type === type);
    if (idx >= 0) {
      this.effects.splice(idx, 1);
      this.configs.splice(idx, 1);
    }
  }

  setConfigs(configs: EffectConfig[]): void {
    this.configs = configs;
  }

  processOffline(input: RawSynthesisResult): RawSynthesisResult {
    let result = input;
    for (let i = 0; i < this.effects.length; i++) {
      const config = this.configs[i];
      if (!config?.enabled) continue;
      result = this.effects[i].processBuffer(result, config);
    }
    return result;
  }

  connectRealtime(source: AudioNode, destination: AudioNode, ctx: AudioContext): void {
    let current: AudioNode = source;
    for (let i = 0; i < this.effects.length; i++) {
      const config = this.configs[i];
      if (!config?.enabled || !this.effects[i].connectRealtime) continue;
      current = this.effects[i].connectRealtime!(current, destination, ctx, config);
    }
    current.connect(destination);
  }

  clear(): void {
    this.effects = [];
    this.configs = [];
  }
}
