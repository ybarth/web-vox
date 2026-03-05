import type {
  EngineCapabilities,
  VoiceInfo,
  SynthesisOptions,
  RawSynthesisResult,
  WordTimestamp,
} from '../types.js';
import type { EngineAdapter } from './EngineAdapter.js';

/**
 * Degraded fallback using the browser's built-in Web Speech API.
 * Returns empty audio samples with word boundary events from onboundary.
 * The browser plays audio through speakers directly — we can't capture it.
 */
export class WebSpeechEngine implements EngineAdapter {
  readonly id = 'web-speech';
  readonly capabilities: EngineCapabilities = {
    supportsSSML: false,
    supportsWordBoundaries: true,
    supportsPhonemeBoundaries: false,
    supportsStreaming: false,
    isLocal: true,
  };

  private synth: SpeechSynthesis;
  private currentUtterance: SpeechSynthesisUtterance | null = null;

  constructor() {
    if (typeof speechSynthesis === 'undefined') {
      throw new Error('Web Speech API not available');
    }
    this.synth = speechSynthesis;
  }

  async initialize(): Promise<void> {
    if (this.synth.getVoices().length === 0) {
      await new Promise<void>((resolve) => {
        this.synth.addEventListener('voiceschanged', () => resolve(), { once: true });
        setTimeout(resolve, 2000);
      });
    }
  }

  async getVoices(): Promise<VoiceInfo[]> {
    return this.synth.getVoices().map(v => ({
      id: v.voiceURI,
      name: v.name,
      language: v.lang,
      engine: 'web-speech',
      localeName: v.name,
    }));
  }

  async synthesize(text: string, options: SynthesisOptions): Promise<RawSynthesisResult> {
    return new Promise((resolve, reject) => {
      const utterance = new SpeechSynthesisUtterance(text);
      this.currentUtterance = utterance;

      if (options.voice) {
        const voice = this.synth.getVoices().find(v => v.voiceURI === options.voice);
        if (voice) utterance.voice = voice;
      }
      utterance.rate = options.rate ?? 1.0;
      utterance.pitch = options.pitch ?? 1.0;
      utterance.volume = options.volume ?? 1.0;

      const wordTimestamps: WordTimestamp[] = [];
      const startTime = performance.now();

      utterance.onboundary = (event) => {
        if (event.name === 'word') {
          const timeMs = performance.now() - startTime;
          const word = text.slice(event.charIndex, event.charIndex + (event.charLength ?? 1));
          wordTimestamps.push({
            word,
            charOffset: event.charIndex,
            charLength: event.charLength ?? word.length,
            startTimeMs: timeMs,
            endTimeMs: timeMs,
          });
          if (wordTimestamps.length >= 2) {
            wordTimestamps[wordTimestamps.length - 2].endTimeMs = timeMs;
          }
        }
      };

      utterance.onend = () => {
        const totalDurationMs = performance.now() - startTime;
        if (wordTimestamps.length > 0) {
          wordTimestamps[wordTimestamps.length - 1].endTimeMs = totalDurationMs;
        }
        resolve({
          samples: new Float32Array(0),
          sampleRate: 22050,
          channels: 1,
          wordTimestamps,
          totalDurationMs,
        });
      };

      utterance.onerror = (event) => {
        reject(new Error(`Web Speech synthesis error: ${event.error}`));
      };

      this.synth.speak(utterance);
    });
  }

  cancel(): void {
    this.synth.cancel();
    this.currentUtterance = null;
  }
}
