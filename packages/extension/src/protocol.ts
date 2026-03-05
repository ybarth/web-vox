/**
 * Shared message types between extension components and native host.
 * Mirrors the Rust web-vox-protocol crate types.
 */

export interface SynthesizeRequest {
  type: 'synthesize';
  id: string;
  text: string;
  voice_id?: string;
  rate: number;
  pitch: number;
  volume: number;
}

export interface CancelRequest {
  type: 'cancel';
  id: string;
}

export interface ListVoicesRequest {
  type: 'list_voices';
}

export type ClientMessage = SynthesizeRequest | CancelRequest | ListVoicesRequest;

export interface AudioChunkMessage {
  type: 'audio_chunk';
  id: string;
  data_base64: string;
  sequence: number;
  is_final: boolean;
  sample_rate: number;
  channels: number;
}

export interface WordBoundaryMessage {
  type: 'word_boundary';
  id: string;
  word: string;
  char_offset: number;
  char_length: number;
  start_time_ms: number;
  end_time_ms: number;
}

export interface SynthesisCompleteMessage {
  type: 'synthesis_complete';
  id: string;
  total_duration_ms: number;
}

export interface VoiceListMessage {
  type: 'voice_list';
  voices: Array<{
    id: string;
    name: string;
    language: string;
    gender?: string;
    engine: string;
  }>;
}

export interface ErrorMessageType {
  type: 'error';
  id?: string;
  code: string;
  message: string;
}

export type HostMessage =
  | AudioChunkMessage
  | WordBoundaryMessage
  | SynthesisCompleteMessage
  | VoiceListMessage
  | ErrorMessageType;
