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

// -- Voice Designer Types --

export interface VoiceDesignResult {
  id: string;
  success: boolean;
  audioBase64?: string;
  sampleRate?: number;
  durationMs?: number;
  description?: string;
  error?: string;
}

export interface VoiceBlendResult {
  id: string;
  success: boolean;
  embedding?: number[];
  dimensions?: number;
  weightsNormalized?: number[];
  error?: string;
}

export interface VoiceProfileSummary {
  id: string;
  name: string;
  description?: string;
  sampleRate?: number;
  hasEmbedding: boolean;
  hasReferenceAudio: boolean;
  createdAt?: number;
}

export interface VoiceProfileResult {
  success: boolean;
  profileId?: string;
  error?: string;
}

export interface NativeVoiceDesignResult {
  id: string;
  success: boolean;
  audio_base64?: string;
  sample_rate?: number;
  duration_ms?: number;
  description?: string;
  error?: string;
}

export interface NativeVoiceBlendResult {
  id: string;
  success: boolean;
  embedding?: number[];
  dimensions?: number;
  weights_normalized?: number[];
  error?: string;
}

export interface NativeVoiceProfileSummary {
  id: string;
  name: string;
  description?: string;
  sample_rate?: number;
  has_embedding: boolean;
  has_reference_audio: boolean;
  created_at?: number;
}

export interface NativeVoiceProfileResult {
  success: boolean;
  profile_id?: string;
  error?: string;
}

export interface NativeRequest {
  type: 'synthesize' | 'cancel' | 'list_voices' | 'get_system_info' | 'validate_voice' | 'list_piper_catalog' | 'download_piper_voice' | 'list_voice_samples' | 'upload_voice_sample' | 'delete_voice_sample' | 'manage_server' | 'get_server_stats' | 'design_voice' | 'blend_voices' | 'list_voice_profiles' | 'save_voice_profile' | 'delete_voice_profile';
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
  // Voice designer fields
  description?: string;
  preview_text?: string;
  audio_samples_base64?: string[];
  sample_rates?: number[];
  weights?: number[];
  profile_id?: string;
  embedding?: number[];
  reference_audio_base64?: string;
  sample_rate?: number;
}

export interface NativeResponse {
  type: 'audio_chunk' | 'word_boundary' | 'synthesis_complete' | 'voice_list' | 'error' | 'system_info' | 'voice_validation' | 'piper_catalog' | 'piper_download_complete' | 'voice_samples' | 'voice_sample_result' | 'server_manage_result' | 'server_stats' | 'quality_score' | 'voice_design_result' | 'voice_blend_result' | 'voice_profiles' | 'voice_profile_result';
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
