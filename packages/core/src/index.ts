// Main API
export { WebVox } from './WebVox.js';
export { WebVoxUtterance } from './WebVoxUtterance.js';

// Types
export type {
  SynthesisResult,
  SynthesisMetadata,
  SynthesisOptions,
  WordTimestamp,
  PhonemeTimestamp,
  SyllableTimestamp,
  AlignmentGranularity,
  SentenceTimestamp,
  PhonemeMark,
  ProsodyHint,
  VoiceInfo,
  EngineCapabilities,
  EffectConfig,
  AudioChunk,
  RawSynthesisResult,
  SemanticAnalysis,
  NativeRequest,
  NativeResponse,
  SystemInfo,
  VoiceValidation,
  PiperCatalogVoice,
  PiperDownloadResult,
  VoiceSampleInfo,
  VoiceSampleResult,
  ServerProcessStats,
  ServerManageResult,
  QualityScore,
  QualityArtifact,
  QualityAnalyzerType,
  NativeQualityScore,
} from './types.js';

// Engine adapters
export type { EngineAdapter } from './engines/EngineAdapter.js';
export { NativeBridgeEngine } from './engines/NativeBridgeEngine.js';
export { WebSpeechEngine } from './engines/WebSpeechEngine.js';

// Transport adapters
export type { TransportAdapter, TransportType } from './transport/TransportAdapter.js';
export { ExtensionTransport } from './transport/ExtensionTransport.js';
export { WebSocketTransport } from './transport/WebSocketTransport.js';
export { NapiTransport } from './transport/NapiTransport.js';

// Effects
export { EffectsChain } from './effects/EffectsChain.js';
export type { AudioEffect } from './effects/EffectsChain.js';
export { GainEffect } from './effects/GainEffect.js';
export { StereoEffect } from './effects/StereoEffect.js';
export { EQEffect } from './effects/EQEffect.js';

// Semantic analysis
export type { SemanticAnalyzer } from './semantic/SemanticAnalyzer.js';
export { RulesAnalyzer } from './semantic/RulesAnalyzer.js';
export { ProsodyMapper } from './semantic/ProsodyMapper.js';

// Utilities
export { SSMLBuilder } from './utils/ssmlBuilder.js';
export { decodeBase64Pcm, encodeBase64Pcm, float32ToInt16, int16ToFloat32 } from './utils/pcmCodec.js';
export { concatFloat32Arrays, samplesToAudioBuffer } from './utils/audioConcat.js';
