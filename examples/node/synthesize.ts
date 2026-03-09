/**
 * Node.js synthesis example — connect to the web-vox server and synthesize text.
 *
 * Prerequisites:
 *   1. Start the backend: web-vox start
 *   2. Run this example: npx tsx examples/node/synthesize.ts
 */
import { writeFileSync } from 'node:fs';
import { WebVox, NativeBridgeEngine, WebSocketTransport } from '@web-vox/core';

async function main() {
  // 1. Create transport and engine
  const transport = new WebSocketTransport('ws://localhost:21740');
  const engine = new NativeBridgeEngine(transport);

  // 2. Initialize — connects to the native bridge server
  await engine.initialize();
  console.log('Connected to web-vox server.');

  // 3. Create the high-level API
  const webVox = new WebVox();
  webVox.registerEngine('native', engine);

  // 4. List available voices
  const voices = await webVox.getVoices();
  console.log(`Available voices: ${voices.length}`);
  for (const v of voices.slice(0, 5)) {
    console.log(`  - ${v.id} (${v.engine}, ${v.language})`);
  }

  // 5. Synthesize with word timestamps
  const text = 'Hello! This is web-vox-pro, an intelligent reading engine.';
  console.log(`\nSynthesizing: "${text}"`);

  const result = await webVox.synthesize(text, {
    rate: 1.0,
    alignment: 'word+syllable',
  });

  console.log(`Duration: ${(result.metadata.totalDurationMs / 1000).toFixed(2)}s`);
  console.log(`Words: ${result.metadata.wordTimestamps.length}`);
  console.log(`Sample rate: ${result.metadata.sampleRate} Hz`);

  // 6. Print word timestamps
  console.log('\nWord timestamps:');
  for (const wt of result.metadata.wordTimestamps) {
    const start = (wt.startTimeMs / 1000).toFixed(3);
    const end = (wt.endTimeMs / 1000).toFixed(3);
    const conf = wt.confidence ? ` (${(wt.confidence * 100).toFixed(0)}%)` : '';
    console.log(`  [${start}s - ${end}s] "${wt.word}"${conf}`);
  }

  // 7. Save raw PCM (optional — you'd normally play or encode to WAV)
  if (result.rawPcm) {
    const int16 = new Int16Array(result.rawPcm.length);
    for (let i = 0; i < result.rawPcm.length; i++) {
      const s = Math.max(-1, Math.min(1, result.rawPcm[i]));
      int16[i] = Math.round(s < 0 ? s * 0x8000 : s * 0x7FFF);
    }
    writeFileSync('output.pcm', Buffer.from(int16.buffer));
    console.log('\nSaved raw PCM to output.pcm');
  }

  // 8. Cleanup
  engine.dispose();
}

main().catch(console.error);
