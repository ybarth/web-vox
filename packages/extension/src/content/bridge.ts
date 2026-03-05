/**
 * Content script (MAIN world) — exposes window.__webVox API.
 * Phase 3 implementation stub.
 */

interface WebVoxBridge {
  isAvailable: boolean;
  synthesize(request: unknown): Promise<unknown>;
  sendMessage(msg: unknown): Promise<unknown>;
}

const bridge: WebVoxBridge = {
  isAvailable: true,
  async synthesize(request: unknown): Promise<unknown> {
    console.log('[web-vox] synthesize called:', request);
    return { type: 'error', code: 'NOT_IMPLEMENTED', message: 'Phase 3 pending' };
  },
  async sendMessage(msg: unknown): Promise<unknown> {
    console.log('[web-vox] sendMessage called:', msg);
    return { type: 'error', code: 'NOT_IMPLEMENTED', message: 'Phase 3 pending' };
  },
};

(window as unknown as { __webVox: WebVoxBridge }).__webVox = bridge;
console.log('[web-vox] Bridge injected into page');
