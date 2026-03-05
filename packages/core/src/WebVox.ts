import type {
  SynthesisOptions,
  SynthesisResult,
  VoiceInfo,
  EffectConfig,
} from './types.js';
import type { EngineAdapter } from './engines/EngineAdapter.js';
import type { TransportAdapter } from './transport/TransportAdapter.js';
import type { SemanticAnalyzer } from './semantic/SemanticAnalyzer.js';
import { EffectsChain } from './effects/EffectsChain.js';
import { WebVoxUtterance } from './WebVoxUtterance.js';
import { samplesToAudioBuffer } from './utils/audioConcat.js';

/** Main WebVox class — Web Speech API replacement with audio capture. */
export class WebVox {
  private engines = new Map<string, EngineAdapter>();
  private defaultEngineId: string | null = null;
  private effectsChain = new EffectsChain();
  private semanticAnalyzer: SemanticAnalyzer | null = null;
  private audioContext: AudioContext | null = null;

  constructor(audioContext?: AudioContext) {
    this.audioContext = audioContext ?? null;
  }

  // -- Engine Management --

  registerEngine(id: string, engine: EngineAdapter): void {
    this.engines.set(id, engine);
    if (!this.defaultEngineId) this.defaultEngineId = id;
  }

  setDefaultEngine(id: string): void {
    if (!this.engines.has(id)) throw new Error(`Engine "${id}" not registered`);
    this.defaultEngineId = id;
  }

  getEngine(id: string): EngineAdapter | undefined {
    return this.engines.get(id);
  }

  // -- Transport --

  setTransport(_transport: TransportAdapter): void {
    // Transport is set on the NativeBridgeEngine directly
  }

  // -- Effects --

  setEffects(effects: EffectConfig[]): void {
    this.effectsChain.setConfigs(effects);
  }

  getEffectsChain(): EffectsChain {
    return this.effectsChain;
  }

  // -- Semantic Analysis --

  enableSemanticAnalysis(analyzer: SemanticAnalyzer): void {
    this.semanticAnalyzer = analyzer;
  }

  disableSemanticAnalysis(): void {
    this.semanticAnalyzer = null;
  }

  // -- Web Speech API Compatible --

  speak(utterance: WebVoxUtterance): void {
    const options = utterance.toSynthesisOptions();
    utterance.onstart?.();

    this.synthesize(utterance.text, options)
      .then((result) => {
        for (const wt of result.metadata.wordTimestamps) {
          utterance.onboundary?.({
            charIndex: wt.charOffset,
            charLength: wt.charLength,
            word: wt.word,
            timeMs: wt.startTimeMs,
          });
        }
        utterance.onend?.();
      })
      .catch((err) => {
        utterance.onerror?.(err);
      });
  }

  cancel(): void {
    for (const engine of this.engines.values()) {
      engine.cancel();
    }
  }

  async getVoices(): Promise<VoiceInfo[]> {
    const allVoices: VoiceInfo[] = [];
    for (const engine of this.engines.values()) {
      const voices = await engine.getVoices();
      allVoices.push(...voices);
    }
    return allVoices;
  }

  // -- Extended API --

  async synthesize(text: string, options?: SynthesisOptions): Promise<SynthesisResult> {
    const engineId = options?.engine ?? this.defaultEngineId;
    if (!engineId) throw new Error('No engine registered');

    const engine = this.engines.get(engineId);
    if (!engine) throw new Error(`Engine "${engineId}" not found`);

    // Pre-process with semantic analysis
    let prosodyHints = undefined;
    const processedOptions = options ?? {};
    if (this.semanticAnalyzer) {
      const analysis = await this.semanticAnalyzer.analyze(text);
      prosodyHints = analysis.prosodyHints;
    }

    // Synthesize
    let raw = await engine.synthesize(text, processedOptions);

    // Post-process with effects chain
    raw = this.effectsChain.processOffline(raw);

    // Convert to AudioBuffer
    const ctx = this.getAudioContext();
    const audioBuffer = raw.samples.length > 0
      ? samplesToAudioBuffer(raw.samples, raw.sampleRate, raw.channels, ctx)
      : ctx.createBuffer(1, 1, raw.sampleRate);

    return {
      audioBuffer,
      metadata: {
        wordTimestamps: raw.wordTimestamps,
        sentenceTimestamps: [],
        totalDurationMs: raw.totalDurationMs,
        engine: engineId,
        voice: options?.voice ?? 'default',
        sampleRate: raw.sampleRate,
        prosodyHints,
      },
      rawPcm: raw.samples.length > 0 ? raw.samples : undefined,
    };
  }

  private getAudioContext(): AudioContext {
    if (!this.audioContext) {
      this.audioContext = new AudioContext();
    }
    return this.audioContext;
  }
}
