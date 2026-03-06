# Web-Vox Pro — Intelligent Reading Engine

## What This Project Is

Web-vox-pro is a meta-TTS platform forked from web-vox. It transforms multiple open-source TTS engines into an intelligent reading engine with:
- Accurate word/syllable/phoneme timestamps via forced alignment
- Audio quality analysis and auto-correction
- Custom voice design (text-prompted, reference audio, multi-sample blending)
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
| `quality_server.py` | 21748 | Audio quality analysis (model council) | Phase 2 - PLANNED |
| `voice_designer_server.py` | 21749 | Voice creation via Parler-TTS + blending | Phase 3 - PLANNED |
| `document_analyzer_server.py` | 21750 | LLM-based text structure detection | Phase 4 - PLANNED |
| `ocr_server.py` | 21751 | OCR with spatial bounding boxes | Phase 6 - PLANNED |

### Key Config Files
- `packages/native-bridge/device_config.json` — CPU/GPU assignment per server
- `packages/native-bridge/server_registry.json` — server URLs and deployment mode (local/cloud/hybrid)

## Implementation Phases

### Phase 0: Project Setup - COMPLETE
- Forked from web-vox into separate project folder
- `feat/meta-engine` branch created
- Config files and directories created

### Phase 1: Forced Alignment Layer - IN PROGRESS
- `alignment_server.py` — Python server using stable-ts (Whisper) + pyphen for syllables
- `alignment.rs` — Rust client (same ureq pattern as other engines)
- Protocol extended: `WordBoundary` now has optional `confidence`, `phonemes`, `syllables`
- `SynthesizeRequest` has `alignment` field: "none"|"word"|"word+syllable"|"word+phoneme"|"full"
- `ws_server.rs` calls alignment after synthesis, before sonic time-stretch, with graceful fallback
- All 9 engine files updated with new WordBoundary fields
- **TODO:** TypeScript types update, Python dependency install, end-to-end testing

### Phase 2: Quality Analysis & Correction Loop - PLANNED
- Model council: Kimi Audio (Moonshot AI), UTMOS, Whisper, DNSMOS/NISQA, Crepe/librosa
- ASR verification, prosody scoring, artifact detection
- Targeted re-synthesis with crossfade splicing

### Phase 3: Voice Designer - PLANNED
- Text-prompted voice creation via Parler-TTS
- Multi-sample blending via speaker embedding interpolation
- Multi-engine preview and comparison

### Phase 4: Intelligent Document Reader - PLANNED
- Plain text + AI structure detection (4a), HTML/Markdown parsing (4b), EPUB/DOCX/PDF (4c)
- Voice Schemes mapping document structure to auditory behavior
- Extended SSML-like markup, stereo positioning, audio effects
- Full positional awareness (word/sentence/paragraph tracking)

### Phase 5: Smart Loading & Progressive Chunking - PLANNED
### Phase 6: OCR/Vision & Spatial Coordinates - PLANNED
### Phase 7: SDK Packaging - PLANNED

## Development Patterns

- **Python servers:** All follow the same HTTP pattern with `/health` + task endpoints. Use `device_config.json` for CPU/GPU. Added to `SERVER_DEFS` in ws_server.rs.
- **Rust clients:** All use `ureq` with the same probe/request pattern. See `alignment.rs` as template.
- **Protocol changes:** Extend types in `crates/web-vox-protocol/src/lib.rs`, mirror in `packages/core/src/types.ts`.
- **WordBoundary constructors:** All require `confidence: None, phonemes: None, syllables: None` fields.

## Full Plan

See `/Users/yishai/.claude/plans/shiny-foraging-wreath.md` for the complete architecture plan with all phases, file lists, and verification steps.

## Building

```bash
# Rust
/Users/yishai/.cargo/bin/cargo check --manifest-path "/Users/yishai/Documents/Warp Coding Projects/web-vox-pro/Cargo.toml" --workspace

# Note: cargo is not on default PATH, use absolute path or:
export PATH="$HOME/.cargo/bin:$PATH"
```
