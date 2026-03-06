#!/usr/bin/env python3
"""
Qwen3-TTS HTTP server for web-vox.

Loads the Qwen3-TTS CustomVoice model once on startup and serves synthesis requests.
Models are automatically downloaded from HuggingFace on first use.

Usage:
    python3.12 qwen_tts_server.py [--port 21744] [--device cpu|cuda|mps] [--model 0.6B|1.7B] [--lazy]

Endpoints:
    GET  /health      - Health check
    GET  /voices      - List available speakers
    POST /synthesize  - Synthesize text to PCM audio (raw f32 LE bytes)
"""

import argparse
import json
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import numpy as np
import torch

SAMPLE_RATE = 24000

# Lazy-loaded state
_model = None
_model_name = None
_device = None

SPEAKERS = [
    {"id": "Ryan",      "name": "Ryan (English Male)",       "language": "en", "gender": "Male"},
    {"id": "Aiden",     "name": "Aiden (English Male)",      "language": "en", "gender": "Male"},
    {"id": "Vivian",    "name": "Vivian (Chinese Female)",   "language": "zh", "gender": "Female"},
    {"id": "Serena",    "name": "Serena (Chinese Female)",   "language": "zh", "gender": "Female"},
    {"id": "Uncle_Fu",  "name": "Uncle Fu (Chinese Male)",   "language": "zh", "gender": "Male"},
    {"id": "Dylan",     "name": "Dylan (Beijing Male)",      "language": "zh", "gender": "Male"},
    {"id": "Eric",      "name": "Eric (Sichuan Male)",       "language": "zh", "gender": "Male"},
    {"id": "Ono_Anna",  "name": "Ono Anna (Japanese Female)","language": "ja", "gender": "Female"},
    {"id": "Sohee",     "name": "Sohee (Korean Female)",     "language": "ko", "gender": "Female"},
]


def get_device(requested: str) -> str:
    if requested == "cuda" and torch.cuda.is_available():
        return "cuda"
    if requested == "mps" and torch.backends.mps.is_available():
        return "mps"
    if requested in ("cuda", "mps"):
        print(f"[qwen-tts] {requested} not available, falling back to cpu")
    return "cpu"


def load_model(model_size: str, device: str) -> None:
    global _model, _model_name, _device
    if _model is not None:
        return

    repo = f"Qwen/Qwen3-TTS-12Hz-{model_size}-CustomVoice"
    _model_name = repo
    _device = device

    print(f"[qwen-tts] Loading model '{repo}' on {device}...")
    print(f"[qwen-tts] First run will download the model from HuggingFace.")
    from qwen_tts import Qwen3TTSModel

    dtype = torch.float32 if device == "cpu" else torch.bfloat16
    kwargs = {
        "device_map": device if device != "cpu" else "cpu",
        "dtype": dtype,
    }
    # flash_attention_2 only works on CUDA
    if device == "cuda":
        kwargs["attn_implementation"] = "flash_attention_2"

    _model = Qwen3TTSModel.from_pretrained(repo, **kwargs)
    print("[qwen-tts] Model loaded successfully.")


def synthesize(text: str, speaker: str, language: str) -> tuple[bytes, int]:
    global _model
    if _model is None:
        raise RuntimeError("Model not loaded")

    wavs, sr = _model.generate_custom_voice(
        text=text,
        language=language,
        speaker=speaker,
    )

    audio = np.array(wavs[0], dtype=np.float32)
    return audio.tobytes(), sr


class QwenTTSHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[qwen-tts] {fmt % args}")

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
            self._send_json(SPEAKERS)
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

                voice = body.get("voice", "Ryan")
                # Map language codes to Qwen language names
                lang_map = {
                    "en": "English", "zh": "Chinese", "ja": "Japanese",
                    "ko": "Korean", "de": "German", "fr": "French",
                    "ru": "Russian", "pt": "Portuguese", "es": "Spanish",
                    "it": "Italian",
                }
                # Find speaker's native language, default to English
                speaker_lang = "English"
                for s in SPEAKERS:
                    if s["id"] == voice:
                        speaker_lang = lang_map.get(s["language"], "English")
                        break
                language = body.get("language", speaker_lang)

                print(f"[qwen-tts] Synthesizing speaker={voice} lang={language}: \"{text[:60]}\"")
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
                print(f"[qwen-tts] Synthesis error: {e}")
                import traceback; traceback.print_exc()
                self._send_error(str(e))
            return

        self._send_error("Not found", 404)


def main():
    parser = argparse.ArgumentParser(description="Qwen3-TTS server for web-vox")
    parser.add_argument("--port", type=int, default=21744, help="Port to listen on")
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
        _model_name = f"Qwen/Qwen3-TTS-12Hz-{args.model}-CustomVoice"

    server = HTTPServer(("127.0.0.1", args.port), QwenTTSHandler)
    print(f"[qwen-tts] Server listening on http://127.0.0.1:{args.port}")
    print("[qwen-tts] Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[qwen-tts] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
