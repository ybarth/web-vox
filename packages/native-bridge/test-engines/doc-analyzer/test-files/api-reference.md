# WebVox Pro API Reference

## Table of Contents

- [Overview](#overview)
- [Authentication](#authentication)
- [Endpoints](#endpoints)
- [Error Handling](#error-handling)

## Overview

The WebVox Pro API provides programmatic access to text-to-speech synthesis with document-aware intelligence. All requests use **JSON** over HTTP.

Base URL: `http://localhost:21740`

## Authentication

Currently, the API runs locally and does not require authentication. Future cloud deployments will use **Bearer tokens**.

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" http://api.webvox.dev/v1/synthesize
```

## Endpoints

### POST /synthesize

Synthesize text to speech with optional document analysis.

**Request Body:**

```json
{
  "text": "Hello, world!",
  "voice_id": "macos-samantha",
  "rate": 1.0,
  "pitch": 1.0,
  "alignment": "word+syllable",
  "analyze_quality": true
}
```

**Response:** Binary audio stream with word boundary metadata.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `text` | string | *required* | Text to synthesize |
| `voice_id` | string | *required* | Voice identifier |
| `rate` | float | `1.0` | Speech rate multiplier |
| `alignment` | string | `"word"` | Alignment granularity |

### POST /analyze

Analyze document structure without synthesis.

```json
{
  "text": "# My Document\n\nFirst paragraph...",
  "format": "auto",
  "use_ai": false
}
```

> **Note:** AI enhancement requires an Ollama instance running locally with the `llama3.1:8b` model.

### GET /health

Returns server status and available engines.

## Error Handling

All errors follow this format:

```json
{
  "success": false,
  "error": "Human-readable error message"
}
```

Common error codes:

- `400` — Invalid request parameters
- `404` — Voice or engine not found
- `503` — Backend engine unavailable

---

*Generated from WebVox Pro v0.3.0*
