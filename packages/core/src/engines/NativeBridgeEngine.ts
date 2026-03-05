import type {
  EngineCapabilities,
  VoiceInfo,
  SynthesisOptions,
  RawSynthesisResult,
  NativeAudioChunk,
  NativeWordBoundary,
  NativeVoiceDescriptor,
  WordTimestamp,
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
    }));
    return this.voices;
  }

  async synthesize(text: string, options: SynthesisOptions): Promise<RawSynthesisResult> {
    if (!this.transport) throw new Error('Not initialized');

    const id = crypto.randomUUID();
    this.collectedChunks.set(id, []);
    this.collectedBoundaries.set(id, []);

    await this.transport.send({
      type: 'synthesize',
      id,
      text,
      voice_id: options.voice,
      rate: options.rate ?? 1.0,
      pitch: options.pitch ?? 1.0,
      volume: options.volume ?? 1.0,
    });

    const chunks = this.collectedChunks.get(id) ?? [];
    const boundaries = this.collectedBoundaries.get(id) ?? [];
    this.collectedChunks.delete(id);
    this.collectedBoundaries.delete(id);

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
    }));

    const totalDurationMs = chunks.length > 0
      ? (samples.length / channels / sampleRate) * 1000
      : 0;

    return { samples, sampleRate, channels, wordTimestamps, totalDurationMs };
  }

  cancel(): void {
    for (const id of this.collectedChunks.keys()) {
      this.transport?.send({ type: 'cancel', id }).catch(() => {});
    }
    this.collectedChunks.clear();
    this.collectedBoundaries.clear();
  }

  dispose(): void {
    this.transport?.disconnect();
    this.transport = null;
  }
}
