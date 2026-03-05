import type { NativeRequest, NativeResponse } from '../types.js';

export type TransportType = 'extension' | 'websocket' | 'napi';

export interface TransportAdapter {
  readonly type: TransportType;
  connect(): Promise<void>;
  isConnected(): boolean;
  send(message: NativeRequest): Promise<NativeResponse>;
  onMessage(handler: (msg: NativeResponse) => void): void;
  disconnect(): void;
}
