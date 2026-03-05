import type { NativeRequest, NativeResponse } from '../types.js';
import type { TransportAdapter, TransportType } from './TransportAdapter.js';

// Declare require for Node.js environments without depending on @types/node
declare const require: ((id: string) => unknown) | undefined;

export class NapiTransport implements TransportAdapter {
  readonly type: TransportType = 'napi';
  private nativeModule: unknown = null;
  private messageHandlers: Array<(msg: NativeResponse) => void> = [];

  static isAvailable(): boolean {
    return typeof require !== 'undefined';
  }

  async connect(): Promise<void> {
    try {
      const moduleName = 'web-vox-native-bridge';
      this.nativeModule = require!(moduleName);
    } catch {
      throw new Error(
        'web-vox-native-bridge N-API module not found. Install it with: npm install web-vox-native-bridge'
      );
    }
  }

  isConnected(): boolean {
    return this.nativeModule !== null;
  }

  async send(message: NativeRequest): Promise<NativeResponse> {
    if (!this.nativeModule) {
      throw new Error('N-API transport not connected');
    }
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const mod = this.nativeModule as any;
    const response = await mod.processMessage(JSON.stringify(message));
    const parsed: NativeResponse = JSON.parse(response);
    this.messageHandlers.forEach(h => h(parsed));
    return parsed;
  }

  onMessage(handler: (msg: NativeResponse) => void): void {
    this.messageHandlers.push(handler);
  }

  disconnect(): void {
    this.nativeModule = null;
    this.messageHandlers = [];
  }
}
