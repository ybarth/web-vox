# Web-Vox Pro SDK Reference

## Installation

```bash
npm install @web-vox/core @web-vox/server
```

## Quick Start

```typescript
import { WebVox, NativeBridgeEngine, WebSocketTransport } from '@web-vox/core';

const transport = new WebSocketTransport('ws://localhost:21740');
const engine = new NativeBridgeEngine(transport);
await engine.initialize();

const webVox = new WebVox();
webVox.registerEngine('native', engine);
```

## Core API

### `WebVox.synthesize(text, options?)`

Synthesizes text to audio with word-level timestamps.

**Parameters:**
- `text` (string) — The text to synthesize
- `options.voice` (string) — Voice identifier
- `options.rate` (number) — Speech rate multiplier (0.1–6.0)
- `options.alignment` — Alignment granularity: `"none"`, `"word"`, `"word+syllable"`, `"word+phoneme"`, `"full"`
- `options.analyzeQuality` (boolean) — Enable quality analysis

**Returns:** `Promise<SynthesisResult>`

### `NativeBridgeEngine.analyzeDocument(text, format?, useAi?)`

Analyzes document structure for intelligent reading.

> **Note:** Requires the document analyzer server to be running on port 21750.

### `NativeBridgeEngine.extractText(imageBase64, options?)`

Extracts text from images using OCR with spatial bounding boxes.

## Architecture

| Component | Package | Port | Purpose |
|-----------|---------|------|---------|
| Core SDK | `@web-vox/core` | — | Client library |
| Server Manager | `@web-vox/server` | — | Process management |
| WS Server | `native-bridge` | 21740 | Central hub |
| Alignment | `alignment_server.py` | 21747 | Forced alignment |
| Quality | `quality_server.py` | 21748 | Audio analysis |
| Doc Analyzer | `document_analyzer_server.py` | 21750 | Document structure |
| OCR | `ocr_server.py` | 21751 | Text extraction |

## Error Handling

All SDK methods throw standard `Error` objects on failure. Wrap calls in try-catch:

```typescript
try {
  const result = await webVox.synthesize('Hello');
} catch (err) {
  console.error('Synthesis failed:', err.message);
}
```

## Changelog

### v0.1.0 (2026-03-09)
- Initial SDK release
- Core synthesis with 9 TTS engines
- Forced alignment (word, syllable, phoneme)
- Quality analysis model council
- Document analysis and progressive synthesis
- OCR with spatial bounding boxes
- CLI tool and server manager