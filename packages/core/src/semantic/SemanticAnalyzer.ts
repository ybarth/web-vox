import type { SemanticAnalysis } from '../types.js';

export interface SemanticAnalyzer {
  analyze(text: string): Promise<SemanticAnalysis>;
}
