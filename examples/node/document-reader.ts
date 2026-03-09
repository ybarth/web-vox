/**
 * Document reader example — analyze document structure and synthesize with per-element voice control.
 *
 * Prerequisites:
 *   1. Start the backend: web-vox start
 *   2. Run this example: npx tsx examples/node/document-reader.ts
 */
import { NativeBridgeEngine, WebSocketTransport } from '@web-vox/core';
import type { DocumentProgress } from '@web-vox/core';

const SAMPLE_MARKDOWN = `# The Art of Reading

## Introduction

Text-to-speech has evolved beyond simple voice synthesis.
Modern systems understand document **structure** and adapt their reading style accordingly.

## Key Features

- **Forced alignment** provides precise word timestamps
- **Quality analysis** ensures natural-sounding output
- **Document awareness** adjusts voice for headings, lists, and paragraphs

> "The best interface is the one you don't notice." — Anonymous

## Conclusion

With web-vox-pro, your applications can read documents intelligently.
`;

async function main() {
  const transport = new WebSocketTransport('ws://localhost:21740');
  const engine = new NativeBridgeEngine(transport);
  await engine.initialize();
  console.log('Connected.\n');

  // 1. Analyze document structure
  console.log('Analyzing document structure...');
  const analysis = await engine.analyzeDocument(SAMPLE_MARKDOWN, 'markdown');

  console.log(`Format: ${analysis.format}`);
  console.log(`Elements: ${analysis.stats?.totalElements}`);
  console.log(`Words: ${analysis.stats?.totalWords}\n`);

  console.log('Document elements:');
  for (const el of analysis.elements) {
    const preview = el.text.substring(0, 60).replace(/\n/g, ' ');
    const voice = el.voice
      ? ` [rate=${el.voice.rate}, pitch=${el.voice.pitch}]`
      : '';
    console.log(`  ${el.type.padEnd(15)} "${preview}..."${voice}`);
  }

  // 2. Synthesize entire document with progress tracking
  console.log('\nSynthesizing document...');
  const result = await engine.synthesizeDocument(
    SAMPLE_MARKDOWN,
    {
      documentFormat: 'markdown',
      rate: 1.0,
      alignment: 'word',
    },
    (progress: DocumentProgress) => {
      const pct = (progress.progress * 100).toFixed(0);
      process.stdout.write(`\r  Progress: ${pct}% (${progress.elementsCompleted}/${progress.totalElements} elements)`);
    },
  );

  console.log('\n');
  console.log(`Total duration: ${(result.totalDurationMs / 1000).toFixed(2)}s`);
  console.log(`Elements synthesized: ${result.elements.length}`);
  console.log(`Combined samples: ${result.combinedSamples.length}`);

  // 3. Show per-element results
  console.log('\nPer-element breakdown:');
  for (const el of result.elements) {
    console.log(`  [${el.elementIndex}] ${el.elementType.padEnd(15)} ${(el.durationMs / 1000).toFixed(2)}s  "${el.textPreview.substring(0, 40)}..."`);
  }

  engine.dispose();
}

main().catch(console.error);
