// -- Core Result Types --

export interface WordTimestamp {
  word: string;
  charOffset: number;
  charLength: number;
  startTimeMs: number;
  endTimeMs: number;
  confidence?: number;
  phonemes?: PhonemeTimestamp[];
  syllables?: SyllableTimestamp[];
}

export interface PhonemeTimestamp {
  phoneme: string;
  startTimeMs: number;
  endTimeMs: number;
}

export interface SyllableTimestamp {
  text: string;
  charOffset?: number;
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
  qualityScore?: QualityScore;
}

// -- Voice Types --

export interface VoiceInfo {
  id: string;
  name: string;
  language: string;
  gender?: 'male' | 'female' | 'neutral';
  engine: string;
  localeName?: string;
  quality?: string;
  description?: string;
  sampleRate?: number;
}

export interface SystemInfo {
  os: string;
  osVersion: string;
  arch: string;
  cpuCores: number;
  availableEngines: string[];
  hostname: string;
}

export interface VoiceValidation {
  voiceId: string;
  valid: boolean;
  error?: string;
  suggestion?: string;
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

export type AlignmentGranularity = 'none' | 'word' | 'word+syllable' | 'word+phoneme' | 'full';

export interface SynthesisOptions {
  voice?: string;
  rate?: number;   // 0.1 - 10.0, default 1.0
  pitch?: number;  // 0.0 - 2.0, default 1.0
  volume?: number; // 0.0 - 1.0, default 1.0
  engine?: string;
  ssml?: boolean;
  format?: 'audiobuffer' | 'arraybuffer' | 'blob';
  alignment?: AlignmentGranularity;
  analyzeQuality?: boolean;
  qualityAnalyzers?: QualityAnalyzerType[];
}

export type QualityAnalyzerType = 'asr' | 'mos' | 'prosody' | 'signal';

export interface QualityArtifact {
  type: string;
  severity: 'low' | 'medium' | 'high';
  detail: string;
}

export interface QualityScore {
  overallScore: number;
  overallRating: string;
  asrConfidence?: number;
  asrWer?: number;
  asrHypothesis?: string;
  mos?: number;
  mosRating?: string;
  snrDb?: number;
  clipRatio?: number;
  silenceRatio?: number;
  f0MeanHz?: number;
  f0RangeHz?: number;
  artifacts: QualityArtifact[];
  recommendations: string[];
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
  qualityScore?: QualityScore;
}

// -- Effect Types --

export interface EffectConfig {
  type: string;
  enabled: boolean;
  params: Record<string, number>;
}

// -- Transport / Native Protocol Types --

export interface PiperCatalogVoice {
  key: string;
  name: string;
  language: string;
  language_name: string;
  quality: string;
  num_speakers: number;
  size_bytes: number;
  installed: boolean;
}

export interface PiperDownloadResult {
  key: string;
  success: boolean;
  error?: string;
}

export interface VoiceSampleInfo {
  name: string;
  filename: string;
  size_bytes: number;
}

export interface VoiceSampleResult {
  name: string;
  success: boolean;
  error?: string;
}

export interface UsageLogEntry {
  timestamp: number;
  cpu_percent: number;
  memory_mb: number;
  online: boolean;
}

export interface ServerProcessStats {
  engine: string;
  name: string;
  port: number;
  online: boolean;
  pid?: number;
  cpu_percent: number;
  memory_mb: number;
  uptime_secs: number;
  cpu_history: number[];
  memory_history: number[];
  usage_log: UsageLogEntry[];
  managed: boolean;
}

export interface ServerManageResult {
  engine: string;
  action: string;
  success: boolean;
  error?: string;
}

// -- Document Analysis Types --

export interface DocumentAnalysisResult {
  id: string;
  success: boolean;
  format?: string;
  elements: DocumentElement[];
  stats?: DocumentStats;
  error?: string;
}

export interface DocumentElement {
  type: string;
  text: string;
  charOffset: number;
  charLength: number;
  level: number;
  voice?: DocumentVoiceMapping;
  position?: DocumentPosition;
}

export interface DocumentVoiceMapping {
  rate: number;
  pitch: number;
  volume: number;
  pauseBeforeMs: number;
  pauseAfterMs: number;
  voiceHint?: string;
}

export interface DocumentPosition {
  wordOffset: number;
  wordCount: number;
  totalWords: number;
  progress: number;
}

export interface DocumentStats {
  totalElements: number;
  elementCounts: Record<string, number>;
  totalChars: number;
  totalWords: number;
  analysisTimeMs: number;
  aiEnhanced: boolean;
}

export interface NativeDocumentElement {
  type: string;
  text: string;
  char_offset: number;
  char_length: number;
  level: number;
  voice?: {
    rate: number;
    pitch: number;
    volume: number;
    pause_before_ms: number;
    pause_after_ms: number;
    voice_hint?: string;
  };
  position?: {
    word_offset: number;
    word_count: number;
    total_words: number;
    progress: number;
  };
}

export interface NativeDocumentAnalysisResult {
  id: string;
  success: boolean;
  format?: string;
  elements: NativeDocumentElement[];
  stats?: {
    total_elements: number;
    element_counts: Record<string, number>;
    total_chars: number;
    total_words: number;
    analysis_time_ms: number;
    ai_enhanced: boolean;
  };
  error?: string;
}

// -- Phase 4: Progressive Document Synthesis Types --

export interface SynthesizeDocumentOptions extends SynthesisOptions {
  format?: string;
  useAi?: boolean;
  voiceScheme?: Record<string, unknown>;
}

export interface ElementStart {
  id: string;
  elementIndex: number;
  elementType: string;
  textPreview: string;
  charOffset: number;
  charLength: number;
  voice?: DocumentVoiceMapping;
}

export interface ElementComplete {
  id: string;
  elementIndex: number;
  durationMs: number;
  pauseAfterMs: number;
}

export interface DocumentProgress {
  id: string;
  elementsCompleted: number;
  totalElements: number;
  progress: number;
  phase: 'analyzing' | 'synthesizing' | 'complete';
}

export interface DocumentSynthesisComplete {
  id: string;
  totalElements: number;
  totalDurationMs: number;
}

export interface ElementSynthesisResult {
  elementIndex: number;
  elementType: string;
  textPreview: string;
  samples: Float32Array;
  sampleRate: number;
  channels: number;
  wordTimestamps: WordTimestamp[];
  durationMs: number;
  pauseAfterMs: number;
  charOffset: number;
  charLength: number;
}

export interface DocumentSynthesisResult {
  elements: ElementSynthesisResult[];
  totalDurationMs: number;
  combinedSamples: Float32Array;
  combinedWordTimestamps: WordTimestamp[];
  sampleRate: number;
  channels: number;
}

export interface NativeElementStart {
  id: string;
  element_index: number;
  element_type: string;
  text_preview: string;
  char_offset: number;
  char_length: number;
  voice?: {
    rate: number;
    pitch: number;
    volume: number;
    pause_before_ms: number;
    pause_after_ms: number;
    voice_hint?: string;
  };
}

export interface NativeElementComplete {
  id: string;
  element_index: number;
  duration_ms: number;
  pause_after_ms: number;
}

export interface NativeDocumentProgress {
  id: string;
  elements_completed: number;
  total_elements: number;
  progress: number;
  phase: string;
}

export interface NativeDocumentSynthesisComplete {
  id: string;
  total_elements: number;
  total_duration_ms: number;
}

export interface NativeRequest {
  type: 'synthesize' | 'cancel' | 'list_voices' | 'get_system_info' | 'validate_voice' | 'list_piper_catalog' | 'download_piper_voice' | 'list_voice_samples' | 'upload_voice_sample' | 'delete_voice_sample' | 'manage_server' | 'get_server_stats' | 'analyze_document' | 'synthesize_document';
  id?: string;
  text?: string;
  voice_id?: string;
  key?: string;
  name?: string;
  data_base64?: string;
  engine?: string;
  action?: string;
  rate?: number;
  pitch?: number;
  volume?: number;
  alignment?: AlignmentGranularity;
  analyze_quality?: boolean;
  quality_analyzers?: string[];
  format?: string;
  use_ai?: boolean;
  voice_scheme?: Record<string, unknown>;
}

export interface NativeResponse {
  type: 'audio_chunk' | 'word_boundary' | 'synthesis_complete' | 'voice_list' | 'error' | 'system_info' | 'voice_validation' | 'piper_catalog' | 'piper_download_complete' | 'voice_samples' | 'voice_sample_result' | 'server_manage_result' | 'server_stats' | 'quality_score' | 'document_analysis' | 'element_start' | 'element_complete' | 'document_progress' | 'document_synthesis_complete';
  id?: string;
  [key: string]: unknown;
}

export interface NativeQualityScore {
  id: string;
  overall_score: number;
  overall_rating: string;
  asr_confidence?: number;
  asr_wer?: number;
  asr_hypothesis?: string;
  mos?: number;
  mos_rating?: string;
  snr_db?: number;
  clip_ratio?: number;
  silence_ratio?: number;
  f0_mean_hz?: number;
  f0_range_hz?: number;
  artifacts: { type: string; severity: string; detail: string }[];
  recommendations: string[];
}

export interface NativeAudioChunk {
  id: string;
  data_base64: string;
  sequence: number;
  is_final: boolean;
  sample_rate: number;
  channels: number;
  element_index?: number;
}

export interface NativePhonemeBoundary {
  phoneme: string;
  start_time_ms: number;
  end_time_ms: number;
}

export interface NativeSyllableBoundary {
  text: string;
  char_offset?: number;
  start_time_ms: number;
  end_time_ms: number;
}

export interface NativeWordBoundary {
  id: string;
  word: string;
  char_offset: number;
  char_length: number;
  start_time_ms: number;
  end_time_ms: number;
  confidence?: number;
  phonemes?: NativePhonemeBoundary[];
  syllables?: NativeSyllableBoundary[];
  element_index?: number;
  document_char_offset?: number;
}

export interface NativeVoiceDescriptor {
  id: string;
  name: string;
  language: string;
  gender?: string;
  engine: string;
  quality?: string;
  description?: string;
  sample_rate?: number;
}

// -- Semantic Types --

export interface SemanticAnalysis {
  prosodyHints: ProsodyHint[];
  ssmlOverride?: string;
  engineHints: Record<string, unknown>;
}
