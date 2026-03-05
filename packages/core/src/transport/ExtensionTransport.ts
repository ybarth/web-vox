import type { NativeRequest, NativeResponse } from '../types.js';
import type { TransportAdapter, TransportType } from './TransportAdapter.js';

declare global {
  interface Window {
    __webVox?: {
      synthesize(request: NativeRequest): Promise<NativeResponse>;
      sendMessage(msg: NativeRequest): Promise<NativeResponse>;
      isAvailable: boolean;
    };
  }
}

export class ExtensionTransport implements TransportAdapter {
  readonly type: TransportType = 'extension';
  private connected = false;
  private messageHandlers: Array<(msg: NativeResponse) => void> = [];

  static isAvailable(): boolean {
    return typeof window !== 'undefined' && !!window.__webVox?.isAvailable;
  }

  async connect(): Promise<void> {
    if (!ExtensionTransport.isAvailable()) {
      throw new Error('web-vox browser extension not detected');
    }
    this.connected = true;
  }

  isConnected(): boolean {
    return this.connected;
  }

  async send(message: NativeRequest): Promise<NativeResponse> {
    if (!this.connected || !window.__webVox) {
      throw new Error('Extension transport not connected');
    }
    const response = await window.__webVox.sendMessage(message);
    this.messageHandlers.forEach(h => h(response));
    return response;
  }

  onMessage(handler: (msg: NativeResponse) => void): void {
    this.messageHandlers.push(handler);
  }

  disconnect(): void {
    this.connected = false;
    this.messageHandlers = [];
  }
}
