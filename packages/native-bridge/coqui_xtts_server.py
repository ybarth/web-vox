#!/usr/bin/env python3
"""
Coqui XTTS v2 voice cloning HTTP server for web-vox.

Loads the XTTS v2 model once on startup and serves voice cloning synthesis requests.
Voice samples are read from the shared voice-samples/ directory.

Usage:
    python3 coqui_xtts_server.py [--port 21745] [--device cpu|cuda|mps] [--lazy]

Endpoints:
    GET  /health      - Health check
    GET  /voices      - List available voice samples for cloning
    POST /synthesize  - Synthesize text using a cloned voice (raw f32 LE bytes)
"""

import argparse
import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

SAMPLE_RATE = 24000
MODEL_NAME = "tts_models/multilingual/multi-dataset/xtts_v2"

_tts = None
_device = None


def find_voice_samples_dir() -> Path:
    d = Path(__file__).resolve().parent
    while d != d.parent:
        candidate = d / "packages" / "native-bridge" / "voice-samples"
        if candidate.is_dir():
            return candidate
        d = d.parent
    fallback = Path(__file__).resolve().parent / "voice-samples"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def get_device(requested: str) -> str:
    import torch
    if requested == "cuda" and torch.cuda.is_available():
        return "cuda"
    if requested == "mps" and torch.backends.mps.is_available():
        return "mps"
    if requested in ("cuda", "mps"):
        print(f"[coqui-xtts] {requested} not available, falling back to cpu")
    return "cpu"


def load_model(device: str) -> None:
    global _tts, _device
    if _tts is not None:
        return

    _device = device
    print(f"[coqui-xtts] Loading XTTS v2 model on {device}...")
    print(f"[coqui-xtts] First run will download the model (~1.8 GB).")
    from TTS.api import TTS

    _tts = TTS(model_name=MODEL_NAME).to(device)
    print("[coqui-xtts] Model loaded successfully.")


def list_samples() -> list[dict]:
    samples_dir = find_voice_samples_dir()
    voices = []
    if samples_dir.is_dir():
        for f in sorted(samples_dir.iterdir()):
            if f.suffix.lower() in (".wav", ".flac", ".mp3", ".ogg"):
                voices.append({
                    "id": f.stem,
                    "name": f.stem,
                    "language": "en",
                    "gender": None,
                })
    return voices


def synthesize(text: str, sample_name: str, language: str = "en") -> tuple[bytes, int]:
    global _tts
    if _tts is None:
        raise RuntimeError("Model not loaded")

    samples_dir = find_voice_samples_dir()
    # Find the sample file
    sample_path = None
    for ext in (".wav", ".flac", ".mp3", ".ogg"):
        candidate = samples_dir / f"{sample_name}{ext}"
        if candidate.exists():
            sample_path = str(candidate)
            break

    if sample_path is None:
        raise ValueError(f"Voice sample '{sample_name}' not found in {samples_dir}")

    wav = _tts.tts(text=text, speaker_wav=sample_path, language=language)
    audio = np.array(wav, dtype=np.float32)
    sr = _tts.synthesizer.output_sample_rate if hasattr(_tts, 'synthesizer') and _tts.synthesizer else SAMPLE_RATE
    return audio.tobytes(), sr


class XttsHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[coqui-xtts] {fmt % args}")

    def _send_json(self, data, status: int = 200) -> None:
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, msg: str, status: int = 500) -> None:
        self._send_json({"error": msg}, status)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            self._send_json({
                "status": "ok",
                "model_loaded": _tts is not None,
                "model_name": MODEL_NAME,
                "device": _device,
                "sample_rate": SAMPLE_RATE,
            })
            return

        if path == "/voices":
            self._send_json(list_samples())
            return

        self._send_error("Not found", 404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/synthesize":
            try:
                body = json.loads(self._read_body())
                text = body.get("text", "")
                if not text.strip():
                    self._send_error("No text provided", 400)
                    return

                voice = body.get("voice", "default")
                language = body.get("language", "en")

                print(f"[coqui-xtts] Cloning voice={voice} lang={language}: \"{text[:60]}\"")
                pcm_bytes, sr = synthesize(text, voice, language)

                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("X-Sample-Rate", str(sr))
                self.send_header("X-Channels", "1")
                self.send_header("Content-Length", str(len(pcm_bytes)))
                self.end_headers()
                self.wfile.write(pcm_bytes)
            except Exception as e:
                print(f"[coqui-xtts] Synthesis error: {e}")
                import traceback; traceback.print_exc()
                self._send_error(str(e))
            return

        self._send_error("Not found", 404)


def main():
    parser = argparse.ArgumentParser(description="Coqui XTTS v2 voice cloning server for web-vox")
    parser.add_argument("--port", type=int, default=21745, help="Port to listen on")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "mps"],
                        help="Torch device")
    parser.add_argument("--lazy", action="store_true",
                        help="Defer model loading until first synthesis request")
    args = parser.parse_args()

    global _device
    _device = get_device(args.device)

    if not args.lazy:
        load_model(_device)

    server = HTTPServer(("127.0.0.1", args.port), XttsHandler)
    print(f"[coqui-xtts] Server listening on http://127.0.0.1:{args.port}")
    print("[coqui-xtts] Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[coqui-xtts] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
