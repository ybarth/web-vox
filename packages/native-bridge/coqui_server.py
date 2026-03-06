#!/usr/bin/env python3
"""
Coqui TTS HTTP server for web-vox.

Loads a Coqui TTS model once on startup and serves synthesis requests.
Models are automatically downloaded on first use.

Usage:
    python3 coqui_server.py [--port 21743] [--device cpu|cuda] [--model MODEL_NAME] [--lazy]

Endpoints:
    GET  /health      - Health check
    GET  /voices      - List available voices/models
    POST /synthesize  - Synthesize text to PCM audio (raw f32 LE bytes)
"""

import argparse
import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import numpy as np

SAMPLE_RATE = 22050

# Lazy-loaded state
_tts = None
_model_name = None
_device = None


def get_device(requested: str) -> str:
    """Resolve device, falling back to cpu if requested device is unavailable."""
    import torch
    if requested == "cuda" and torch.cuda.is_available():
        return "cuda"
    if requested == "mps" and torch.backends.mps.is_available():
        return "mps"
    if requested in ("cuda", "mps"):
        print(f"[coqui] {requested} not available, falling back to cpu")
    return "cpu"


def load_model(model_name: str, device: str) -> None:
    global _tts, _model_name, _device
    if _tts is not None:
        return

    print(f"[coqui] Loading model '{model_name}' on {device}...")
    print(f"[coqui] First run will download the model into the cache.")
    from TTS.api import TTS

    _tts = TTS(model_name=model_name).to(device)
    _model_name = model_name
    _device = device
    print("[coqui] Model loaded successfully.")


def synthesize(text: str, voice: str) -> tuple[bytes, int]:
    """Synthesize text, returning (raw_pcm_f32_le_bytes, sample_rate)."""
    global _tts
    if _tts is None:
        raise RuntimeError("Model not loaded")

    # For multi-speaker models, voice is the speaker name
    # For single-speaker models, voice is ignored
    kwargs = {"text": text}
    if _tts.speakers and voice != "default":
        kwargs["speaker"] = voice

    wav = _tts.tts(**kwargs)
    audio = np.array(wav, dtype=np.float32)
    sr = _tts.synthesizer.output_sample_rate if hasattr(_tts, 'synthesizer') and _tts.synthesizer else SAMPLE_RATE
    return audio.tobytes(), sr


def list_voices() -> list[dict]:
    """Return available voices from the loaded model."""
    global _tts, _model_name
    if _tts is None:
        return [{"id": "default", "name": "Default", "language": "en", "gender": None}]

    voices = []
    if _tts.speakers:
        for speaker in _tts.speakers:
            voices.append({
                "id": speaker,
                "name": speaker,
                "language": "en",
                "gender": None,
            })
    else:
        name = _model_name.split("/")[-1] if _model_name else "Default"
        voices.append({
            "id": "default",
            "name": name,
            "language": "en",
            "gender": None,
        })
    return voices


class CoquiHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[coqui] {fmt % args}")

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
                "model_name": _model_name,
                "device": _device,
                "sample_rate": SAMPLE_RATE,
            })
            return

        if path == "/voices":
            self._send_json(list_voices())
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

                print(f"[coqui] Synthesizing voice={voice}: \"{text[:60]}\"")
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
                print(f"[coqui] Synthesis error: {e}")
                self._send_error(str(e))
            return

        self._send_error("Not found", 404)


def main():
    parser = argparse.ArgumentParser(description="Coqui TTS server for web-vox")
    parser.add_argument("--port", type=int, default=21743, help="Port to listen on")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "mps"],
                        help="Torch device")
    parser.add_argument("--model", default="tts_models/en/ljspeech/tacotron2-DDC",
                        help="Coqui TTS model name (run `tts --list_models` to see options)")
    parser.add_argument("--lazy", action="store_true",
                        help="Defer model loading until first synthesis request")
    args = parser.parse_args()

    global _device
    _device = get_device(args.device)

    if not args.lazy:
        load_model(args.model, _device)
    else:
        global _model_name
        _model_name = args.model

    server = HTTPServer(("127.0.0.1", args.port), CoquiHandler)
    print(f"[coqui] Server listening on http://127.0.0.1:{args.port}")
    print("[coqui] Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[coqui] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
