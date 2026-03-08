# Changelog

All notable changes to WebVox Pro are documented in this file.

## [0.3.0] - 2026-03-08

### Added
- **Document Analyzer** — intelligent document structure detection
  - Auto-detection of plain text, markdown, and HTML formats
  - 20 document element types with voice scheme mappings
  - Position tracking (word offset, count, progress) per element
  - Optional AI enhancement via Ollama
- Document Mode toggle in the main demo UI
- Test workbench for the document analyzer at port 5200
- Stack status bar now shows 4 services (WS, alignment, quality, doc-analyzer)

### Changed
- `NativeBridgeEngine` now exposes `analyzeDocument()` method
- Protocol extended with `AnalyzeDocument` / `DocumentAnalysis` message types
- Server registry updated with document analyzer on port 21750

### Fixed
- Stack status count updated from `/3` to `/4`

## [0.2.0] - 2026-03-07

### Added
- **Quality Analysis** via model council
  - ASR verification (Whisper) — transcript comparison and WER
  - MOS prediction (UTMOS) — mean opinion score
  - Prosody analysis (librosa) — F0, energy, spectral brightness
  - Signal quality — SNR, clipping, silence ratio, artifacts
- Quality server on port 21748
- "Analyze Quality" checkbox in demo with metrics display

### Fixed
- Progress bar no longer freezes at 99% (asymptotic curve)

## [0.1.0] - 2026-03-06

### Added
- **Forced Alignment** via stable-ts (Whisper)
  - Word, syllable, and phoneme timestamp extraction
  - Confidence scores per word boundary
- Alignment server on port 21747
- Alignment granularity selector in demo UI
- `WordTimestamp` extended with confidence, phonemes, syllables

### Changed
- All 9 TTS engine files updated with new `WordBoundary` fields

## [0.0.1] - 2026-03-05

### Added
- Initial fork from web-vox
- `feat/meta-engine` branch created
- `device_config.json` and `server_registry.json` configuration files
- Project structure for 7 implementation phases

---

> **Format:** This changelog follows [Keep a Changelog](https://keepachangelog.com/) conventions.
>
> **Versioning:** This project uses [Semantic Versioning](https://semver.org/).
