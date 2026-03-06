#!/usr/bin/env python3
"""
Kokoro TTS HTTP server for web-vox.

Loads the Kokoro-82M model once on startup and serves synthesis requests.
Models are automatically downloaded from HuggingFace on first use (~330 MB).

Usage:
    python3 kokoro_server.py [--port 21742] [--device cpu|cuda] [--lazy]

Endpoints:
    GET  /health      - Health check
    POST /synthesize  - Synthesize text to PCM audio (raw f32 LE bytes)
"""

import argparse
import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ID = "hexgrad/Kokoro-82M"
SAMPLE_RATE = 24000

# Lazy-loaded state
_model = None
_us_pipeline = None   # lang_code='a'  — American English (af_*, am_*)
_gb_pipeline = None   # lang_code='b'  — British English  (bf_*, bm_*)
_device = None


def get_device(requested: str) -> str:
    """Resolve device, falling back to cpu if requested device is unavailable.
    Note: Kokoro supports only 'cpu' and 'cuda' — not 'mps'."""
    import torch
    if requested == "cuda" and torch.cuda.is_available():
        return "cuda"
    if requested in ("cuda", "mps"):
        print(f"[kokoro] {requested} not available (Kokoro supports cpu/cuda only), falling back to cpu")
    return "cpu"


def load_model(device: str) -> None:
    global _model, _us_pipeline, _gb_pipeline, _device
    if _model is not None:
        return

    print(f"[kokoro] Loading model on {device}...")
    print(f"[kokoro] First run will download ~330 MB from HuggingFace into the cache.")
    from kokoro import KModel, KPipeline

    _model = KModel(repo_id=REPO_ID).to(device).eval()
    # Share the single KModel across both language pipelines
    _us_pipeline = KPipeline(lang_code="a", repo_id=REPO_ID, model=_model)
    _gb_pipeline = KPipeline(lang_code="b", repo_id=REPO_ID, model=_model)
    _device = device
    print("[kokoro] Model loaded successfully.")


def _pipeline_for(voice_code: str):
    """Return the pipeline appropriate for the given Kokoro voice code."""
    load_model(_device)
    # bf_* / bm_* → British English; everything else → American English
    if voice_code.startswith("b"):
        return _gb_pipeline
    return _us_pipeline


def synthesize(text: str, voice: str) -> tuple[bytes, int]:
    """Synthesize *text* with *voice*, returning (raw_pcm_f32_le_bytes, sample_rate)."""
    pipeline = _pipeline_for(voice)
    chunks = []
    for result in pipeline(text, voice=voice, speed=1.0):
        if result.audio is not None:
            chunks.append(result.audio.numpy().astype(np.float32))
    if not chunks:
        raise ValueError("Kokoro produced no audio")
    audio = np.concatenate(chunks)
    return audio.tobytes(), SAMPLE_RATE


class KokoroHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # suppress default access-log spam
        print(f"[kokoro] {fmt % args}")

    def _send_json(self, data: dict, status: int = 200) -> None:
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
                "model_loaded": _model is not None,
                "device": _device,
                "sample_rate": SAMPLE_RATE,
            })
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

                voice = body.get("voice", "am_onyx")

                print(f"[kokoro] Synthesizing voice={voice}: \"{text[:60]}\"")
                pcm_bytes, sr = synthesize(text, voice)

                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("X-Sample-Rate", str(sr))
                self.send_header("X-Channels", "1")
                self.send_header("Content-Length", str(len(pcm_bytes)))
                self.end_headers()
                self.wfile.write(pcm_bytes)
            except Exception as e:
                print(f"[kokoro] Synthesis error: {e}")
                self._send_error(str(e))
            return

        self._send_error("Not found", 404)


def main():
    parser = argparse.ArgumentParser(description="Kokoro TTS server for web-vox")
    parser.add_argument("--port", type=int, default=21742, help="Port to listen on")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"],
                        help="Torch device (Kokoro does not support mps)")
    parser.add_argument("--lazy", action="store_true",
                        help="Defer model loading until first synthesis request")
    args = parser.parse_args()

    global _device
    _device = get_device(args.device)

    if not args.lazy:
        load_model(_device)

    server = HTTPServer(("127.0.0.1", args.port), KokoroHandler)
    print(f"[kokoro] Server listening on http://127.0.0.1:{args.port}")
    print("[kokoro] Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[kokoro] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
