import type { ProsodyHint, SynthesisOptions } from '../types.js';

/**
 * Maps semantic prosody hints to engine-specific synthesis parameters.
 */
export class ProsodyMapper {
  /** Generate SSML from text and prosody hints (for SSML-capable engines). */
  toSSML(text: string, hints: ProsodyHint[]): string {
    if (hints.length === 0) return text;

    const sorted = [...hints].sort((a, b) => b.startChar - a.startChar);
    let result = text;

    for (const hint of sorted) {
      const segment = result.slice(hint.startChar, hint.endChar);
      let wrapped: string;

      switch (hint.type) {
        case 'emphasis':
          wrapped = `<emphasis level="strong">${segment}</emphasis>`;
          break;
        case 'question':
          wrapped = `<prosody pitch="+10%">${segment}</prosody>`;
          break;
        case 'exclamation':
          wrapped = `<prosody rate="105%" pitch="+5%">${segment}</prosody>`;
          break;
        case 'whisper':
          wrapped = `<prosody volume="soft" rate="95%">${segment}</prosody>`;
          break;
        case 'pause':
          wrapped = `${segment}<break time="${hint.value ?? 500}ms"/>`;
          break;
        case 'rate-change':
          wrapped = `<prosody rate="${(hint.value ?? 1) * 100}%">${segment}</prosody>`;
          break;
        default:
          wrapped = segment;
      }

      result = result.slice(0, hint.startChar) + wrapped + result.slice(hint.endChar);
    }

    return `<speak>${result}</speak>`;
  }

  /** Adjust synthesis options based on prosody hints (for non-SSML engines). */
  adjustOptions(options: SynthesisOptions, hints: ProsodyHint[]): SynthesisOptions {
    const adjusted = { ...options };
    const hasQuestion = hints.some(h => h.type === 'question');
    const hasExclamation = hints.some(h => h.type === 'exclamation');

    if (hasQuestion) {
      adjusted.pitch = (adjusted.pitch ?? 1.0) * 1.1;
    }
    if (hasExclamation) {
      adjusted.rate = (adjusted.rate ?? 1.0) * 1.05;
      adjusted.pitch = (adjusted.pitch ?? 1.0) * 1.05;
    }

    return adjusted;
  }
}
