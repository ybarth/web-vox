#!/usr/bin/env python3
"""
Qwen3-TTS Base voice cloning HTTP server for web-vox.

Loads the Qwen3-TTS Base model once on startup and serves voice cloning synthesis requests.
Voice samples are read from the shared voice-samples/ directory.

Usage:
    python3.12 qwen_tts_clone_server.py [--port 21746] [--device cpu|cuda|mps] [--model 0.6B|1.7B] [--lazy]

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
import torch

SAMPLE_RATE = 24000

_model = None
_model_name = None
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
    if requested == "cuda" and torch.cuda.is_available():
        return "cuda"
    if requested == "mps" and torch.backends.mps.is_available():
        return "mps"
    if requested in ("cuda", "mps"):
        print(f"[qwen-clone] {requested} not available, falling back to cpu")
    return "cpu"


def load_model(model_size: str, device: str) -> None:
    global _model, _model_name, _device
    if _model is not None:
        return

    repo = f"Qwen/Qwen3-TTS-12Hz-{model_size}-Base"
    _model_name = repo
    _device = device

    print(f"[qwen-clone] Loading model '{repo}' on {device}...")
    print(f"[qwen-clone] First run will download the model from HuggingFace.")
    from qwen_tts import Qwen3TTSModel

    dtype = torch.float32 if device == "cpu" else torch.bfloat16
    kwargs = {
        "device_map": device if device != "cpu" else "cpu",
        "dtype": dtype,
    }
    if device == "cuda":
        kwargs["attn_implementation"] = "flash_attention_2"

    _model = Qwen3TTSModel.from_pretrained(repo, **kwargs)
    print("[qwen-clone] Model loaded successfully.")


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


def synthesize(text: str, sample_name: str, language: str = "English") -> tuple[bytes, int]:
    global _model
    if _model is None:
        raise RuntimeError("Model not loaded")

    samples_dir = find_voice_samples_dir()
    sample_path = None
    for ext in (".wav", ".flac", ".mp3", ".ogg"):
        candidate = samples_dir / f"{sample_name}{ext}"
        if candidate.exists():
            sample_path = str(candidate)
            break

    if sample_path is None:
        raise ValueError(f"Voice sample '{sample_name}' not found in {samples_dir}")

    wavs, sr = _model.generate_voice_clone(
        text=text,
        language=language,
        ref_audio=sample_path,
        ref_text="",
    )

    audio = np.array(wavs[0], dtype=np.float32)
    return audio.tobytes(), sr


class QwenCloneHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[qwen-clone] {fmt % args}")

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
                "model_loaded": _model is not None,
                "model_name": _model_name,
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
                language = body.get("language", "English")

                print(f"[qwen-clone] Cloning voice={voice} lang={language}: \"{text[:60]}\"")
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
                print(f"[qwen-clone] Synthesis error: {e}")
                import traceback; traceback.print_exc()
                self._send_error(str(e))
            return

        self._send_error("Not found", 404)


def main():
    parser = argparse.ArgumentParser(description="Qwen3-TTS voice cloning server for web-vox")
    parser.add_argument("--port", type=int, default=21746, help="Port to listen on")
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda", "mps"],
                        help="Torch device")
    parser.add_argument("--model", default="0.6B", choices=["0.6B", "1.7B"],
                        help="Model size (0.6B lighter, 1.7B higher quality)")
    parser.add_argument("--lazy", action="store_true",
                        help="Defer model loading until first synthesis request")
    args = parser.parse_args()

    global _device
    _device = get_device(args.device)

    if not args.lazy:
        load_model(args.model, _device)
    else:
        global _model_name
        _model_name = f"Qwen/Qwen3-TTS-12Hz-{args.model}-Base"

    server = HTTPServer(("127.0.0.1", args.port), QwenCloneHandler)
    print(f"[qwen-clone] Server listening on http://127.0.0.1:{args.port}")
    print("[qwen-clone] Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[qwen-clone] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
