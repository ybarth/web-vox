import type { NativeRequest, NativeResponse } from '../types.js';
import type { TransportAdapter, TransportType } from './TransportAdapter.js';

const DEFAULT_URL = 'ws://localhost:21740';

export class WebSocketTransport implements TransportAdapter {
  readonly type: TransportType = 'websocket';
  private ws: WebSocket | null = null;
  private url: string;
  private messageHandlers: Array<(msg: NativeResponse) => void> = [];
  private pendingRequests = new Map<string, {
    resolve: (value: NativeResponse) => void;
    reject: (reason: Error) => void;
  }>();

  constructor(url: string = DEFAULT_URL) {
    this.url = url;
  }

  static async probe(url: string = DEFAULT_URL): Promise<boolean> {
    return new Promise(resolve => {
      try {
        const ws = new WebSocket(url);
        const timer = setTimeout(() => { ws.close(); resolve(false); }, 1000);
        ws.onopen = () => { clearTimeout(timer); ws.close(); resolve(true); };
        ws.onerror = () => { clearTimeout(timer); resolve(false); };
      } catch {
        resolve(false);
      }
    });
  }

  async connect(): Promise<void> {
    return new Promise((resolve, reject) => {
      this.ws = new WebSocket(this.url);
      const timer = setTimeout(() => {
        this.ws?.close();
        reject(new Error(`WebSocket connection timeout to ${this.url}`));
      }, 5000);

      this.ws.onopen = () => {
        clearTimeout(timer);
        resolve();
      };

      this.ws.onerror = (e) => {
        clearTimeout(timer);
        reject(new Error(`WebSocket connection failed: ${e}`));
      };

      this.ws.onmessage = (event) => {
        try {
          const msg: NativeResponse = JSON.parse(event.data as string);
          const msgId = msg.id as string | undefined;

          if (msgId && this.pendingRequests.has(msgId)) {
            const pending = this.pendingRequests.get(msgId)!;
            if (msg.type === 'synthesis_complete' || msg.type === 'voice_list' || msg.type === 'error') {
              this.pendingRequests.delete(msgId);
              pending.resolve(msg);
            }
          } else if (!msgId && (msg.type === 'voice_list' || msg.type === 'error')) {
            // Responses without id (e.g. voice_list) — resolve the oldest pending request
            for (const [id, pending] of this.pendingRequests) {
              this.pendingRequests.delete(id);
              pending.resolve(msg);
              break;
            }
          }

          this.messageHandlers.forEach(h => h(msg));
        } catch {
          // Ignore non-JSON messages
        }
      };

      this.ws.onclose = () => {
        for (const [, pending] of this.pendingRequests) {
          pending.reject(new Error('WebSocket closed'));
        }
        this.pendingRequests.clear();
      };
    });
  }

  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  async send(message: NativeRequest): Promise<NativeResponse> {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      throw new Error('WebSocket not connected');
    }

    return new Promise((resolve, reject) => {
      const id = message.id ?? crypto.randomUUID();
      const msg = { ...message, id };
      this.pendingRequests.set(id, { resolve, reject });
      this.ws!.send(JSON.stringify(msg));
    });
  }

  onMessage(handler: (msg: NativeResponse) => void): void {
    this.messageHandlers.push(handler);
  }

  disconnect(): void {
    this.ws?.close();
    this.ws = null;
    this.messageHandlers = [];
    this.pendingRequests.clear();
  }
}
