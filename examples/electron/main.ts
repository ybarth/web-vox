/**
 * Electron integration example — embed web-vox-pro in a desktop app.
 *
 * This shows the pattern for integrating web-vox with Electron.
 * For a full Electron app, you'd also need package.json, preload.ts, and renderer code.
 *
 * Key integration points:
 *   1. Start the native backend as a child process via @web-vox/server
 *   2. Connect @web-vox/core via WebSocket from the renderer process
 *   3. Shut down gracefully on app quit
 */

// -- Main process (main.ts) --

import { ServerManager } from '@web-vox/server';
import { resolve } from 'node:path';

// In a real app, these would come from electron
declare const app: { on(event: string, cb: () => void): void; getAppPath(): string; quit(): void };
declare const BrowserWindow: new (opts: unknown) => { loadFile(path: string): void };

let manager: ServerManager | null = null;

async function createWindow() {
  // Start the TTS backend
  manager = ServerManager.fromProjectRoot(resolve(app.getAppPath(), '..'), {
    // Only start the servers you need
    servers: ['ws-server', 'kokoro', 'alignment'],
    onLog: (server, line) => console.log(`[${server}] ${line}`),
  });

  const results = await manager.startAll();
  const healthy = Array.from(results.values()).filter(s => s.healthy);
  console.log(`Started ${healthy.length}/${results.size} servers`);

  // Create browser window
  const win = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: { nodeIntegration: false, contextIsolation: true },
  });

  win.loadFile('renderer/index.html');
}

// Graceful shutdown
app.on('before-quit', async () => {
  if (manager) {
    console.log('Shutting down TTS servers...');
    await manager.stopAll();
  }
});

// -- Renderer process (renderer.ts) --
// In the renderer, use @web-vox/core directly:
//
//   import { WebVox, NativeBridgeEngine, WebSocketTransport } from '@web-vox/core';
//
//   const transport = new WebSocketTransport('ws://localhost:21740');
//   const engine = new NativeBridgeEngine(transport);
//   await engine.initialize();
//
//   const webVox = new WebVox();
//   webVox.registerEngine('native', engine);
//
//   const result = await webVox.synthesize('Hello from Electron!', {
//     alignment: 'word+syllable',
//   });
//
//   // Play the AudioBuffer, display word highlights, etc.
