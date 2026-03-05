import type { ProsodyHint, SemanticAnalysis } from '../types.js';
import type { SemanticAnalyzer } from './SemanticAnalyzer.js';

/**
 * Rules-based semantic analyzer (no LLM required).
 * Detects questions, exclamations, quoted speech, parentheticals, etc.
 */
export class RulesAnalyzer implements SemanticAnalyzer {
  async analyze(text: string): Promise<SemanticAnalysis> {
    const hints: ProsodyHint[] = [];

    // Questions
    for (const match of text.matchAll(/[^.!?]*\?/g)) {
      const start = match.index ?? 0;
      hints.push({ type: 'question', startChar: start, endChar: start + match[0].length });
    }

    // Exclamations
    for (const match of text.matchAll(/[^.!?]*!/g)) {
      const start = match.index ?? 0;
      hints.push({ type: 'exclamation', startChar: start, endChar: start + match[0].length });
    }

    // Parentheticals (whisper/aside)
    for (const match of text.matchAll(/\(([^)]+)\)/g)) {
      const start = match.index ?? 0;
      hints.push({ type: 'whisper', startChar: start, endChar: start + match[0].length });
    }

    // ALL CAPS words (emphasis)
    for (const match of text.matchAll(/\b[A-Z]{2,}\b/g)) {
      const start = match.index ?? 0;
      hints.push({ type: 'emphasis', startChar: start, endChar: start + match[0].length });
    }

    // Ellipsis (pause)
    for (const match of text.matchAll(/\.\.\./g)) {
      const start = match.index ?? 0;
      hints.push({ type: 'pause', startChar: start, endChar: start + match[0].length, value: 500 });
    }

    // Em-dash interruptions (pause)
    for (const match of text.matchAll(/\s*[\u2014\u2013]\s*/g)) {
      const start = match.index ?? 0;
      hints.push({ type: 'pause', startChar: start, endChar: start + match[0].length, value: 300 });
    }

    return { prosodyHints: hints, engineHints: {} };
  }
}
