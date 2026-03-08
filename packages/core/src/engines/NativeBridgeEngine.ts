import type {
  EngineCapabilities,
  VoiceInfo,
  SynthesisOptions,
  SynthesizeDocumentOptions,
  RawSynthesisResult,
  NativeAudioChunk,
  NativeWordBoundary,
  NativeVoiceDescriptor,
  NativeQualityScore,
  NativeDocumentAnalysisResult,
  NativeElementStart,
  NativeElementComplete,
  NativeDocumentProgress,
  NativeDocumentSynthesisComplete,
  WordTimestamp,
  QualityScore,
  DocumentAnalysisResult,
  DocumentElement,
  DocumentProgress,
  ElementSynthesisResult,
  DocumentSynthesisResult,
  SystemInfo,
  VoiceValidation,
  PiperCatalogVoice,
  PiperDownloadResult,
  VoiceSampleInfo,
  VoiceSampleResult,
  ServerProcessStats,
  ServerManageResult,
} from '../types.js';
import type { EngineAdapter } from './EngineAdapter.js';
import type { TransportAdapter } from '../transport/TransportAdapter.js';
import { ExtensionTransport } from '../transport/ExtensionTransport.js';
import { WebSocketTransport } from '../transport/WebSocketTransport.js';
import { NapiTransport } from '../transport/NapiTransport.js';
import { decodeBase64Pcm } from '../utils/pcmCodec.js';

export class NativeBridgeEngine implements EngineAdapter {
  readonly id = 'native-bridge';
  readonly capabilities: EngineCapabilities = {
    supportsSSML: false,
    supportsWordBoundaries: true,
    supportsPhonemeBoundaries: false,
    supportsStreaming: true,
    isLocal: true,
    maxRate: 6.0,
    minRate: 0.1,
  };

  private transport: TransportAdapter | null = null;
  private voices: VoiceInfo[] = [];
  private collectedChunks = new Map<string, NativeAudioChunk[]>();
  private collectedBoundaries = new Map<string, NativeWordBoundary[]>();
  private collectedQuality = new Map<string, NativeQualityScore>();
  private collectedElementStarts = new Map<string, NativeElementStart[]>();
  private collectedElementCompletes = new Map<string, NativeElementComplete[]>();
  private progressCallbacks = new Map<string, (progress: DocumentProgress) => void>();

  constructor(private customTransport?: TransportAdapter) {}

  async initialize(): Promise<void> {
    if (this.customTransport) {
      this.transport = this.customTransport;
      await this.transport.connect();
      this.setupMessageHandler();
      return;
    }

    // Auto-detect best available transport
    if (typeof window !== 'undefined' && ExtensionTransport.isAvailable()) {
      this.transport = new ExtensionTransport();
      await this.transport.connect();
      this.setupMessageHandler();
      return;
    }

    if (typeof WebSocket !== 'undefined') {
      const available = await WebSocketTransport.probe();
      if (available) {
        this.transport = new WebSocketTransport();
        await this.transport.connect();
        this.setupMessageHandler();
        return;
      }
    }

    if (NapiTransport.isAvailable()) {
      this.transport = new NapiTransport();
      await this.transport.connect();
      this.setupMessageHandler();
      return;
    }

    throw new Error(
      'No web-vox transport available. Install the browser extension, start the WebSocket server, or use Node.js with the native module.'
    );
  }

  private setupMessageHandler(): void {
    this.transport!.onMessage((msg) => {
      const id = msg.id as string | undefined;
      if (!id) return;

      switch (msg.type) {
        case 'audio_chunk': {
          const chunk = msg as unknown as NativeAudioChunk;
          if (!this.collectedChunks.has(id)) this.collectedChunks.set(id, []);
          this.collectedChunks.get(id)!.push(chunk);
          break;
        }
        case 'word_boundary': {
          const boundary = msg as unknown as NativeWordBoundary;
          if (!this.collectedBoundaries.has(id)) this.collectedBoundaries.set(id, []);
          this.collectedBoundaries.get(id)!.push(boundary);
          break;
        }
        case 'quality_score': {
          const qs = msg as unknown as NativeQualityScore;
          this.collectedQuality.set(id, qs);
          break;
        }
        case 'element_start': {
          const es = msg as unknown as NativeElementStart;
          if (!this.collectedElementStarts.has(id)) this.collectedElementStarts.set(id, []);
          this.collectedElementStarts.get(id)!.push(es);
          break;
        }
        case 'element_complete': {
          const ec = msg as unknown as NativeElementComplete;
          if (!this.collectedElementCompletes.has(id)) this.collectedElementCompletes.set(id, []);
          this.collectedElementCompletes.get(id)!.push(ec);
          break;
        }
        case 'document_progress': {
          const dp = msg as unknown as NativeDocumentProgress;
          const cb = this.progressCallbacks.get(id);
          if (cb) {
            cb({
              id: dp.id,
              elementsCompleted: dp.elements_completed,
              totalElements: dp.total_elements,
              progress: dp.progress,
              phase: dp.phase as DocumentProgress['phase'],
            });
          }
          break;
        }
      }
    });
  }

  async getVoices(): Promise<VoiceInfo[]> {
    if (!this.transport) throw new Error('Not initialized');
    const response = await this.transport.send({ type: 'list_voices' });
    const voiceList = (response as unknown as { voices: NativeVoiceDescriptor[] }).voices ?? [];
    this.voices = voiceList.map(v => ({
      id: v.id,
      name: v.name,
      language: v.language,
      gender: v.gender as VoiceInfo['gender'],
      engine: v.engine,
      quality: v.quality,
      description: v.description,
      sampleRate: v.sample_rate,
    }));
    return this.voices;
  }

  async getSystemInfo(): Promise<SystemInfo> {
    if (!this.transport) throw new Error('Not initialized');
    const response = await this.transport.send({ type: 'get_system_info' });
    const info = response as unknown as {
      os: string; os_version: string; arch: string;
      cpu_cores: number; available_engines: string[]; hostname: string;
    };
    return {
      os: info.os,
      osVersion: info.os_version,
      arch: info.arch,
      cpuCores: info.cpu_cores,
      availableEngines: info.available_engines,
      hostname: info.hostname,
    };
  }

  async validateVoice(voiceId: string): Promise<VoiceValidation> {
    if (!this.transport) throw new Error('Not initialized');
    const response = await this.transport.send({ type: 'validate_voice', voice_id: voiceId });
    const v = response as unknown as {
      voice_id: string; valid: boolean; error?: string; suggestion?: string;
    };
    return {
      voiceId: v.voice_id,
      valid: v.valid,
      error: v.error,
      suggestion: v.suggestion,
    };
  }

  async listPiperCatalog(): Promise<PiperCatalogVoice[]> {
    if (!this.transport) throw new Error('Not initialized');
    const response = await this.transport.send({ type: 'list_piper_catalog' });
    if (response.type === 'error') {
      throw new Error((response as unknown as { message: string }).message ?? 'Failed to fetch catalog');
    }
    return (response as unknown as { voices: PiperCatalogVoice[] }).voices ?? [];
  }

  async downloadPiperVoice(key: string): Promise<PiperDownloadResult> {
    if (!this.transport) throw new Error('Not initialized');
    const response = await this.transport.send({ type: 'download_piper_voice', key });
    if (response.type === 'error') {
      throw new Error((response as unknown as { message: string }).message ?? 'Download failed');
    }
    return response as unknown as PiperDownloadResult;
  }

  async listVoiceSamples(): Promise<VoiceSampleInfo[]> {
    if (!this.transport) throw new Error('Not initialized');
    const response = await this.transport.send({ type: 'list_voice_samples' });
    if (response.type === 'error') {
      throw new Error((response as unknown as { message: string }).message ?? 'Failed to list samples');
    }
    return (response as unknown as { samples: VoiceSampleInfo[] }).samples ?? [];
  }

  async uploadVoiceSample(name: string, dataBase64: string): Promise<VoiceSampleResult> {
    if (!this.transport) throw new Error('Not initialized');
    const response = await this.transport.send({
      type: 'upload_voice_sample',
      name,
      data_base64: dataBase64,
    });
    if (response.type === 'error') {
      throw new Error((response as unknown as { message: string }).message ?? 'Upload failed');
    }
    return response as unknown as VoiceSampleResult;
  }

  async deleteVoiceSample(name: string): Promise<VoiceSampleResult> {
    if (!this.transport) throw new Error('Not initialized');
    const response = await this.transport.send({ type: 'delete_voice_sample', name });
    if (response.type === 'error') {
      throw new Error((response as unknown as { message: string }).message ?? 'Delete failed');
    }
    return response as unknown as VoiceSampleResult;
  }

  async manageServer(engine: string, action: 'start' | 'stop' | 'restart'): Promise<ServerManageResult> {
    if (!this.transport) throw new Error('Not initialized');
    const response = await this.transport.send({ type: 'manage_server', engine, action });
    if (response.type === 'error') {
      throw new Error((response as unknown as { message: string }).message ?? 'Server management failed');
    }
    return response as unknown as ServerManageResult;
  }

  async getServerStats(): Promise<ServerProcessStats[]> {
    if (!this.transport) throw new Error('Not initialized');
    const response = await this.transport.send({ type: 'get_server_stats' });
    if (response.type === 'error') {
      throw new Error((response as unknown as { message: string }).message ?? 'Failed to get server stats');
    }
    return (response as unknown as { servers: ServerProcessStats[] }).servers ?? [];
  }

  async synthesize(text: string, options: SynthesisOptions): Promise<RawSynthesisResult> {
    if (!this.transport) throw new Error('Not initialized');

    const id = crypto.randomUUID();
    this.collectedChunks.set(id, []);
    this.collectedBoundaries.set(id, []);

    const response = await this.transport.send({
      type: 'synthesize',
      id,
      text,
      voice_id: options.voice,
      rate: options.rate ?? 1.0,
      pitch: options.pitch ?? 1.0,
      volume: options.volume ?? 1.0,
      alignment: options.alignment,
      analyze_quality: options.analyzeQuality,
      quality_analyzers: options.qualityAnalyzers,
    });

    if (response.type === 'error') {
      this.collectedChunks.delete(id);
      this.collectedBoundaries.delete(id);
      const errMsg = (response as unknown as { message: string }).message ?? 'Synthesis failed';
      throw new Error(errMsg);
    }

    const chunks = this.collectedChunks.get(id) ?? [];
    const boundaries = this.collectedBoundaries.get(id) ?? [];
    const nativeQuality = this.collectedQuality.get(id);
    this.collectedChunks.delete(id);
    this.collectedBoundaries.delete(id);
    this.collectedQuality.delete(id);

    const sampleRate = chunks[0]?.sample_rate ?? 22050;
    const channels = chunks[0]?.channels ?? 1;
    const pcmArrays = chunks
      .sort((a, b) => a.sequence - b.sequence)
      .map(c => decodeBase64Pcm(c.data_base64));

    const totalLength = pcmArrays.reduce((sum, arr) => sum + arr.length, 0);
    const samples = new Float32Array(totalLength);
    let offset = 0;
    for (const arr of pcmArrays) {
      samples.set(arr, offset);
      offset += arr.length;
    }

    const wordTimestamps: WordTimestamp[] = boundaries.map(b => ({
      word: b.word,
      charOffset: b.char_offset,
      charLength: b.char_length,
      startTimeMs: b.start_time_ms,
      endTimeMs: b.end_time_ms,
      confidence: b.confidence,
      phonemes: b.phonemes?.map(p => ({
        phoneme: p.phoneme,
        startTimeMs: p.start_time_ms,
        endTimeMs: p.end_time_ms,
      })),
      syllables: b.syllables?.map(s => ({
        text: s.text,
        charOffset: s.char_offset,
        startTimeMs: s.start_time_ms,
        endTimeMs: s.end_time_ms,
      })),
    }));

    const totalDurationMs = chunks.length > 0
      ? (samples.length / channels / sampleRate) * 1000
      : 0;

    let qualityScore: QualityScore | undefined;
    if (nativeQuality) {
      qualityScore = {
        overallScore: nativeQuality.overall_score,
        overallRating: nativeQuality.overall_rating,
        asrConfidence: nativeQuality.asr_confidence,
        asrWer: nativeQuality.asr_wer,
        asrHypothesis: nativeQuality.asr_hypothesis,
        mos: nativeQuality.mos,
        mosRating: nativeQuality.mos_rating,
        snrDb: nativeQuality.snr_db,
        clipRatio: nativeQuality.clip_ratio,
        silenceRatio: nativeQuality.silence_ratio,
        f0MeanHz: nativeQuality.f0_mean_hz,
        f0RangeHz: nativeQuality.f0_range_hz,
        artifacts: nativeQuality.artifacts.map(a => ({
          type: a.type,
          severity: a.severity as 'low' | 'medium' | 'high',
          detail: a.detail,
        })),
        recommendations: nativeQuality.recommendations,
      };
    }

    return { samples, sampleRate, channels, wordTimestamps, totalDurationMs, qualityScore };
  }

  async analyzeDocument(
    text: string,
    format?: string,
    useAi?: boolean,
  ): Promise<DocumentAnalysisResult> {
    if (!this.transport) throw new Error('Not initialized');
    const id = crypto.randomUUID();
    const response = await this.transport.send({
      type: 'analyze_document',
      id,
      text,
      format: format ?? 'auto',
      use_ai: useAi ?? false,
    });
    if (response.type === 'error') {
      throw new Error((response as unknown as { message: string }).message ?? 'Document analysis failed');
    }
    const r = response as unknown as NativeDocumentAnalysisResult;
    const elements: DocumentElement[] = (r.elements ?? []).map(e => ({
      type: e.type,
      text: e.text,
      charOffset: e.char_offset,
      charLength: e.char_length,
      level: e.level,
      voice: e.voice ? {
        rate: e.voice.rate,
        pitch: e.voice.pitch,
        volume: e.voice.volume,
        pauseBeforeMs: e.voice.pause_before_ms,
        pauseAfterMs: e.voice.pause_after_ms,
        voiceHint: e.voice.voice_hint,
      } : undefined,
      position: e.position ? {
        wordOffset: e.position.word_offset,
        wordCount: e.position.word_count,
        totalWords: e.position.total_words,
        progress: e.position.progress,
      } : undefined,
    }));
    return {
      id: r.id,
      success: r.success,
      format: r.format,
      elements,
      stats: r.stats ? {
        totalElements: r.stats.total_elements,
        elementCounts: r.stats.element_counts,
        totalChars: r.stats.total_chars,
        totalWords: r.stats.total_words,
        analysisTimeMs: r.stats.analysis_time_ms,
        aiEnhanced: r.stats.ai_enhanced,
      } : undefined,
      error: r.error,
    };
  }

  async synthesizeDocument(
    text: string,
    options: SynthesizeDocumentOptions,
    onProgress?: (progress: DocumentProgress) => void,
  ): Promise<DocumentSynthesisResult> {
    if (!this.transport) throw new Error('Not initialized');

    const id = crypto.randomUUID();
    this.collectedChunks.set(id, []);
    this.collectedBoundaries.set(id, []);
    this.collectedElementStarts.set(id, []);
    this.collectedElementCompletes.set(id, []);
    if (onProgress) this.progressCallbacks.set(id, onProgress);

    const response = await this.transport.send({
      type: 'synthesize_document',
      id,
      text,
      voice_id: options.voice,
      rate: options.rate ?? 1.0,
      pitch: options.pitch ?? 1.0,
      volume: options.volume ?? 1.0,
      alignment: options.alignment,
      format: options.format ?? 'auto',
      use_ai: options.useAi ?? false,
      voice_scheme: options.voiceScheme,
    });

    if (response.type === 'error') {
      this.cleanupDocSynth(id);
      const errMsg = (response as unknown as { message: string }).message ?? 'Document synthesis failed';
      throw new Error(errMsg);
    }

    const chunks = this.collectedChunks.get(id) ?? [];
    const boundaries = this.collectedBoundaries.get(id) ?? [];
    const elementStarts = this.collectedElementStarts.get(id) ?? [];
    const elementCompletes = this.collectedElementCompletes.get(id) ?? [];
    const completeMsg = response as unknown as NativeDocumentSynthesisComplete;
    this.cleanupDocSynth(id);

    const sampleRate = chunks[0]?.sample_rate ?? 22050;
    const channels = chunks[0]?.channels ?? 1;

    // Sort all chunks by sequence and decode
    const sortedChunks = chunks.sort((a, b) => a.sequence - b.sequence);
    const pcmArrays = sortedChunks.map(c => decodeBase64Pcm(c.data_base64));
    const totalLength = pcmArrays.reduce((sum, arr) => sum + arr.length, 0);
    const combinedSamples = new Float32Array(totalLength);
    let offset = 0;
    for (const arr of pcmArrays) {
      combinedSamples.set(arr, offset);
      offset += arr.length;
    }

    // Map all word boundaries
    const combinedWordTimestamps: WordTimestamp[] = boundaries.map(b => ({
      word: b.word,
      charOffset: b.document_char_offset ?? b.char_offset,
      charLength: b.char_length,
      startTimeMs: b.start_time_ms,
      endTimeMs: b.end_time_ms,
      confidence: b.confidence,
      phonemes: b.phonemes?.map(p => ({
        phoneme: p.phoneme,
        startTimeMs: p.start_time_ms,
        endTimeMs: p.end_time_ms,
      })),
      syllables: b.syllables?.map(s => ({
        text: s.text,
        charOffset: s.char_offset,
        startTimeMs: s.start_time_ms,
        endTimeMs: s.end_time_ms,
      })),
    }));

    // Group per-element results
    const elementsMap = new Map<number, {
      chunks: NativeAudioChunk[];
      boundaries: NativeWordBoundary[];
      start?: NativeElementStart;
      complete?: NativeElementComplete;
    }>();

    for (const c of sortedChunks) {
      if (c.element_index == null) continue;
      if (!elementsMap.has(c.element_index)) elementsMap.set(c.element_index, { chunks: [], boundaries: [] });
      elementsMap.get(c.element_index)!.chunks.push(c);
    }
    for (const b of boundaries) {
      if (b.element_index == null) continue;
      if (!elementsMap.has(b.element_index)) elementsMap.set(b.element_index, { chunks: [], boundaries: [] });
      elementsMap.get(b.element_index)!.boundaries.push(b);
    }
    for (const es of elementStarts) {
      if (!elementsMap.has(es.element_index)) elementsMap.set(es.element_index, { chunks: [], boundaries: [] });
      elementsMap.get(es.element_index)!.start = es;
    }
    for (const ec of elementCompletes) {
      if (!elementsMap.has(ec.element_index)) elementsMap.set(ec.element_index, { chunks: [], boundaries: [] });
      elementsMap.get(ec.element_index)!.complete = ec;
    }

    const elements: ElementSynthesisResult[] = [];
    for (const [elemIdx, data] of Array.from(elementsMap.entries()).sort((a, b) => a[0] - b[0])) {
      const elemPcm = data.chunks.map(c => decodeBase64Pcm(c.data_base64));
      const elemLen = elemPcm.reduce((s, a) => s + a.length, 0);
      const elemSamples = new Float32Array(elemLen);
      let off = 0;
      for (const arr of elemPcm) { elemSamples.set(arr, off); off += arr.length; }

      elements.push({
        elementIndex: elemIdx,
        elementType: data.start?.element_type ?? 'paragraph',
        textPreview: data.start?.text_preview ?? '',
        samples: elemSamples,
        sampleRate,
        channels,
        wordTimestamps: data.boundaries.map(b => ({
          word: b.word,
          charOffset: b.document_char_offset ?? b.char_offset,
          charLength: b.char_length,
          startTimeMs: b.start_time_ms,
          endTimeMs: b.end_time_ms,
          confidence: b.confidence,
        })),
        durationMs: data.complete?.duration_ms ?? 0,
        pauseAfterMs: data.complete?.pause_after_ms ?? 0,
        charOffset: data.start?.char_offset ?? 0,
        charLength: data.start?.char_length ?? 0,
      });
    }

    return {
      elements,
      totalDurationMs: completeMsg.total_duration_ms,
      combinedSamples,
      combinedWordTimestamps,
      sampleRate,
      channels,
    };
  }

  private cleanupDocSynth(id: string): void {
    this.collectedChunks.delete(id);
    this.collectedBoundaries.delete(id);
    this.collectedQuality.delete(id);
    this.collectedElementStarts.delete(id);
    this.collectedElementCompletes.delete(id);
    this.progressCallbacks.delete(id);
  }

  cancel(): void {
    for (const id of this.collectedChunks.keys()) {
      this.transport?.send({ type: 'cancel', id }).catch(() => {});
    }
    this.collectedChunks.clear();
    this.collectedBoundaries.clear();
    this.collectedQuality.clear();
  }

  dispose(): void {
    this.transport?.disconnect();
    this.transport = null;
  }
}
