import type {
  EngineCapabilities,
  VoiceInfo,
  SynthesisOptions,
  RawSynthesisResult,
  AudioChunk,
} from '../types.js';

export interface EngineAdapter {
  readonly id: string;
  readonly capabilities: EngineCapabilities;

  initialize(): Promise<void>;
  getVoices(): Promise<VoiceInfo[]>;
  synthesize(text: string, options: SynthesisOptions): Promise<RawSynthesisResult>;
  synthesizeStream?(text: string, options: SynthesisOptions): AsyncIterable<AudioChunk>;
  cancel(): void;
  dispose?(): void;
}
