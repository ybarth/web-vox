import type { SynthesisOptions, ProsodyHint } from './types.js';

/** Extended SpeechSynthesisUtterance with web-vox features. */
export class WebVoxUtterance {
  text: string;
  voice?: string;
  rate: number;
  pitch: number;
  volume: number;
  engine?: string;
  prosodyHints?: ProsodyHint[];

  onstart?: () => void;
  onend?: () => void;
  onerror?: (error: Error) => void;
  onboundary?: (event: { charIndex: number; charLength: number; word: string; timeMs: number }) => void;

  constructor(text: string) {
    this.text = text;
    this.rate = 1.0;
    this.pitch = 1.0;
    this.volume = 1.0;
  }

  toSynthesisOptions(): SynthesisOptions {
    return {
      voice: this.voice,
      rate: this.rate,
      pitch: this.pitch,
      volume: this.volume,
      engine: this.engine,
    };
  }
}
