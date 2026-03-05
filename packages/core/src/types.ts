// -- Core Result Types --

export interface WordTimestamp {
  word: string;
  charOffset: number;
  charLength: number;
  startTimeMs: number;
  endTimeMs: number;
}

export interface SentenceTimestamp {
  text: string;
  startTimeMs: number;
  endTimeMs: number;
  wordIndices: [number, number]; // [startIdx, endIdx] into wordTimestamps
}

export interface PhonemeMark {
  phoneme: string;
  startTimeMs: number;
  endTimeMs: number;
}

export interface ProsodyHint {
  type: 'emphasis' | 'question' | 'exclamation' | 'whisper' | 'pause' | 'rate-change';
  startChar: number;
  endChar: number;
  value?: number;
  label?: string;
}

export interface SynthesisMetadata {
  wordTimestamps: WordTimestamp[];
  sentenceTimestamps: SentenceTimestamp[];
  phonemeMarks?: PhonemeMark[];
  totalDurationMs: number;
  engine: string;
  voice: string;
  sampleRate: number;
  prosodyHints?: ProsodyHint[];
}

export interface SynthesisResult {
  audioBuffer: AudioBuffer;
  metadata: SynthesisMetadata;
  rawPcm?: Float32Array;
}

// -- Voice Types --

export interface VoiceInfo {
  id: string;
  name: string;
  language: string;
  gender?: 'male' | 'female' | 'neutral';
  engine: string;
  localeName?: string;
}

// -- Engine Types --

export interface EngineCapabilities {
  supportsSSML: boolean;
  supportsWordBoundaries: boolean;
  supportsPhonemeBoundaries: boolean;
  supportsStreaming: boolean;
  maxTextLength?: number;
  supportedLanguages?: string[];
  isLocal: boolean;
  maxRate: number;
  minRate: number;
}

export interface SynthesisOptions {
  voice?: string;
  rate?: number;   // 0.1 - 10.0, default 1.0
  pitch?: number;  // 0.0 - 2.0, default 1.0
  volume?: number; // 0.0 - 1.0, default 1.0
  engine?: string;
  ssml?: boolean;
  format?: 'audiobuffer' | 'arraybuffer' | 'blob';
}

export interface AudioChunk {
  samples: Float32Array;
  sampleRate: number;
  channels: number;
  timestamp?: number;
  wordBoundaries?: WordTimestamp[];
  isFinal: boolean;
}

export interface RawSynthesisResult {
  samples: Float32Array;
  sampleRate: number;
  channels: number;
  wordTimestamps: WordTimestamp[];
  totalDurationMs: number;
}

// -- Effect Types --

export interface EffectConfig {
  type: string;
  enabled: boolean;
  params: Record<string, number>;
}

// -- Transport / Native Protocol Types --

export interface NativeRequest {
  type: 'synthesize' | 'cancel' | 'list_voices';
  id?: string;
  text?: string;
  voice_id?: string;
  rate?: number;
  pitch?: number;
  volume?: number;
}

export interface NativeResponse {
  type: 'audio_chunk' | 'word_boundary' | 'synthesis_complete' | 'voice_list' | 'error';
  id?: string;
  [key: string]: unknown;
}

export interface NativeAudioChunk {
  id: string;
  data_base64: string;
  sequence: number;
  is_final: boolean;
  sample_rate: number;
  channels: number;
}

export interface NativeWordBoundary {
  id: string;
  word: string;
  char_offset: number;
  char_length: number;
  start_time_ms: number;
  end_time_ms: number;
}

export interface NativeVoiceDescriptor {
  id: string;
  name: string;
  language: string;
  gender?: string;
  engine: string;
}

// -- Semantic Types --

export interface SemanticAnalysis {
  prosodyHints: ProsodyHint[];
  ssmlOverride?: string;
  engineHints: Record<string, unknown>;
}
