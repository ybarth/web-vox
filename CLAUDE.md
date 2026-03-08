# Web-Vox Pro — Intelligent Reading Engine

## What This Project Is

Web-vox-pro is a meta-TTS platform forked from web-vox. It transforms multiple open-source TTS engines into an intelligent reading engine with:
- Accurate word/syllable/phoneme timestamps via forced alignment
- Audio quality analysis and auto-correction
- Document-aware multi-voice synthesis with audio effects
- OCR/vision support with spatial coordinate mapping
- SDK packaging for embedding in desktop/web apps

## Architecture

### Existing Infrastructure (from web-vox)
- **Rust WebSocket server** (`packages/native-bridge/src/bin/ws_server.rs`) — central hub on port 21740
- **TTS engines:** macOS AVSpeech, espeak-ng, Piper, Kokoro, Coqui, Coqui XTTS v2, Chatterbox, Qwen, Qwen-clone
- **Python HTTP servers** for neural engines (ports 21741-21746), each with `/health` and `/synthesize` endpoints
- **Rust HTTP clients** using `ureq` for each Python server
- **TypeScript core library** (`@web-vox/core`) with `NativeBridgeEngine` communicating via WebSocket
- **Demo frontend** (`packages/demo`) with voice selection, synthesis, playback, word highlighting
- **Sonic time-stretching** for speed adjustment (pitch-preserving)

### New Infrastructure (web-vox-pro additions)

| Service | Port | Purpose | Status |
|---------|------|---------|--------|
| `alignment_server.py` | 21747 | Forced alignment via Whisper/stable-ts | Phase 1 - BUILT |
| `quality_server.py` | 21748 | Audio quality analysis (model council) | Phase 2 - BUILT |
| `document_analyzer_server.py` | 21750 | LLM-based text structure detection | Phase 3 - PLANNED |
| `ocr_server.py` | 21751 | OCR with spatial bounding boxes | Phase 5 - PLANNED |

### Key Config Files
- `packages/native-bridge/device_config.json` — CPU/GPU assignment per server
- `packages/native-bridge/server_registry.json` — server URLs and deployment mode (local/cloud/hybrid)

## Implementation Phases

### Phase 0: Project Setup - COMPLETE
- Forked from web-vox into separate project folder
- `feat/meta-engine` branch created
- Config files and directories created

### Phase 1: Forced Alignment Layer - COMPLETE
- `alignment_server.py` — Python server using stable-ts (Whisper) + pyphen for syllables
- `alignment.rs` — Rust client (same ureq pattern as other engines)
- Protocol extended: `WordBoundary` now has optional `confidence`, `phonemes`, `syllables`
- `SynthesizeRequest` has `alignment` field: "none"|"word"|"word+syllable"|"word+phoneme"|"full"
- `ws_server.rs` calls alignment after synthesis, before sonic time-stretch, with graceful fallback
- All 9 engine files updated with new WordBoundary fields
- TypeScript types mirrored: `PhonemeTimestamp`, `SyllableTimestamp`, `AlignmentGranularity`, `NativePhonemeBoundary`, `NativeSyllableBoundary`; `WordTimestamp` and `NativeWordBoundary` extended; `SynthesisOptions` and `NativeRequest` have `alignment` field
- `NativeBridgeEngine.synthesize()` passes alignment and maps confidence/phonemes/syllables
- Demo UI has alignment granularity selector
- Python deps installed in `tts-venv` (stable-ts, pyphen, librosa)
- End-to-end tested: WS server + alignment server, synthesis with `word+syllable` alignment returns confidence scores and syllable data

### Phase 2: Quality Analysis & Correction Loop - COMPLETE
- `quality_server.py` — Python server (port 21748) with model council:
  - ASR verification via Whisper (stable-ts) — transcript comparison, word error rate
  - MOS prediction via UTMOS (torch Hub) — mean opinion score
  - Prosody analysis via librosa — F0 stats, energy, spectral brightness
  - Signal quality metrics — SNR, clipping detection, silence ratio, artifact flagging
- `quality.rs` — Rust HTTP client (same ureq pattern as alignment.rs)
- Protocol extended: `QualityScore`, `QualityArtifact` structs; `HostMessage::QualityScore` variant
- `SynthesizeRequest` has `analyze_quality` bool and `quality_analyzers` list
- TypeScript types mirrored: `QualityScore`, `QualityArtifact`, `QualityAnalyzerType`, `NativeQualityScore`
- `SynthesisOptions.analyzeQuality` + `qualityAnalyzers` fields
- `NativeBridgeEngine` collects quality_score messages, maps to `RawSynthesisResult.qualityScore`
- `SynthesisResult.qualityScore` exposed through `WebVox.synthesize()`
- Demo UI has "Analyze Quality" checkbox with quality score display (badge, metrics grid, recommendations)
- Quality server added to `SERVER_DEFS` in ws_server.rs
- Integrated into `handle_synthesize` — runs on raw audio before sonic time-stretch, with graceful fallback
- **Not yet implemented:** Targeted re-synthesis with crossfade splicing (planned for Phase 2b)

### Phase 3: Intelligent Document Reader (3a) - COMPLETE
- `document_analyzer_server.py` — Python server (port 21750) with:
  - Auto-detection of plain text, markdown, HTML formats
  - 20 document element types (heading, paragraph, dialogue, list_item, code_block, etc.)
  - Default voice scheme mapping (rate, pitch, volume, pause, voice hints) per element type
  - Position tracking (word offset, count, total, progress) per element
  - Optional AI enhancement via Ollama (llama3.1:8b)
  - Endpoints: `/health`, `/voice_scheme`, `/element_types`, `/analyze`, `/analyze_with_scheme`
- `document_analyzer.rs` — Rust HTTP client (same ureq pattern)
- Protocol extended: `AnalyzeDocumentRequest`, `DocumentAnalysisResult`, `DocumentElement`, `DocumentVoiceMapping`, `DocumentPosition`, `DocumentStats`
- `ClientMessage::AnalyzeDocument` + `HostMessage::DocumentAnalysis` variants
- `ws_server.rs` — `handle_analyze_document()` handler, server added to `SERVER_DEFS`
- TypeScript types mirrored: `DocumentAnalysisResult`, `DocumentElement`, `DocumentVoiceMapping`, `DocumentPosition`, `DocumentStats`, native variants
- `NativeBridgeEngine.analyzeDocument()` — full request/response mapping
- Demo UI:
  - "Document Mode" toggle on text input card
  - Format selector (auto/plain/markdown/HTML), Analyze Structure button, sample texts dropdown
  - Document Structure results section with 3 tabs: Elements, Preview (highlight), Voice Scheme
  - Stats bar (format, elements, words, chars, analysis time)
  - Stack status bar shows doc-analyzer dot (4/4 services)
- Test workbenches: `test-engines/doc-analyzer/index.html`, `test-engines/phase3/index.html` (standalone, removable)
- **Not yet implemented:** Phase 3b (EPUB/DOCX/PDF), Phase 3c (voice-scheme-driven multi-voice synthesis)

### Phase 4: Smart Loading & Progressive Chunking - PLANNED
### Phase 5: OCR/Vision & Spatial Coordinates - PLANNED
### Phase 6: SDK Packaging - PLANNED

## Development Patterns

- **Python servers:** All follow the same HTTP pattern with `/health` + task endpoints. Use `device_config.json` for CPU/GPU. Added to `SERVER_DEFS` in ws_server.rs.
- **Rust clients:** All use `ureq` with the same probe/request pattern. See `alignment.rs` as template.
- **Protocol changes:** Extend types in `crates/web-vox-protocol/src/lib.rs`, mirror in `packages/core/src/types.ts`.
- **WordBoundary constructors:** All require `confidence: None, phonemes: None, syllables: None` fields.

## Building

```bash
# Rust
/Users/yishai/.cargo/bin/cargo check --manifest-path "/Users/yishai/Documents/Warp Coding Projects/web-vox-pro/Cargo.toml" --workspace

# Note: cargo is not on default PATH, use absolute path or:
export PATH="$HOME/.cargo/bin:$PATH"
```
