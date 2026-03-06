#!/usr/bin/env python3
"""
Forced alignment server for web-vox-pro.

Accepts synthesized audio + transcript text, returns accurate word-level
timestamps using Whisper (via stable-ts). Optionally provides syllable-level
and phoneme-level timestamps.

Port: 21747

Usage:
    python3 alignment_server.py [--device cpu|cuda|mps] [--model-size small|medium|large-v3-turbo]
"""

import argparse
import io
import json
import struct
import sys
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np

# ── Lazy-loaded models ────────────────────────────────────────────────

_whisper_model = None
_model_size = "small"
_device = "cpu"


def _load_config():
    """Load device/model config from device_config.json if present."""
    global _device, _model_size
    config_path = Path(__file__).parent / "device_config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            alignment = config.get("alignment", {})
            _device = alignment.get("device", _device)
            _model_size = alignment.get("model_size", _model_size)
        except Exception as e:
            print(f"  [alignment] Warning: failed to read device_config.json: {e}")


def _get_model():
    global _whisper_model
    if _whisper_model is None:
        import stable_whisper
        print(f"  [alignment] Loading Whisper model '{_model_size}' on {_device}...")
        t0 = time.time()
        _whisper_model = stable_whisper.load_model(_model_size, device=_device)
        print(f"  [alignment] Model loaded in {time.time() - t0:.1f}s")
    return _whisper_model


def _get_pyphen():
    import pyphen
    return pyphen.Pyphen(lang="en_US")


# ── Alignment logic ──────────────────────────────────────────────────

def align_audio(pcm_f32: np.ndarray, sample_rate: int, transcript: str,
                granularity: str = "word") -> dict:
    """
    Align audio to transcript using stable-ts (Whisper with stabilized timestamps).

    Returns dict with word-level timestamps and optional syllable/phoneme data.
    """
    model = _get_model()

    # stable-ts expects float32 numpy array at 16kHz.
    # Resample if needed.
    if sample_rate != 16000:
        try:
            import librosa
            pcm_f32 = librosa.resample(pcm_f32, orig_sr=sample_rate, target_sr=16000)
        except ImportError:
            # Simple linear resampling fallback
            ratio = 16000 / sample_rate
            indices = np.arange(0, len(pcm_f32), 1 / ratio).astype(int)
            indices = indices[indices < len(pcm_f32)]
            pcm_f32 = pcm_f32[indices]

    # Run forced alignment with known transcript
    result = model.align(pcm_f32, transcript, language="en")

    words = []
    for segment in result.segments:
        for word_obj in segment.words:
            word_text = word_obj.word.strip()
            if not word_text:
                continue

            # Find character offset in original transcript
            # stable-ts word text may have leading/trailing spaces stripped
            char_offset = _find_word_offset(transcript, word_text, words)

            word_entry = {
                "word": word_text,
                "char_offset": char_offset,
                "char_length": len(word_text),
                "start_time_ms": round(word_obj.start * 1000, 1),
                "end_time_ms": round(word_obj.end * 1000, 1),
                "confidence": round(getattr(word_obj, "probability", 0.9), 3),
            }

            # Add syllable data if requested
            if "syllable" in granularity or granularity == "full":
                word_entry["syllables"] = _syllabify_word(
                    word_text, word_entry["start_time_ms"], word_entry["end_time_ms"],
                    char_offset
                )

            words.append(word_entry)

    total_duration_ms = round(len(pcm_f32) / 16000 * 1000, 1)

    return {
        "words": words,
        "total_duration_ms": total_duration_ms,
    }


def _find_word_offset(transcript: str, word: str, existing_words: list) -> int:
    """Find the character offset of a word in the transcript, accounting for prior words."""
    # Start searching after the last found word
    search_start = 0
    if existing_words:
        last = existing_words[-1]
        search_start = last["char_offset"] + last["char_length"]

    idx = transcript.lower().find(word.lower(), search_start)
    if idx == -1:
        # Fallback: search from beginning
        idx = transcript.lower().find(word.lower())
    if idx == -1:
        # Last resort: use search_start
        idx = search_start

    return idx


def _syllabify_word(word: str, start_ms: float, end_ms: float,
                    word_char_offset: int) -> list:
    """Split a word into syllables and distribute time proportionally by character count."""
    try:
        dic = _get_pyphen()
        syllables = dic.inserted(word).split("-")
    except Exception:
        syllables = [word]

    if not syllables or len(syllables) == 0:
        syllables = [word]

    total_chars = sum(len(s) for s in syllables)
    if total_chars == 0:
        return [{"text": word, "start_time_ms": start_ms, "end_time_ms": end_ms}]

    duration = end_ms - start_ms
    result = []
    current_time = start_ms
    char_pos = 0

    for syl in syllables:
        proportion = len(syl) / total_chars
        syl_duration = duration * proportion
        result.append({
            "text": syl,
            "char_offset": word_char_offset + char_pos,
            "start_time_ms": round(current_time, 1),
            "end_time_ms": round(current_time + syl_duration, 1),
        })
        current_time += syl_duration
        char_pos += len(syl)

    return result


# ── HTTP Server ──────────────────────────────────────────────────────

class AlignmentHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  [alignment] {args[0]}")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            body = json.dumps({
                "status": "ok",
                "model_loaded": _whisper_model is not None,
                "model_size": _model_size,
                "device": _device,
            }).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/align":
            self._handle_align()
        else:
            self.send_error(404)

    def _handle_align(self):
        try:
            # Read headers
            sample_rate = int(self.headers.get("X-Sample-Rate", "22050"))
            channels = int(self.headers.get("X-Channels", "1"))
            transcript = self.headers.get("X-Transcript", "")
            request_id = self.headers.get("X-Request-Id", "unknown")
            granularity = self.headers.get("X-Granularity", "word")

            # Read PCM body (f32 LE)
            content_length = int(self.headers.get("Content-Length", 0))
            pcm_bytes = self.rfile.read(content_length)

            if not transcript:
                self._send_error(400, "X-Transcript header is required")
                return

            if len(pcm_bytes) < 4:
                self._send_error(400, "No audio data received")
                return

            # Convert f32 LE bytes to numpy array
            num_samples = len(pcm_bytes) // 4
            pcm_f32 = np.array(
                struct.unpack(f"<{num_samples}f", pcm_bytes[:num_samples * 4]),
                dtype=np.float32,
            )

            # If stereo, mix to mono
            if channels > 1:
                pcm_f32 = pcm_f32.reshape(-1, channels).mean(axis=1)

            print(f"  [alignment] Aligning {len(pcm_f32)} samples @ {sample_rate}Hz, "
                  f"transcript: \"{transcript[:60]}...\" granularity={granularity}")

            t0 = time.time()
            result = align_audio(pcm_f32, sample_rate, transcript, granularity)
            elapsed = time.time() - t0

            print(f"  [alignment] Aligned {len(result['words'])} words in {elapsed:.2f}s")

            body = json.dumps(result).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_error(500, str(e))

    def _send_error(self, code: int, message: str):
        body = json.dumps({"error": message}).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Forced alignment server for web-vox-pro")
    parser.add_argument("--port", type=int, default=21747)
    parser.add_argument("--device", choices=["cpu", "cuda", "mps"], default=None,
                        help="Override device from device_config.json")
    parser.add_argument("--model-size", default=None,
                        help="Whisper model size: small, medium, large-v3-turbo")
    parser.add_argument("--preload", action="store_true",
                        help="Load model immediately on startup")
    args = parser.parse_args()

    _load_config()

    global _device, _model_size
    if args.device:
        _device = args.device
    if args.model_size:
        _model_size = args.model_size

    print(f"  [alignment] Starting alignment server on port {args.port}")
    print(f"  [alignment] Device: {_device}, Model: {_model_size}")

    if args.preload:
        _get_model()

    server = HTTPServer(("127.0.0.1", args.port), AlignmentHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  [alignment] Shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
