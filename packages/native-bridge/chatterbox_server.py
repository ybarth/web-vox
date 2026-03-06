#!/usr/bin/env python3
"""
Chatterbox TTS HTTP server for web-vox.

Loads the Chatterbox model once on startup and serves synthesis requests.
Manages voice samples on disk for voice cloning.

Usage:
    python3 chatterbox_server.py [--port 21741] [--device mps|cuda|cpu]

Endpoints:
    GET  /health          - Health check
    POST /synthesize      - Synthesize text to PCM audio
    GET  /voices          - List available voice samples
    POST /upload_sample   - Upload a voice sample WAV
    DELETE /sample/<name> - Delete a voice sample
"""

import argparse
import io
import json
import os
import struct
import sys
import wave
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import numpy as np
import torch

# Add the venv's site-packages if running outside the venv
SCRIPT_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = SCRIPT_DIR / "voice-samples"
SAMPLES_DIR.mkdir(exist_ok=True)

# Lazy-loaded model
model = None
model_device = None


def get_device(requested: str) -> str:
    if requested == "cuda" and torch.cuda.is_available():
        return "cuda"
    if requested == "mps" and torch.backends.mps.is_available():
        return "mps"
    if requested in ("cuda", "mps"):
        print(f"[chatterbox] {requested} not available, falling back to cpu")
    return "cpu"


def load_model(device: str):
    global model, model_device
    if model is not None:
        return

    print(f"[chatterbox] Loading model on {device}...")
    from chatterbox.tts import ChatterboxTTS
    model = ChatterboxTTS.from_pretrained(device)
    model_device = device
    print(f"[chatterbox] Model loaded (sample rate: {model.sr})")


def list_samples() -> list[dict]:
    samples = []
    for f in sorted(SAMPLES_DIR.iterdir()):
        if f.suffix.lower() in (".wav", ".flac", ".mp3", ".ogg"):
            samples.append({
                "name": f.stem,
                "filename": f.name,
                "size_bytes": f.stat().st_size,
            })
    return samples


def synthesize(text: str, sample_name: str | None, exaggeration: float,
               cfg_weight: float, temperature: float) -> tuple[bytes, int]:
    """Synthesize text, return (raw_pcm_f32_le_bytes, sample_rate)."""
    load_model(model_device)

    audio_prompt_path = None
    if sample_name:
        # Find the sample file
        for f in SAMPLES_DIR.iterdir():
            if f.stem == sample_name and f.suffix.lower() in (".wav", ".flac", ".mp3", ".ogg"):
                audio_prompt_path = str(f)
                break
        if audio_prompt_path is None:
            raise ValueError(f"Voice sample '{sample_name}' not found")

    wav = model.generate(
        text,
        audio_prompt_path=audio_prompt_path,
        exaggeration=exaggeration,
        cfg_weight=cfg_weight,
        temperature=temperature,
    )

    # wav is a torch tensor [1, N] — convert to numpy float32
    samples = wav.squeeze(0).numpy().astype(np.float32)
    pcm_bytes = samples.tobytes()
    return pcm_bytes, model.sr


class ChatterboxHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[chatterbox] {format % args}")

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, msg: str, status: int = 500):
        self._send_json({"error": msg}, status)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", 0))
        return self.rfile.read(length)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/health":
            self._send_json({
                "status": "ok",
                "model_loaded": model is not None,
                "device": model_device,
                "sample_rate": model.sr if model else 24000,
            })
            return

        if path == "/voices":
            self._send_json({"samples": list_samples()})
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

                sample_name = body.get("voice_sample")
                exaggeration = float(body.get("exaggeration", 0.5))
                cfg_weight = float(body.get("cfg_weight", 0.5))
                temperature = float(body.get("temperature", 0.8))

                print(f"[chatterbox] Synthesizing: \"{text[:60]}\" sample={sample_name}")
                pcm_bytes, sr = synthesize(text, sample_name, exaggeration, cfg_weight, temperature)

                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("X-Sample-Rate", str(sr))
                self.send_header("X-Channels", "1")
                self.send_header("Content-Length", str(len(pcm_bytes)))
                self.end_headers()
                self.wfile.write(pcm_bytes)
            except Exception as e:
                import traceback
                traceback.print_exc()
                print(f"[chatterbox] Synthesis error: {e}")
                self._send_error(str(e))
            return

        if path == "/upload_sample":
            try:
                content_type = self.headers.get("Content-Type", "")

                if "multipart/form-data" in content_type:
                    # Parse multipart — extract the file
                    import cgi
                    form = cgi.FieldStorage(
                        fp=self.rfile,
                        headers=self.headers,
                        environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": content_type},
                    )
                    name = form.getvalue("name", "sample")
                    file_item = form["file"]
                    data = file_item.file.read()
                else:
                    # Raw WAV upload with name in query string
                    params = parse_qs(urlparse(self.path).query)
                    name = params.get("name", ["sample"])[0]
                    data = self._read_body()

                # Sanitize name
                name = "".join(c for c in name if c.isalnum() or c in "-_ ").strip()
                if not name:
                    name = "sample"

                dest = SAMPLES_DIR / f"{name}.wav"
                dest.write_bytes(data)

                print(f"[chatterbox] Saved voice sample: {dest.name} ({len(data)} bytes)")
                self._send_json({"name": name, "filename": dest.name, "size_bytes": len(data)})
            except Exception as e:
                print(f"[chatterbox] Upload error: {e}")
                self._send_error(str(e))
            return

        self._send_error("Not found", 404)

    def do_DELETE(self):
        path = urlparse(self.path).path

        if path.startswith("/sample/"):
            name = path[len("/sample/"):]
            deleted = False
            for f in SAMPLES_DIR.iterdir():
                if f.stem == name:
                    f.unlink()
                    deleted = True
                    print(f"[chatterbox] Deleted voice sample: {f.name}")
                    break

            if deleted:
                self._send_json({"deleted": name})
            else:
                self._send_error(f"Sample '{name}' not found", 404)
            return

        self._send_error("Not found", 404)


def main():
    parser = argparse.ArgumentParser(description="Chatterbox TTS server for web-vox")
    parser.add_argument("--port", type=int, default=21741, help="Port to listen on")
    parser.add_argument("--device", default="mps", choices=["cpu", "cuda", "mps"],
                        help="Torch device for inference")
    parser.add_argument("--lazy", action="store_true",
                        help="Defer model loading until first synthesis request")
    args = parser.parse_args()

    global model_device
    model_device = get_device(args.device)

    if not args.lazy:
        load_model(model_device)

    server = HTTPServer(("127.0.0.1", args.port), ChatterboxHandler)
    print(f"[chatterbox] Server listening on http://127.0.0.1:{args.port}")
    print(f"[chatterbox] Voice samples directory: {SAMPLES_DIR}")
    print(f"[chatterbox] Press Ctrl+C to stop.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[chatterbox] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
