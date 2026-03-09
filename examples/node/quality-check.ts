/**
 * Quality analysis example — synthesize and inspect audio quality metrics.
 *
 * Prerequisites:
 *   1. Start the backend: web-vox start
 *   2. Run this example: npx tsx examples/node/quality-check.ts
 */
import { NativeBridgeEngine, WebSocketTransport } from '@web-vox/core';

async function main() {
  const transport = new WebSocketTransport('ws://localhost:21740');
  const engine = new NativeBridgeEngine(transport);
  await engine.initialize();

  const text = 'The quick brown fox jumps over the lazy dog.';
  console.log(`Synthesizing with quality analysis: "${text}"\n`);

  const result = await engine.synthesize(text, {
    rate: 1.0,
    analyzeQuality: true,
    qualityAnalyzers: ['asr', 'mos', 'prosody', 'signal'],
  });

  console.log(`Duration: ${(result.totalDurationMs / 1000).toFixed(2)}s`);
  console.log(`Sample rate: ${result.sampleRate} Hz\n`);

  if (result.qualityScore) {
    const q = result.qualityScore;
    console.log('Quality Analysis Results:');
    console.log(`  Overall: ${q.overallScore.toFixed(2)}/10 (${q.overallRating})`);
    console.log(`  ASR confidence: ${(q.asrConfidence * 100).toFixed(1)}%`);
    console.log(`  ASR WER: ${(q.asrWer * 100).toFixed(1)}%`);
    console.log(`  MOS: ${q.mos.toFixed(2)} (${q.mosRating})`);
    console.log(`  SNR: ${q.snrDb.toFixed(1)} dB`);
    console.log(`  F0 mean: ${q.f0MeanHz.toFixed(0)} Hz, range: ${q.f0RangeHz.toFixed(0)} Hz`);
    console.log(`  Clip ratio: ${(q.clipRatio * 100).toFixed(2)}%`);
    console.log(`  Silence ratio: ${(q.silenceRatio * 100).toFixed(1)}%`);

    if (q.artifacts.length > 0) {
      console.log('\n  Artifacts:');
      for (const a of q.artifacts) {
        console.log(`    [${a.severity}] ${a.type}: ${a.detail}`);
      }
    }

    if (q.recommendations.length > 0) {
      console.log('\n  Recommendations:');
      for (const r of q.recommendations) {
        console.log(`    - ${r}`);
      }
    }
  } else {
    console.log('Quality analysis not available (quality server may not be running).');
  }

  engine.dispose();
}

main().catch(console.error);
