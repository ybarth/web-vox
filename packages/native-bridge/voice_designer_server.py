#!/usr/bin/env python3
"""
Voice designer server for web-vox-pro.

Text-prompted voice creation via Parler-TTS, speaker embedding extraction,
and multi-sample blending via embedding interpolation.

Port: 21749

Endpoints:
    GET  /health          — status check
    POST /design          — create voice from text description (Parler-TTS)
    POST /extract_embedding — extract speaker embedding from audio
    POST /blend           — blend multiple embeddings with weights
    POST /preview         — preview a voice design with reference audio
    POST /save_profile    — save a voice design to disk
    GET  /list_profiles   — list saved voice profiles
    POST /delete_profile  — delete a saved voice profile

Usage:
    python3 voice_designer_server.py [--device cpu|cuda|mps] [--port 21749]
"""

import argparse
import base64
import hashlib
import io
import json
import os
import shlex
import struct
import subprocess
import threading
import time
import uuid
import urllib.error
import urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from socketserver import ThreadingMixIn
from urllib.parse import urlparse

import numpy as np

# Load .env for API keys
def _load_env_fallback(env_path: Path) -> int:
    """Minimal .env loader used when python-dotenv is not installed."""
    loaded = 0
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if value and value[0] in ("'", '"'):
            try:
                value = shlex.split(value)[0]
            except Exception:
                value = value.strip("'\"")
        os.environ[key] = value
        loaded += 1
    return loaded


_env_path = Path(__file__).resolve().parents[2] / ".env"
if _env_path.exists():
    try:
        from dotenv import load_dotenv
        load_dotenv(_env_path)
        print(f"  [voice-designer] Loaded .env from {_env_path}")
    except ImportError:
        loaded = _load_env_fallback(_env_path)
        print(f"  [voice-designer] Loaded {loaded} env entries from {_env_path} (fallback loader)")

# ── Gemini AI client ─────────────────────────────────────────────────

_gemini_client = None
_gemini_available = False
_gemini_model_name = "gemini-3-pro-preview"


def _init_gemini():
    """Initialize the Gemini generative AI client from env."""
    global _gemini_client, _gemini_available
    if _gemini_client is not None:
        return _gemini_available

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("VITE_GEMINI_API_KEY")
    if not api_key:
        print("  [voice-designer] No GEMINI_API_KEY found — falling back to keyword matching")
        _gemini_client = "unavailable"
        _gemini_available = False
        return False

    try:
        from google import genai
        _gemini_client = genai.Client(api_key=api_key)
        _gemini_available = True
        print(f"  [voice-designer] Gemini AI initialized ({_gemini_model_name})")
        return True
    except Exception as e:
        print(f"  [voice-designer] Gemini init failed: {e}")
        _gemini_client = "unavailable"
        _gemini_available = False
        return False


def _gemini_json(prompt: str, fallback: dict | None = None) -> dict | None:
    """Send a prompt to Gemini and parse the JSON response."""
    if not _init_gemini() or not _gemini_available:
        return fallback

    try:
        from google.genai import types
        response = _gemini_client.models.generate_content(
            model=_gemini_model_name,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        text = response.text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        parsed = json.loads(text)
        # If Gemini returns a list, unwrap the first element
        if isinstance(parsed, list) and len(parsed) > 0:
            parsed = parsed[0]
        return parsed if isinstance(parsed, dict) else fallback
    except Exception as e:
        print(f"  [voice-designer] Gemini request failed: {e}")
        return fallback


def _gemini_text(prompt: str, fallback: str = "") -> str:
    """Send a prompt to Gemini and return plain text response."""
    if not _init_gemini() or not _gemini_available:
        return fallback

    try:
        from google.genai import types
        response = _gemini_client.models.generate_content(
            model=_gemini_model_name,
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.4),
        )
        return response.text.strip()
    except Exception as e:
        print(f"  [voice-designer] Gemini request failed: {e}")
        return fallback

# ── ElevenLabs API client ────────────────────────────────────────────

_elevenlabs_api_key = None
_elevenlabs_available = False
_elevenlabs_call_times: list[float] = []
_elevenlabs_cache: dict[str, dict] = {}  # MD5 -> result, max 50 entries
_ELEVENLABS_RPM = 10
_ELEVENLABS_CACHE_MAX = 50


def _init_elevenlabs() -> bool:
    """Initialize ElevenLabs API from env."""
    global _elevenlabs_api_key, _elevenlabs_available
    if _elevenlabs_api_key is not None:
        return _elevenlabs_available

    key = os.environ.get("ELEVEN_LABS_API_KEY") or os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        print("  [voice-designer] No ELEVEN_LABS_API_KEY found — ElevenLabs unavailable")
        _elevenlabs_api_key = "unavailable"
        _elevenlabs_available = False
        return False

    # Validate key with a quick user check
    try:
        req = urllib.request.Request(
            "https://api.elevenlabs.io/v1/user",
            headers={"xi-api-key": key, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            tier = data.get("subscription", {}).get("tier", "unknown")
            chars = data.get("subscription", {}).get("character_count", 0)
            limit = data.get("subscription", {}).get("character_limit", 0)
            print(f"  [voice-designer] ElevenLabs initialized — tier: {tier}, "
                  f"chars: {chars}/{limit}")
            _elevenlabs_api_key = key
            _elevenlabs_available = True
            return True
    except Exception as e:
        print(f"  [voice-designer] ElevenLabs init failed: {e}")
        _elevenlabs_api_key = "unavailable"
        _elevenlabs_available = False
        return False


def _elevenlabs_request(method: str, path: str, body: dict | None = None,
                        timeout: int = 30) -> dict | bytes:
    """Low-level HTTP request to ElevenLabs API."""
    if not _elevenlabs_available or _elevenlabs_api_key in (None, "unavailable"):
        raise RuntimeError("ElevenLabs not available")

    url = f"https://api.elevenlabs.io{path}"
    headers = {
        "xi-api-key": _elevenlabs_api_key,
        "Accept": "application/json",
    }

    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ct = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "application/json" in ct:
                return json.loads(raw)
            return raw  # binary (audio)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:500]
        except Exception:
            pass
        raise RuntimeError(f"HTTP Error {e.code}: {body or e.reason}")


def _elevenlabs_rate_check():
    """Simple rate limiter — blocks if exceeding RPM."""
    now = time.time()
    _elevenlabs_call_times[:] = [t for t in _elevenlabs_call_times if now - t < 60]
    if len(_elevenlabs_call_times) >= _ELEVENLABS_RPM:
        wait = 60 - (now - _elevenlabs_call_times[0])
        if wait > 0:
            print(f"  [voice-designer] ElevenLabs rate limit — waiting {wait:.1f}s")
            time.sleep(wait)
    _elevenlabs_call_times.append(time.time())


def _mp3_bytes_to_pcm_f32(mp3_bytes: bytes, target_sr: int = 24000) -> tuple[bytes, int]:
    """Convert MP3 bytes to PCM float32 via ffmpeg, fallback to librosa."""
    # Try ffmpeg first (faster, no Python deps)
    try:
        proc = subprocess.run(
            ["ffmpeg", "-i", "pipe:0", "-f", "f32le", "-acodec", "pcm_f32le",
             "-ac", "1", "-ar", str(target_sr), "pipe:1"],
            input=mp3_bytes, capture_output=True, timeout=10,
        )
        if proc.returncode == 0 and len(proc.stdout) > 0:
            return proc.stdout, target_sr
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: librosa
    try:
        import librosa
        audio_np, sr = librosa.load(io.BytesIO(mp3_bytes), sr=target_sr, mono=True)
        return audio_np.astype(np.float32).tobytes(), target_sr
    except Exception as e:
        raise RuntimeError(f"Cannot convert MP3 to PCM: {e}")


def _mp3_base64_to_pcm_f32(mp3_b64: str, target_sr: int = 24000) -> tuple[str, int]:
    """Decode base64 MP3, convert to PCM f32, return as base64."""
    mp3_bytes = base64.b64decode(mp3_b64)
    pcm_bytes, sr = _mp3_bytes_to_pcm_f32(mp3_bytes, target_sr)
    return base64.b64encode(pcm_bytes).decode("ascii"), sr


_ELEVENLABS_MIN_PREVIEW = "The quick brown fox jumped over the lazy dog, and the sun set behind the mountains with a warm golden glow that painted the sky in shades of amber and rose."

def elevenlabs_design_voice(description: str, preview_text: str) -> dict:
    """Design voice via ElevenLabs text-to-voice preview API."""
    if not _init_elevenlabs():
        return {"success": False, "error": "ElevenLabs not available"}

    # ElevenLabs requires >= 20 chars for description
    if len(description) < 20:
        description = description + " with a clear, natural speaking style"

    # ElevenLabs requires >= 100 chars of preview text
    if len(preview_text) < 100:
        preview_text = _ELEVENLABS_MIN_PREVIEW

    # NOTE: No caching — generated_voice_id tokens are single-use
    _elevenlabs_rate_check()

    try:
        result = _elevenlabs_request("POST", "/v1/text-to-voice/create-previews", {
            "voice_description": description,
            "text": preview_text[:500],  # ElevenLabs has a text limit
        }, timeout=60)

        candidates = []
        previews = result.get("previews", [])
        for preview in previews:
            audio_b64_mp3 = preview.get("audio_base_64", "")
            generated_id = preview.get("generated_voice_id", "")

            # Convert MP3 to PCM f32 for consistent handling
            pcm_b64 = None
            sample_rate = 24000
            if audio_b64_mp3:
                try:
                    pcm_b64, sample_rate = _mp3_base64_to_pcm_f32(audio_b64_mp3)
                except Exception as e:
                    print(f"  [voice-designer] MP3 conversion failed: {e}")
                    pcm_b64 = audio_b64_mp3  # pass through as-is
                    sample_rate = 44100

            candidates.append({
                "generated_voice_id": generated_id,
                "audio_base64": pcm_b64,
                "audio_base64_mp3": audio_b64_mp3,
                "sample_rate": sample_rate,
            })

        response = {
            "success": True,
            "candidates": candidates,
            "description": description,
        }

        print(f"  [voice-designer] ElevenLabs design: {len(candidates)} candidates")
        return response

    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"  [voice-designer] ElevenLabs API error {e.code}: {body[:200]}")
        return {"success": False, "error": f"ElevenLabs API error {e.code}: {body[:200]}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def elevenlabs_create_voice(name: str, description: str,
                            generated_voice_id: str) -> dict:
    """Create a permanent voice from a preview."""
    if not _init_elevenlabs():
        return {"success": False, "error": "ElevenLabs not available"}

    _elevenlabs_rate_check()

    # ElevenLabs requires >= 20 chars for voice_description
    if len(description) < 20:
        description = description + " — custom designed voice"

    try:
        result = _elevenlabs_request("POST", "/v1/text-to-voice/create-voice-from-preview", {
            "voice_name": name,
            "voice_description": description,
            "generated_voice_id": generated_voice_id,
        })

        voice_id = result.get("voice_id", "")
        print(f"  [voice-designer] ElevenLabs voice created: {voice_id}")
        return {"success": True, "voice_id": voice_id}

    except Exception as e:
        return {"success": False, "error": str(e)}


def elevenlabs_synthesize(text: str, voice_id: str,
                          model_id: str = "eleven_multilingual_v2",
                          voice_settings: dict | None = None) -> dict:
    """Synthesize speech with an ElevenLabs voice."""
    if not _init_elevenlabs():
        return {"success": False, "error": "ElevenLabs not available"}

    _elevenlabs_rate_check()

    body = {"text": text, "model_id": model_id}
    if voice_settings:
        body["voice_settings"] = voice_settings

    try:
        audio_bytes = _elevenlabs_request(
            "POST", f"/v1/text-to-speech/{voice_id}", body, timeout=30)

        if isinstance(audio_bytes, dict):
            return {"success": False, "error": audio_bytes.get("detail", "Unknown error")}

        # Convert MP3 to PCM
        pcm_bytes, sr = _mp3_bytes_to_pcm_f32(audio_bytes)
        pcm_b64 = base64.b64encode(pcm_bytes).decode("ascii")

        return {
            "success": True,
            "audio_base64": pcm_b64,
            "sample_rate": sr,
            "duration_ms": len(pcm_bytes) / 4 / sr * 1000,  # f32 = 4 bytes per sample
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def elevenlabs_health() -> dict:
    """Check ElevenLabs API status."""
    if not _init_elevenlabs():
        return {"available": False, "error": "Not configured"}

    try:
        req = urllib.request.Request(
            "https://api.elevenlabs.io/v1/user",
            headers={"xi-api-key": _elevenlabs_api_key, "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            sub = data.get("subscription", {})
            return {
                "available": True,
                "tier": sub.get("tier", "unknown"),
                "character_count": sub.get("character_count", 0),
                "character_limit": sub.get("character_limit", 0),
                "remaining": sub.get("character_limit", 0) - sub.get("character_count", 0),
            }
    except Exception as e:
        return {"available": False, "error": str(e)}


# ── ElevenLabs prompt composer ───────────────────────────────────────

def compose_elevenlabs_description(anatomy_specs: dict,
                                   general_description: str = "") -> str:
    """Use Gemini to polish anatomy specs into an ElevenLabs description."""
    if not anatomy_specs and not general_description:
        return "A natural speaking voice"

    result = _gemini_text(f"""Write a voice description for the ElevenLabs text-to-voice API.

User's intent: "{general_description}"
Voice anatomy specs: {json.dumps(anatomy_specs) if anatomy_specs else "none specified"}

Write a natural English paragraph (2-3 sentences) describing this voice.
Focus on: gender/age, pitch, timbre, texture, speaking style, emotional tone.
Be specific and descriptive. Do NOT use markdown or quotes.
Example: "A young woman with a warm, rich voice. She speaks clearly with moderate pacing and a friendly, approachable tone. Her voice has a slightly breathy quality with natural expressiveness." """)

    if result and len(result) > 20 and not result.startswith("{"):
        return result.strip().strip('"').strip("'")

    return _compose_elevenlabs_description_basic(anatomy_specs, general_description)


def _compose_elevenlabs_description_basic(anatomy_specs: dict,
                                          general_description: str = "") -> str:
    """Keyword fallback for ElevenLabs description."""
    parts = []
    if general_description:
        parts.append(general_description.rstrip("."))

    _EL_AXIS_TEMPLATES = {
        "pitch": {"deep": "deep-voiced", "low": "low-pitched", "medium": "medium-pitched",
                   "high": "higher-pitched", "very high": "high-pitched"},
        "timbre": {"warm": "warm tone", "bright": "bright, clear tone",
                    "dark": "dark, smooth tone", "rich": "rich tonal quality"},
        "texture": {"clear": "crystal clear voice", "breathy": "slightly breathy",
                     "husky": "husky voice", "smooth": "silky smooth delivery"},
        "emotion": {"neutral": "professional demeanor", "warm": "friendly manner",
                     "authoritative": "commanding presence", "energetic": "upbeat energy"},
        "tempo": {"slow": "deliberate pacing", "moderate": "natural pacing",
                   "fast": "brisk delivery", "varied": "dynamic pacing"},
    }

    for element, templates in _EL_AXIS_TEMPLATES.items():
        spec = anatomy_specs.get(element, "").lower()
        for key, template in templates.items():
            if key in spec:
                parts.append(template)
                break

    if not parts:
        return "A natural speaking voice"
    return ". ".join(parts) + "."


# ── Voice Crafting Engine integration ────────────────────────────────

_crafting_engine = None


def _get_crafting_engine():
    """Lazy-init the crafting engine with proper function bindings."""
    global _crafting_engine
    if _crafting_engine is None:
        from voice_crafting import CraftingEngine
        _crafting_engine = CraftingEngine(
            elevenlabs_design_fn=elevenlabs_design_voice,
            elevenlabs_create_fn=elevenlabs_create_voice,
            parler_design_fn=design_voice,
            save_profile_fn=save_profile,
            gemini_text_fn=_gemini_text,
        )
    return _crafting_engine


# ── Lazy-loaded models ────────────────────────────────────────────────

_parler_model = None
_parler_tokenizer = None
_speaker_encoder = None
_device = "cpu"
_profiles_dir = None
_model_lock = threading.Lock()
_loading_status = {
    "parler": {"state": "idle", "stage": "", "progress": 0},
    "encoder": {"state": "idle", "stage": "", "progress": 0},
}

PROFILES_DIR_NAME = "voice_profiles"


def _load_config():
    """Load device config from device_config.json if present."""
    global _device
    config_path = Path(__file__).parent / "device_config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            vd = config.get("voice_designer", {})
            _device = vd.get("device", _device)
        except Exception as e:
            print(f"  [voice-designer] Warning: failed to read device_config.json: {e}")


def _get_profiles_dir() -> Path:
    global _profiles_dir
    if _profiles_dir is None:
        _profiles_dir = Path(__file__).parent / PROFILES_DIR_NAME
        _profiles_dir.mkdir(exist_ok=True)
    return _profiles_dir


def _get_parler():
    """Load Parler-TTS model for text-prompted voice generation."""
    global _parler_model, _parler_tokenizer
    if _parler_model is None:
        with _model_lock:
            if _parler_model is not None:
                return _parler_model, _parler_tokenizer
            status = _loading_status["parler"]
            try:
                status.update(state="loading", stage="Importing parler-tts...", progress=5)
                from parler_tts import ParlerTTSForConditionalGeneration
                from transformers import AutoTokenizer
                import torch

                model_name = "parler-tts/parler-tts-mini-v1"

                status.update(stage=f"Downloading/loading model weights ({model_name})...", progress=15)
                print(f"  [voice-designer] Loading Parler-TTS '{model_name}' on {_device}...")
                t0 = time.time()

                _parler_model = ParlerTTSForConditionalGeneration.from_pretrained(
                    model_name
                )

                status.update(stage="Moving model to device...", progress=70)
                if _device != "cpu":
                    _parler_model = _parler_model.to(_device)

                status.update(stage="Loading tokenizer...", progress=85)
                _parler_tokenizer = AutoTokenizer.from_pretrained(model_name)

                elapsed = time.time() - t0
                status.update(state="ready", stage=f"Loaded in {elapsed:.1f}s", progress=100)
                print(f"  [voice-designer] Parler-TTS loaded in {elapsed:.1f}s")
            except Exception as e:
                print(f"  [voice-designer] Parler-TTS unavailable: {e}")
                status.update(state="error", stage=str(e), progress=0)
                _parler_model = "unavailable"
    return _parler_model, _parler_tokenizer


def _get_speaker_encoder():
    """Load speaker encoder for embedding extraction (Resemblyzer)."""
    global _speaker_encoder
    if _speaker_encoder is None:
        with _model_lock:
            if _speaker_encoder is not None:
                return _speaker_encoder
            status = _loading_status["encoder"]
            try:
                status.update(state="loading", stage="Importing resemblyzer...", progress=20)
                from resemblyzer import VoiceEncoder
                status.update(stage="Loading speaker encoder model...", progress=50)
                print(f"  [voice-designer] Loading speaker encoder...")
                t0 = time.time()
                _speaker_encoder = VoiceEncoder(_device)
                elapsed = time.time() - t0
                status.update(state="ready", stage=f"Loaded in {elapsed:.1f}s", progress=100)
                print(f"  [voice-designer] Speaker encoder loaded in {elapsed:.1f}s")
            except ImportError:
                print("  [voice-designer] Resemblyzer not available, using spectral fingerprint fallback")
                _speaker_encoder = "spectral_fallback"
                status.update(state="ready", stage="Using spectral fallback", progress=100)
            except Exception as e:
                print(f"  [voice-designer] Speaker encoder unavailable: {e}")
                _speaker_encoder = "unavailable"
                status.update(state="error", stage=str(e), progress=0)
    return _speaker_encoder


# ── Core functions ────────────────────────────────────────────────────

def design_voice(description: str, preview_text: str) -> dict:
    """Generate a voice sample from a text description using Parler-TTS."""
    model, tokenizer = _get_parler()
    if model == "unavailable" or model is None:
        return {"success": False, "error": "Parler-TTS model not available. Install: pip install parler-tts"}

    try:
        import torch

        input_ids = tokenizer(description, return_tensors="pt").input_ids
        prompt_ids = tokenizer(preview_text, return_tensors="pt").input_ids

        if _device != "cpu":
            input_ids = input_ids.to(_device)
            prompt_ids = prompt_ids.to(_device)

        print(f"  [voice-designer] Generating voice: '{description[:60]}...' saying '{preview_text[:40]}...'")
        t0 = time.time()

        with torch.no_grad():
            generation = model.generate(
                input_ids=input_ids,
                prompt_input_ids=prompt_ids,
            )

        audio_np = generation.cpu().numpy().squeeze()
        if audio_np.ndim > 1:
            audio_np = audio_np[0]
        audio_np = audio_np.astype(np.float32)

        # Normalize to [-1, 1]
        peak = np.max(np.abs(audio_np))
        if peak > 0:
            audio_np = audio_np / peak * 0.95

        sample_rate = model.config.sampling_rate
        elapsed = time.time() - t0
        duration_ms = len(audio_np) / sample_rate * 1000

        print(f"  [voice-designer] Generated {duration_ms:.0f}ms audio in {elapsed:.1f}s")

        # Encode audio as base64 PCM f32
        pcm_bytes = audio_np.tobytes()
        audio_b64 = base64.b64encode(pcm_bytes).decode("ascii")

        return {
            "success": True,
            "audio_base64": audio_b64,
            "sample_rate": int(sample_rate),
            "duration_ms": round(duration_ms, 1),
            "num_samples": len(audio_np),
            "description": description,
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def extract_embedding(pcm_f32: np.ndarray, sample_rate: int) -> dict:
    """Extract a speaker embedding from audio."""
    encoder = _get_speaker_encoder()
    if encoder == "unavailable":
        return {"success": False, "error": "Speaker encoder not available"}

    try:
        if encoder == "spectral_fallback":
            embedding = _spectral_embedding(pcm_f32, sample_rate)
        else:
            # Resemblyzer expects 16kHz
            audio = pcm_f32
            if sample_rate != 16000:
                try:
                    import librosa
                    audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=16000)
                except ImportError:
                    ratio = 16000 / sample_rate
                    indices = np.arange(0, len(audio), 1 / ratio).astype(int)
                    indices = indices[indices < len(audio)]
                    audio = audio[indices]

            from resemblyzer import preprocess_wav
            audio = preprocess_wav(audio, source_sr=16000)
            embedding = encoder.embed_utterance(audio)

        return {
            "success": True,
            "embedding": embedding.tolist(),
            "dimensions": len(embedding),
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


def isolate_target_speaker(pcm_f32: np.ndarray, sample_rate: int,
                           segment_duration: float = 2.0,
                           similarity_threshold: float = 0.6) -> tuple[np.ndarray, dict]:
    """Isolate the dominant/target speaker from mixed audio.

    Splits audio into segments, extracts per-segment embeddings, clusters them,
    picks the largest cluster as the target speaker, and returns only those segments
    concatenated. Also returns isolation metadata.

    Returns (isolated_audio, metadata).
    """
    n_samples = len(pcm_f32)
    seg_len = int(segment_duration * sample_rate)

    if n_samples < seg_len:
        # Too short to segment — return as-is
        return pcm_f32, {"isolated": False, "reason": "audio too short to segment",
                         "total_segments": 1, "kept_segments": 1}

    # Split into segments
    segments = []
    for start in range(0, n_samples - seg_len // 2, seg_len):
        end = min(start + seg_len, n_samples)
        seg = pcm_f32[start:end]
        # Skip near-silent segments
        rms = np.sqrt(np.mean(seg ** 2))
        if rms < 0.01:
            continue
        segments.append({"audio": seg, "start": start, "end": end, "rms": rms})

    if len(segments) < 2:
        return pcm_f32, {"isolated": False, "reason": "too few non-silent segments",
                         "total_segments": len(segments), "kept_segments": len(segments)}

    # Extract embedding for each segment
    embeddings = []
    for seg in segments:
        emb_result = extract_embedding(seg["audio"], sample_rate)
        if emb_result["success"]:
            seg["embedding"] = np.array(emb_result["embedding"], dtype=np.float32)
            embeddings.append(seg["embedding"])
        else:
            seg["embedding"] = None

    valid_segments = [s for s in segments if s["embedding"] is not None]
    if len(valid_segments) < 2:
        return pcm_f32, {"isolated": False, "reason": "could not extract enough embeddings",
                         "total_segments": len(segments), "kept_segments": len(valid_segments)}

    # Find the dominant speaker cluster using pairwise cosine similarity
    # Compute the centroid of all embeddings as initial reference
    all_embs = np.array([s["embedding"] for s in valid_segments])

    # Use the segment with highest average similarity to others as the anchor
    similarity_matrix = np.zeros((len(valid_segments), len(valid_segments)))
    for i in range(len(valid_segments)):
        for j in range(len(valid_segments)):
            if i != j:
                cos_sim = np.dot(all_embs[i], all_embs[j]) / (
                    np.linalg.norm(all_embs[i]) * np.linalg.norm(all_embs[j]) + 1e-8)
                similarity_matrix[i][j] = cos_sim

    avg_similarities = similarity_matrix.sum(axis=1) / (len(valid_segments) - 1)
    anchor_idx = int(np.argmax(avg_similarities))
    anchor_emb = all_embs[anchor_idx]

    # Compute similarities to anchor
    for i, seg in enumerate(valid_segments):
        cos_sim = np.dot(seg["embedding"], anchor_emb) / (
            np.linalg.norm(seg["embedding"]) * np.linalg.norm(anchor_emb) + 1e-8)
        seg["similarity"] = float(cos_sim)

    similarities = [s["similarity"] for s in valid_segments]
    sim_mean = np.mean(similarities)
    sim_std = np.std(similarities)

    # Adaptive threshold: use the higher of the fixed threshold or (mean - 1.5*std)
    # This catches outlier segments that differ from the dominant speaker
    adaptive_threshold = max(similarity_threshold, sim_mean - 1.5 * sim_std)

    kept = []
    rejected = []
    for seg in valid_segments:
        if seg["similarity"] >= adaptive_threshold:
            kept.append(seg)
        else:
            rejected.append(seg)

    if not kept:
        # All rejected — fall back to top half
        valid_segments.sort(key=lambda s: s.get("similarity", 0), reverse=True)
        kept = valid_segments[:len(valid_segments) // 2 + 1]
        rejected = valid_segments[len(kept):]

    # Concatenate kept segments in order
    kept.sort(key=lambda s: s["start"])
    isolated = np.concatenate([s["audio"] for s in kept])

    metadata = {
        "isolated": True,
        "total_segments": len(segments),
        "valid_segments": len(valid_segments),
        "kept_segments": len(kept),
        "rejected_segments": len(rejected),
        "anchor_segment": anchor_idx,
        "similarity_threshold_fixed": similarity_threshold,
        "similarity_threshold_adaptive": round(float(adaptive_threshold), 3),
        "kept_similarities": [round(s.get("similarity", 0), 3) for s in kept],
        "rejected_similarities": [round(s.get("similarity", 0), 3) for s in rejected],
        "original_duration_s": round(n_samples / sample_rate, 2),
        "isolated_duration_s": round(len(isolated) / sample_rate, 2),
    }

    print(f"  [voice-designer] Speaker isolation: kept {len(kept)}/{len(valid_segments)} "
          f"segments ({metadata['isolated_duration_s']:.1f}s / "
          f"{metadata['original_duration_s']:.1f}s)")

    return isolated, metadata


def _spectral_embedding(pcm_f32: np.ndarray, sample_rate: int, n_dims: int = 256) -> np.ndarray:
    """Speaker-discriminative embedding using MFCCs + deltas + pitch statistics.

    Much better than mel spectrogram averages for distinguishing between
    different speakers in the same audio clip.
    """
    try:
        import librosa

        # MFCCs capture vocal tract shape (speaker-specific)
        n_mfcc = 20
        mfccs = librosa.feature.mfcc(y=pcm_f32, sr=sample_rate, n_mfcc=n_mfcc)
        # Delta and delta-delta capture temporal dynamics
        mfcc_delta = librosa.feature.delta(mfccs)
        mfcc_delta2 = librosa.feature.delta(mfccs, order=2)

        # Statistics per coefficient: mean, std, skew, kurtosis
        features = []
        for feat_matrix in [mfccs, mfcc_delta, mfcc_delta2]:
            features.append(np.mean(feat_matrix, axis=1))
            features.append(np.std(feat_matrix, axis=1))

        # Pitch statistics (F0) — very speaker-discriminative
        f0, voiced, _ = librosa.pyin(pcm_f32, fmin=50, fmax=600, sr=sample_rate)
        f0_valid = f0[~np.isnan(f0)] if f0 is not None else np.array([150.0])
        if len(f0_valid) == 0:
            f0_valid = np.array([150.0])
        pitch_stats = np.array([
            np.mean(f0_valid), np.std(f0_valid),
            np.median(f0_valid), np.percentile(f0_valid, 10),
            np.percentile(f0_valid, 90),
        ])
        features.append(pitch_stats)

        # Spectral contrast — captures harmonic vs. noise balance
        contrast = librosa.feature.spectral_contrast(y=pcm_f32, sr=sample_rate)
        features.append(np.mean(contrast, axis=1))
        features.append(np.std(contrast, axis=1))

        embedding = np.concatenate(features).astype(np.float32)

        # Pad or truncate to n_dims
        if len(embedding) < n_dims:
            embedding = np.pad(embedding, (0, n_dims - len(embedding)))
        elif len(embedding) > n_dims:
            embedding = embedding[:n_dims]

        # L2 normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding

    except ImportError:
        # Ultra-basic: FFT mean spectrum
        n_fft = min(2048, len(pcm_f32))
        spectrum = np.abs(np.fft.rfft(pcm_f32, n=n_fft))
        indices = np.linspace(0, len(spectrum) - 1, n_dims).astype(int)
        embedding = spectrum[indices]
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding.astype(np.float32)


def blend_embeddings(embeddings: list[list[float]], weights: list[float]) -> dict:
    """Blend speaker embeddings via weighted interpolation (1+ embeddings)."""
    if len(embeddings) < 1:
        return {"success": False, "error": "Need at least 1 embedding"}
    if len(embeddings) != len(weights):
        return {"success": False, "error": "Number of embeddings must match number of weights"}

    dims = len(embeddings[0])
    if not all(len(e) == dims for e in embeddings):
        return {"success": False, "error": "All embeddings must have the same dimensions"}

    emb_array = np.array(embeddings, dtype=np.float32)
    w = np.array(weights, dtype=np.float32)
    w = w / w.sum()  # Normalize weights

    blended = np.average(emb_array, axis=0, weights=w)

    # Normalize the blended embedding
    norm = np.linalg.norm(blended)
    if norm > 0:
        blended = blended / norm

    return {
        "success": True,
        "embedding": blended.tolist(),
        "dimensions": int(dims),
        "weights_normalized": w.tolist(),
    }


def save_profile(profile_id: str, name: str, description: str,
                 embedding: list[float] | None, reference_audio_b64: str | None,
                 sample_rate: int) -> dict:
    """Save a voice profile to disk."""
    profiles_dir = _get_profiles_dir()
    if not profile_id:
        profile_id = str(uuid.uuid4())[:8]

    profile = {
        "id": profile_id,
        "name": name,
        "description": description,
        "sample_rate": sample_rate,
        "created_at": time.time(),
    }

    if embedding is not None:
        profile["embedding"] = embedding
        profile["embedding_dimensions"] = len(embedding)

    profile_path = profiles_dir / f"{profile_id}.json"
    profile_path.write_text(json.dumps(profile, indent=2))

    # Save reference audio if provided
    if reference_audio_b64:
        audio_path = profiles_dir / f"{profile_id}.pcm"
        audio_path.write_bytes(base64.b64decode(reference_audio_b64))

    print(f"  [voice-designer] Saved profile '{name}' as {profile_id}")
    return {"success": True, "profile_id": profile_id}


def list_profiles() -> list[dict]:
    """List all saved voice profiles."""
    profiles_dir = _get_profiles_dir()
    profiles = []
    for path in sorted(profiles_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text())
            # Don't send embedding in list (too large)
            summary = {
                "id": data.get("id", path.stem),
                "name": data.get("name", "Unnamed"),
                "description": data.get("description", ""),
                "sample_rate": data.get("sample_rate", 22050),
                "has_embedding": "embedding" in data,
                "has_reference_audio": (profiles_dir / f"{path.stem}.pcm").exists(),
                "created_at": data.get("created_at", 0),
            }
            profiles.append(summary)
        except Exception:
            continue
    return profiles


def delete_profile(profile_id: str) -> dict:
    """Delete a saved voice profile."""
    profiles_dir = _get_profiles_dir()
    json_path = profiles_dir / f"{profile_id}.json"
    pcm_path = profiles_dir / f"{profile_id}.pcm"

    deleted = False
    if json_path.exists():
        json_path.unlink()
        deleted = True
    if pcm_path.exists():
        pcm_path.unlink()
        deleted = True

    return {"success": deleted, "error": None if deleted else "Profile not found"}


def get_profile(profile_id: str) -> dict | None:
    """Load a voice profile (including embedding)."""
    profiles_dir = _get_profiles_dir()
    json_path = profiles_dir / f"{profile_id}.json"
    if not json_path.exists():
        return None
    data = json.loads(json_path.read_text())

    # Include reference audio if available
    pcm_path = profiles_dir / f"{profile_id}.pcm"
    if pcm_path.exists():
        data["reference_audio_base64"] = base64.b64encode(pcm_path.read_bytes()).decode("ascii")

    return data


# ── Voice Anatomy ────────────────────────────────────────────────────

VOICE_ANATOMY = {
    "timbre": {
        "label": "Timbre",
        "description": "Tonal color and warmth of the voice",
        "examples": ["warm", "bright", "dark", "metallic", "velvety", "rich",
                      "thin", "woody", "reedy", "round", "sharp"],
    },
    "pitch": {
        "label": "Pitch Range",
        "description": "Fundamental frequency register",
        "examples": ["deep bass", "deep voice", "low baritone", "low voice",
                      "mid tenor", "alto", "high soprano", "high-pitched",
                      "falsetto", "baritone", "tenor", "soprano"],
    },
    "resonance": {
        "label": "Resonance",
        "description": "Where the voice vibrates and projects from",
        "examples": ["chest", "throat", "nasal", "head voice", "mixed",
                      "booming", "hollow", "full-bodied"],
    },
    "texture": {
        "label": "Texture",
        "description": "Surface quality and grain of the voice",
        "examples": ["clear", "breathy", "raspy", "husky", "smooth",
                      "gravelly", "crisp", "silky", "rough", "airy"],
    },
    "accent": {
        "label": "Accent & Dialect",
        "description": "Regional, cultural, or stylistic speech patterns",
        "examples": ["neutral American", "British RP", "Southern US",
                      "Australian", "Irish", "Transatlantic", "urban",
                      "formal", "colloquial"],
    },
    "prosody": {
        "label": "Prosody & Intonation",
        "description": "Melodic contour, stress patterns, and rhythm",
        "examples": ["monotone", "melodic", "staccato", "flowing",
                      "dramatic", "lilting", "measured", "sing-song",
                      "rising inflection", "flat"],
    },
    "tempo": {
        "label": "Tempo & Pacing",
        "description": "Speaking speed and rhythmic timing",
        "examples": ["very slow", "slow", "deliberate", "moderate", "brisk",
                      "rapid", "fast", "varied", "pausing", "steady"],
    },
    "emotion": {
        "label": "Emotion & Affect",
        "description": "Emotional coloring and attitude",
        "examples": ["neutral", "warm", "authoritative", "playful",
                      "somber", "energetic", "intimate", "detached",
                      "passionate", "serene", "menacing"],
    },
    "articulation": {
        "label": "Articulation",
        "description": "Precision and style of consonant and vowel delivery",
        "examples": ["precise", "casual", "clipped", "elongated",
                      "mumbled", "over-enunciated", "natural", "crisp"],
    },
    "dynamics": {
        "label": "Dynamics",
        "description": "Volume variation, emphasis, and breath control",
        "examples": ["flat", "gentle", "punchy", "expressive",
                      "whispered", "projected", "crescendo", "intimate"],
    },
}


def _decompose_description_keywords(description: str) -> dict:
    """Keyword-based fallback for description decomposition."""
    desc_lower = description.lower()
    result = {}
    for element, info in VOICE_ANATOMY.items():
        matches = []
        for ex in info["examples"]:
            if ex.lower() in desc_lower:
                matches.append(ex)
        if matches:
            result[element] = matches
    if not result:
        result["_general"] = [description]
    return result


def decompose_description(description: str) -> dict:
    """Analyze a text description and map it to voice anatomy elements using Gemini AI.
    Understands natural language, metaphors, and references to real voices."""
    anatomy_keys = list(VOICE_ANATOMY.keys())
    anatomy_info = {k: {"label": v["label"], "description": v["description"],
                         "examples": v["examples"]} for k, v in VOICE_ANATOMY.items()}

    result = _gemini_json(f"""Analyze this voice description and map it to specific voice anatomy elements.

Description: "{description}"

Voice anatomy elements and their meanings:
{json.dumps(anatomy_info, indent=2)}

Interpret the description deeply — understand metaphors (e.g. "voice like honey" = warm, smooth timbre),
references to real people (e.g. "sounds like Morgan Freeman" = deep bass pitch, warm timbre, smooth texture, authoritative emotion, slow deliberate tempo),
and abstract qualities (e.g. "commanding presence" = projected dynamics, authoritative emotion, full-bodied resonance).

Return JSON mapping each relevant element key to an array of descriptive terms.
Only include elements that are relevant to the description.
Example: {{"timbre": ["warm", "rich"], "pitch": ["deep bass"], "emotion": ["authoritative"]}}

If the description mentions a real person's voice, decompose what their voice actually sounds like.
Use the example values when they match, but you can also use other descriptive terms.""")

    if result and any(k in anatomy_keys for k in result):
        # Ensure all values are lists
        cleaned = {}
        for k, v in result.items():
            if k in anatomy_keys:
                cleaned[k] = v if isinstance(v, list) else [v]
        if cleaned:
            print(f"  [voice-designer] Gemini decomposed: {cleaned}")
            return cleaned

    return _decompose_description_keywords(description)


def analyze_audio_anatomy(pcm_f32: np.ndarray, sample_rate: int) -> dict:
    """Analyze audio to extract voice anatomy features.
    Returns measured values for pitch, dynamics, tempo, texture."""
    analysis = {}
    try:
        import librosa

        # Pitch analysis via F0
        f0, voiced, _ = librosa.pyin(pcm_f32, fmin=50, fmax=600, sr=sample_rate)
        f0_valid = f0[~np.isnan(f0)] if f0 is not None else np.array([])
        if len(f0_valid) > 0:
            f0_mean = float(np.mean(f0_valid))
            f0_std = float(np.std(f0_valid))
            if f0_mean < 120:
                pitch_label = "deep bass"
            elif f0_mean < 170:
                pitch_label = "low baritone"
            elif f0_mean < 220:
                pitch_label = "mid tenor"
            elif f0_mean < 300:
                pitch_label = "alto"
            else:
                pitch_label = "high soprano"
            analysis["pitch"] = {
                "f0_mean_hz": round(f0_mean, 1),
                "f0_std_hz": round(f0_std, 1),
                "label": pitch_label,
                "variability": "monotone" if f0_std < 15 else
                               "moderate" if f0_std < 40 else "expressive",
            }

        # Dynamics (energy variation)
        rms = librosa.feature.rms(y=pcm_f32)[0]
        rms_mean = float(np.mean(rms))
        rms_std = float(np.std(rms))
        dynamics_ratio = rms_std / rms_mean if rms_mean > 0 else 0
        analysis["dynamics"] = {
            "rms_mean": round(rms_mean, 4),
            "rms_std": round(rms_std, 4),
            "label": "flat" if dynamics_ratio < 0.2 else
                     "gentle" if dynamics_ratio < 0.4 else
                     "expressive" if dynamics_ratio < 0.7 else "dramatic",
        }

        # Texture (spectral characteristics)
        spectral_centroid = librosa.feature.spectral_centroid(y=pcm_f32, sr=sample_rate)[0]
        sc_mean = float(np.mean(spectral_centroid))
        spectral_flatness = librosa.feature.spectral_flatness(y=pcm_f32)[0]
        sf_mean = float(np.mean(spectral_flatness))
        analysis["texture"] = {
            "spectral_centroid_hz": round(sc_mean, 1),
            "spectral_flatness": round(sf_mean, 4),
            "label": "breathy" if sf_mean > 0.1 else
                     "bright" if sc_mean > 3000 else
                     "dark" if sc_mean < 1500 else "balanced",
        }

        # Tempo estimate (onset rate)
        onset_env = librosa.onset.onset_strength(y=pcm_f32, sr=sample_rate)
        tempo = librosa.feature.tempo(onset_envelope=onset_env, sr=sample_rate)
        tempo_val = float(tempo[0]) if len(tempo) > 0 else 0
        analysis["tempo"] = {
            "estimated_bpm": round(tempo_val, 1),
            "label": "very slow" if tempo_val < 80 else
                     "slow" if tempo_val < 110 else
                     "moderate" if tempo_val < 140 else
                     "brisk" if tempo_val < 180 else "rapid",
        }

        # Resonance (spectral bandwidth)
        bandwidth = librosa.feature.spectral_bandwidth(y=pcm_f32, sr=sample_rate)[0]
        bw_mean = float(np.mean(bandwidth))
        analysis["resonance"] = {
            "bandwidth_hz": round(bw_mean, 1),
            "label": "nasal" if bw_mean < 1200 else
                     "chest" if bw_mean < 2000 else
                     "full-bodied" if bw_mean < 3000 else "head voice",
        }

    except ImportError:
        analysis["_error"] = "librosa not available for audio analysis"
    except Exception as e:
        analysis["_error"] = str(e)

    return analysis


def _compose_parler_prompt_basic(anatomy_specs: dict, general_description: str = "") -> str:
    """Keyword-based fallback for Parler-TTS prompt composition."""
    parts = []
    if general_description:
        parts.append(general_description.rstrip("."))
    element_order = ["pitch", "timbre", "resonance", "texture", "emotion",
                     "tempo", "prosody", "articulation", "dynamics", "accent"]
    for element in element_order:
        spec = anatomy_specs.get(element, "")
        if spec:
            label = VOICE_ANATOMY[element]["label"]
            parts.append(f"{spec} {label.lower()}" if len(spec.split()) <= 3
                         else spec)
    if not parts:
        return "A natural speaking voice"
    return ". ".join(parts) + "."


def compose_parler_prompt(anatomy_specs: dict, general_description: str = "") -> str:
    """Build an optimized Parler-TTS prompt using Gemini AI."""
    if not anatomy_specs and not general_description:
        return "A natural speaking voice"

    result = _gemini_text(f"""Write a Parler-TTS voice description prompt. Parler-TTS generates speech from text descriptions of voices.

User's intent: "{general_description}"
Voice anatomy specs: {json.dumps(anatomy_specs) if anatomy_specs else "none specified"}

Write a single natural English paragraph (2-4 sentences) that describes this voice for Parler-TTS.
Focus on: pitch register, timbre/tonal color, texture, speaking pace, emotional tone, and recording quality.
Use concrete terms Parler-TTS understands well, like: "deep voice", "warm tone", "clear enunciation",
"slow speaking pace", "expressive intonation", "recorded in a studio", "very close sounding".
Do NOT use quotes, special characters, or markdown. Just plain descriptive text.
Do NOT mention any real person by name — only describe vocal qualities.""")

    if result and len(result) > 20 and not result.startswith("{"):
        # Clean up any markdown or quotes
        prompt = result.strip().strip('"').strip("'")
        print(f"  [voice-designer] Gemini Parler prompt: '{prompt[:120]}...'")
        return prompt

    return _compose_parler_prompt_basic(anatomy_specs, general_description)


def compose_voice(references: list[dict], anatomy_specs: dict,
                  general_description: str, preview_text: str,
                  max_attempts: int = 3, min_mos: float = 2.5) -> dict:
    """Compose a voice from multiple references + anatomy specs.

    Each reference in `references` is:
        { "embedding": [...], "weight": 0.5, "label": "..." }
    anatomy_specs maps element name -> description string.
    """
    # Step 1: Decompose general description into anatomy if no explicit specs given
    auto_decomposition = decompose_description(general_description) if general_description else {}
    # Merge: explicit specs override auto-decomposition
    merged_specs = {}
    for element in VOICE_ANATOMY:
        if element in anatomy_specs and anatomy_specs[element]:
            merged_specs[element] = anatomy_specs[element]
        elif element in auto_decomposition:
            merged_specs[element] = ", ".join(auto_decomposition[element])

    # Step 2: Build Parler-TTS prompt from merged anatomy
    prompt = compose_parler_prompt(merged_specs, general_description)
    print(f"  [voice-designer] Composed prompt: '{prompt[:120]}...'")

    # Step 3: Blend reference embeddings if multiple provided
    blended_embedding = None
    blend_info = None
    valid_refs = [r for r in references if r.get("embedding")]
    if valid_refs:
        embeddings = [r["embedding"] for r in valid_refs]
        weights = [r.get("weight", 1.0) for r in valid_refs]
        if len(embeddings) == 1:
            blended_embedding = embeddings[0]
            w_norm = [1.0]
        else:
            blend_result = blend_embeddings(embeddings, weights)
            if blend_result["success"]:
                blended_embedding = blend_result["embedding"]
                w_norm = blend_result["weights_normalized"]
            else:
                print(f"  [voice-designer] Blend failed: {blend_result.get('error')}")
                w_norm = weights
        blend_info = {
            "num_references": len(valid_refs),
            "labels": [r.get("label", "unnamed") for r in valid_refs],
            "weights_normalized": w_norm,
        }

    # Step 4: Generate with quality loop
    result = design_voice_smart(prompt, preview_text, max_attempts, min_mos)

    # Step 5: Attach composition metadata
    result["composition"] = {
        "prompt": prompt,
        "anatomy_specs": merged_specs,
        "auto_decomposition": auto_decomposition,
        "blend": blend_info,
    }
    if blended_embedding:
        result["blended_embedding"] = blended_embedding
        result["blended_embedding_dimensions"] = len(blended_embedding)

    return result


def suggest_description_from_references(
    reference_analyses: list[dict],
    labels: list[str],
    mode: str = "commonalities",
) -> dict:
    """Analyze multiple voice reference analyses and suggest a description.
    Uses Gemini AI for intelligent synthesis, with algorithmic fallback."""
    if not reference_analyses:
        return {"success": False, "error": "No reference analyses provided"}

    # Try Gemini for intelligent synthesis
    gemini_result = _gemini_json(f"""Analyze these voice reference audio analyses and create a unified voice description.

References and their measured acoustic properties:
{json.dumps([{"label": labels[i] if i < len(labels) else f"Reference {i+1}", "analysis": a}
             for i, a in enumerate(reference_analyses)], indent=2)}

Mode: "{mode}"
- If "commonalities": focus on what these voices share in common
- If "additive": combine the best/unique qualities from each voice

Return JSON with:
- "description": a natural 2-3 sentence voice description for Parler-TTS that captures the {mode} of these references
- "anatomy": object mapping voice elements (timbre, pitch, resonance, texture, prosody, tempo, emotion, articulation, dynamics, accent) to descriptive terms. Only include relevant elements.
- "explanation": 1 sentence explaining the synthesis strategy
- "per_reference_notes": array of brief notes about what each reference contributes""")

    if gemini_result and gemini_result.get("description"):
        print(f"  [voice-designer] Gemini palette suggestion: '{gemini_result['description'][:100]}...'")
        return {
            "success": True,
            "description": gemini_result["description"],
            "anatomy": gemini_result.get("anatomy", {}),
            "mode": mode,
            "explanation": gemini_result.get("explanation", "AI-synthesized from reference analyses"),
            "per_reference": [
                {"label": labels[i] if i < len(labels) else f"Reference {i+1}",
                 "analysis": a,
                 "note": gemini_result.get("per_reference_notes", [""])[i]
                         if i < len(gemini_result.get("per_reference_notes", [])) else ""}
                for i, a in enumerate(reference_analyses)
            ],
            "ai_powered": True,
        }

    # Fallback: algorithmic approach
    elements_data = {}
    for analysis in reference_analyses:
        for element in ["pitch", "dynamics", "texture", "tempo", "resonance"]:
            data = analysis.get(element, {})
            label = data.get("label", "")
            if label:
                elements_data.setdefault(element, []).append(label)

    suggestion = {}
    if mode == "commonalities":
        threshold = max(1, len(reference_analyses) // 2)
        for element, labels_list in elements_data.items():
            from collections import Counter
            counts = Counter(labels_list)
            common = [val for val, count in counts.items() if count >= threshold]
            suggestion[element] = common[0] if common else counts.most_common(1)[0][0]
        desc_parts = []
        for el, tmpl in [("pitch", "a {} voice"), ("texture", "{} texture"),
                          ("dynamics", "{} dynamics"), ("tempo", "{} pacing"),
                          ("resonance", "{} resonance")]:
            if el in suggestion:
                desc_parts.append(tmpl.format(suggestion[el]))
        description = "A voice with " + ", ".join(desc_parts) if desc_parts else "A natural speaking voice"
        explanation = "Based on shared characteristics across all references"
    else:
        for element in ["pitch", "dynamics", "texture", "tempo", "resonance"]:
            all_vals = elements_data.get(element, [])
            if all_vals:
                unique = list(dict.fromkeys(all_vals))
                suggestion[element] = " blending ".join(unique) if len(unique) > 1 else unique[0]
        desc_parts = []
        for el, tmpl in [("pitch", "{} pitch"), ("texture", "{} texture"),
                          ("dynamics", "{} dynamics"), ("tempo", "{} pace"),
                          ("resonance", "{} resonance")]:
            if el in suggestion:
                desc_parts.append(tmpl.format(suggestion[el]))
        description = "A voice combining " + ", ".join(desc_parts) if desc_parts else "A natural speaking voice"
        explanation = "Combining distinct qualities from each reference"

    return {
        "success": True,
        "description": description,
        "anatomy": suggestion,
        "mode": mode,
        "explanation": explanation,
        "per_reference": [
            {"label": labels[i] if i < len(labels) else f"Reference {i+1}", "analysis": a}
            for i, a in enumerate(reference_analyses)
        ],
    }


def interpret_voice_request(user_input: str) -> dict:
    """Use Gemini to interpret a freeform voice creation request.
    Handles natural language like 'give me a voice like honey dripping over warm bread'
    or 'make me sound like that guy from the Allstate commercials'."""
    result = _gemini_json(f"""Interpret this voice creation request and extract structured information.

User request: "{user_input}"

Return JSON with:
- "interpretation": 1-2 sentence plain English explanation of what voice the user wants
- "identified_references": array of real people/characters whose voices are being referenced (if any).
  Each: {{"name": "...", "relevance": "why this person is relevant"}}
- "voice_anatomy": object mapping voice elements to descriptive terms:
  - "timbre": tonal color (warm/bright/dark/rich/metallic/velvety/etc)
  - "pitch": register (deep bass/low baritone/mid tenor/alto/high soprano)
  - "resonance": projection (chest/nasal/head voice/full-bodied/booming)
  - "texture": surface quality (smooth/raspy/breathy/gravelly/clear/husky)
  - "prosody": melodic contour (monotone/melodic/dramatic/flowing/sing-song)
  - "tempo": speed (very slow/slow/moderate/brisk/rapid)
  - "emotion": affect (warm/authoritative/playful/intimate/energetic)
  - "articulation": precision (precise/casual/crisp/natural)
  - "dynamics": volume (gentle/punchy/expressive/whispered/projected)
  - "accent": dialect (neutral American/British RP/etc)
  Only include elements that are clearly implied by the request.
- "parler_prompt": a ready-to-use Parler-TTS description prompt (2-4 sentences, no real names, just voice qualities)
- "search_queries": if the user references a real person, 3-4 YouTube search queries to find their voice clips. Otherwise empty array.
- "confidence": float 0-1 indicating how confident you are in the interpretation""")

    if result and result.get("interpretation"):
        print(f"  [voice-designer] Gemini interpreted: '{result['interpretation']}'")
        return {"success": True, **result}

    return {
        "success": False,
        "error": "Could not interpret the voice request. Try being more specific about the voice qualities you want.",
    }


# Clone-ready sample sentences — varied phonetic content for maximum coverage
CLONE_SENTENCES = [
    "The quick brown fox jumps over the lazy dog near the riverbank.",
    "She sells seashells by the seashore every summer morning.",
    "How vexingly quick daft zebras jump through the foggy landscape.",
    "Pack my box with five dozen jugs of liquid wax for the gallery.",
    "The wizard quickly jinxed the gnomes before they could vanish.",
    "Bright vixens jump and dozy fowl quack in the misty meadow.",
    "A journey of a thousand miles begins with a single step forward.",
    "Every good boy does fine when practicing musical scales daily.",
    "Just keep examining every low bid quoted for zinc etchings carefully.",
    "Crazy Frederick bought many very exquisite opal jewels from the market.",
]


def generate_clone_sample(description: str, duration_target_s: float = 15.0,
                          anatomy_specs: dict | None = None) -> dict:
    """Generate a long audio sample for voice cloning in a single consistent voice.

    Generates all text in one model call so Parler-TTS uses the same voice
    throughout. Chatterbox/XTTS work best with 5-15 seconds of clear speech.
    """
    prompt = description
    if anatomy_specs:
        prompt = compose_parler_prompt(anatomy_specs, description)

    model, tokenizer = _get_parler()
    if model == "unavailable" or model is None:
        return {"success": False, "error": "Parler-TTS not available"}

    import torch

    sample_rate = int(model.config.sampling_rate)

    # Estimate ~3-4 seconds per sentence. Pick enough sentences to reach target.
    sents_needed = max(2, int(duration_target_s / 3.5) + 1)
    sents_needed = min(sents_needed, len(CLONE_SENTENCES))
    combined_text = " ".join(CLONE_SENTENCES[:sents_needed])

    print(f"  [voice-designer] Clone sample: generating {sents_needed} sentences "
          f"in a single pass (~{duration_target_s}s target)")
    t0 = time.time()

    try:
        input_ids = tokenizer(prompt, return_tensors="pt").input_ids
        prompt_ids = tokenizer(combined_text, return_tensors="pt").input_ids
        if _device != "cpu":
            input_ids = input_ids.to(_device)
            prompt_ids = prompt_ids.to(_device)

        # Set a fixed seed so the voice is deterministic for a given description
        torch.manual_seed(hash(prompt) % (2**32))

        with torch.no_grad():
            generation = model.generate(
                input_ids=input_ids,
                prompt_input_ids=prompt_ids,
            )

        audio_np = generation.cpu().numpy().squeeze()
        if audio_np.ndim > 1:
            audio_np = audio_np[0]
        audio_np = audio_np.astype(np.float32)

        # Normalize
        peak = np.max(np.abs(audio_np))
        if peak > 0:
            audio_np = audio_np / peak * 0.95

        duration_s = len(audio_np) / sample_rate
        elapsed = time.time() - t0

        print(f"  [voice-designer] Clone sample: {duration_s:.1f}s generated in {elapsed:.1f}s")

        # If way too short, do a second pass with more sentences
        if duration_s < duration_target_s * 0.5 and sents_needed < len(CLONE_SENTENCES):
            print(f"  [voice-designer] Clone sample: too short, extending...")
            extra_text = " ".join(CLONE_SENTENCES[sents_needed:])
            extra_ids = tokenizer(extra_text, return_tensors="pt").input_ids
            if _device != "cpu":
                extra_ids = extra_ids.to(_device)

            # Use same seed for consistent voice
            torch.manual_seed(hash(prompt) % (2**32))
            with torch.no_grad():
                extra_gen = model.generate(
                    input_ids=input_ids,
                    prompt_input_ids=extra_ids,
                )
            extra_np = extra_gen.cpu().numpy().squeeze()
            if extra_np.ndim > 1:
                extra_np = extra_np[0]
            extra_np = extra_np.astype(np.float32)
            peak = np.max(np.abs(extra_np))
            if peak > 0:
                extra_np = extra_np / peak * 0.95

            # Join with a brief silence
            gap = np.zeros(int(sample_rate * 0.3), dtype=np.float32)
            audio_np = np.concatenate([audio_np, gap, extra_np])
            duration_s = len(audio_np) / sample_rate
            sents_needed = len(CLONE_SENTENCES)

            # Re-normalize combined
            peak = np.max(np.abs(audio_np))
            if peak > 0:
                audio_np = audio_np / peak * 0.95

        audio_b64 = base64.b64encode(audio_np.tobytes()).decode("ascii")

        return {
            "success": True,
            "audio_base64": audio_b64,
            "sample_rate": sample_rate,
            "duration_s": round(duration_s, 2),
            "duration_ms": round(duration_s * 1000, 1),
            "num_sentences": sents_needed,
            "sentences": CLONE_SENTENCES[:sents_needed],
            "prompt": prompt,
            "clone_ready": duration_s >= 5.0,
            "recommended_engines": ["chatterbox", "coqui-xtts"],
        }

    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": str(e)}


# ── Quality self-analysis (calls quality_server on 21748) ────────────

QUALITY_SERVER = "http://127.0.0.1:21748"


def _analyze_quality(pcm_f32: np.ndarray, sample_rate: int, transcript: str) -> dict | None:
    """Send audio to the quality server for ASR + MOS + prosody analysis."""
    import http.client

    try:
        pcm_bytes = pcm_f32.astype(np.float32).tobytes()
        conn = http.client.HTTPConnection("127.0.0.1", 21748, timeout=60)
        headers = {
            "Content-Type": "application/octet-stream",
            "Content-Length": str(len(pcm_bytes)),
            "X-Sample-Rate": str(sample_rate),
            "X-Channels": "1",
            "X-Transcript": transcript,
            "X-Request-Id": f"designer-{uuid.uuid4().hex[:8]}",
            "X-Analyzers": "asr,mos,prosody,signal",
        }
        conn.request("POST", "/analyze", body=pcm_bytes, headers=headers)
        resp = conn.getresponse()
        body = resp.read().decode()
        conn.close()
        if resp.status == 200:
            return json.loads(body)
        print(f"  [voice-designer] Quality analysis returned {resp.status}: {body[:200]}")
        return None
    except Exception as e:
        print(f"  [voice-designer] Quality analysis failed: {e}")
        return None


def design_voice_smart(description: str, preview_text: str,
                       max_attempts: int = 3, min_mos: float = 2.5) -> dict:
    """Generate a voice with self-analysis. Retries if quality is poor."""
    best_result = None
    best_mos = -1.0
    attempts = []

    for attempt in range(1, max_attempts + 1):
        print(f"  [voice-designer] Smart design attempt {attempt}/{max_attempts}")
        result = design_voice(description, preview_text)
        if not result["success"]:
            attempts.append({"attempt": attempt, "error": result.get("error")})
            continue

        # Decode audio for quality analysis
        pcm_bytes = base64.b64decode(result["audio_base64"])
        pcm_f32 = np.frombuffer(pcm_bytes, dtype=np.float32)
        sr = result["sample_rate"]

        quality = _analyze_quality(pcm_f32, sr, preview_text)

        attempt_info = {
            "attempt": attempt,
            "duration_ms": result["duration_ms"],
        }

        if quality:
            mos_data = quality.get("mos", {})
            asr_data = quality.get("asr", {})
            signal_data = quality.get("signal", {})
            overall_data = quality.get("overall", {})

            mos = mos_data.get("mos") if isinstance(mos_data, dict) else None
            wer = asr_data.get("wer") if isinstance(asr_data, dict) else None
            asr_text = asr_data.get("hypothesis", "") if isinstance(asr_data, dict) else ""
            snr = signal_data.get("snr_db") if isinstance(signal_data, dict) else None

            attempt_info.update({
                "mos": round(mos, 2) if mos is not None else None,
                "wer": round(wer, 3) if wer is not None else None,
                "asr_transcript": asr_text,
                "snr_db": round(snr, 1) if snr is not None else None,
                "artifacts": signal_data.get("artifacts", []) if isinstance(signal_data, dict) else [],
            })

            if mos is not None and mos > best_mos:
                best_mos = mos
                best_result = result
                best_result["quality"] = quality

            mos_str = f"{mos:.2f}" if mos is not None else "N/A"
            wer_str = f"{wer:.3f}" if wer is not None else "N/A"
            snr_str = f"{snr:.1f}dB" if snr is not None else "N/A"
            print(f"  [voice-designer]   Attempt {attempt}: MOS={mos_str}, WER={wer_str}, SNR={snr_str}")

            if mos is not None and mos >= min_mos and (wer is None or wer < 0.3):
                print(f"  [voice-designer]   Quality meets threshold, using attempt {attempt}")
                break
        else:
            # No quality server — use this attempt
            if best_result is None:
                best_result = result
            attempt_info["quality_unavailable"] = True

        attempts.append(attempt_info)

    if best_result is None:
        return {"success": False, "error": "All attempts failed", "attempts": attempts}

    best_result["attempts"] = attempts
    best_result["total_attempts"] = len(attempts)
    return best_result


# ── Voice reference search (YouTube / web) ───────────────────────────

_reference_cache_dir = None


def _get_reference_cache_dir() -> Path:
    global _reference_cache_dir
    if _reference_cache_dir is None:
        _reference_cache_dir = Path(__file__).parent / "voice_references"
        _reference_cache_dir.mkdir(exist_ok=True)
    return _reference_cache_dir


def _classify_query_keywords(query: str) -> dict:
    """Keyword-based fallback for query classification."""
    q_lower = query.lower()

    performance_keywords = [" as ", " in ", "'s performance", " playing ", " portrayal"]
    is_performance = any(k in q_lower for k in performance_keywords)

    sfx_keywords = ["beep", "boop", "roar", "growl", "sound effect", "sfx",
                     "r2d2", "r2-d2", "robot voice", "alien voice", "monster",
                     "creature", "animal", "siren", "engine", "machine"]
    is_sfx = any(k in q_lower for k in sfx_keywords)

    quality_keywords = ["whisper", "raspy", "deep voice", "breathy", "husky",
                        "gravelly", "silky", "booming", "nasal", "falsetto",
                        "baritone", "soprano", "alto", "bass voice",
                        "asmr", "soundtrack", "score", "ambient"]
    is_quality = any(k in q_lower for k in quality_keywords)

    return {
        "is_performance": is_performance,
        "is_sfx": is_sfx,
        "is_quality": is_quality,
        "is_person": not is_sfx and not is_quality,
    }


def _classify_query(query: str) -> dict:
    """Classify a voice search query using Gemini AI, with keyword fallback."""
    result = _gemini_json(f"""Classify this voice/sound search query into exactly one category.

Query: "{query}"

Return JSON with these boolean fields:
- "is_person": true if the query refers to a specific real person (actor, singer, narrator, public figure) by name
- "is_performance": true if it refers to a specific character portrayal or role (e.g. "Mark Hamill as Joker", "Vader in Empire Strikes Back")
- "is_sfx": true if it refers to a non-human sound effect, animal sound, machine noise, or robot/alien voice
- "is_quality": true if it describes vocal qualities, techniques, or styles without naming a specific person (e.g. "deep raspy voice", "breathy whisper", "ASMR")

Set exactly one to true. If the query names a real person without specifying a role, set is_person=true.
If it describes a voice quality/style, set is_quality=true.
Also include:
- "resolved_name": the full real name of the person if is_person or is_performance is true, otherwise null
- "resolved_character": the character/role name if is_performance is true, otherwise null
- "description": a brief 1-sentence description of what the user is looking for""")

    if result and any(result.get(k) for k in ["is_person", "is_performance", "is_sfx", "is_quality"]):
        # Ensure exactly-one semantics and fill in defaults
        result.setdefault("is_person", False)
        result.setdefault("is_performance", False)
        result.setdefault("is_sfx", False)
        result.setdefault("is_quality", False)
        print(f"  [voice-designer] Gemini classified '{query}': {result}")
        return result

    return _classify_query_keywords(query)


def _build_search_queries_keywords(query: str, classification: dict) -> list[str]:
    """Keyword-based fallback for building search queries."""
    queries = []
    if classification["is_performance"]:
        queries.extend([
            f'"{query}" scene clip',
            f'"{query}" monologue',
            f'"{query}" best moments',
            f'"{query}" voice',
        ])
    elif classification["is_sfx"]:
        queries.extend([
            f"{query}",
            f"{query} sound effect",
            f"{query} audio clip",
            f"{query} compilation",
        ])
    elif classification["is_quality"]:
        queries.extend([
            f"{query}",
            f"{query} audio",
            f"{query} example",
            f"{query} sample",
        ])
    else:
        queries.extend([
            f'"{query}" monologue scene',
            f'"{query}" movie clip scene',
            f'"{query}" best performance',
            f'"{query}" speech',
            f'"{query}" voice acting',
            f'"{query}" interview',
        ])
    return queries


def _build_search_queries(query: str, classification: dict) -> list[str]:
    """Build targeted YouTube search queries using Gemini AI."""
    resolved = classification.get("resolved_name") or query
    character = classification.get("resolved_character")

    result = _gemini_json(f"""Generate YouTube search queries to find clean audio clips of a specific voice.

Target: "{query}"
{"Resolved name: " + resolved if resolved != query else ""}
{"Character/role: " + character if character else ""}
Category: {"specific performance/role" if classification.get("is_performance") else "sound effect" if classification.get("is_sfx") else "vocal quality/style" if classification.get("is_quality") else "specific person"}

Generate 4-6 YouTube search queries optimized to find:
- Solo voice clips with minimal background noise/music
- Monologues, speeches, narration, or audiobook readings (for people)
- Clean isolated audio samples (for sound effects)
- Example demonstrations (for vocal qualities)

For real people, ALWAYS quote their full name in the search query.
Prefer movie scenes, monologues, narration, and solo performances over interviews or panel discussions.

Return JSON: {{"queries": ["query1", "query2", ...]}}""")

    if result and result.get("queries"):
        queries = result["queries"][:8]
        print(f"  [voice-designer] Gemini search queries: {queries}")
        return queries

    return _build_search_queries_keywords(query, classification)


# Title keywords that indicate clean solo-voice clips (higher = better)
_TITLE_BOOST_KEYWORDS = [
    "monologue", "solo", "narrat", "speech", "audiobook", "reading",
    "voice acting", "voice lines", "scene", "performance", "iconic",
    "best moments", "compilation", "movie clip", "film clip",
]
# Title keywords that indicate noisy/multi-speaker clips (lower = worse)
_TITLE_PENALTY_KEYWORDS = [
    "interview", "talk show", "podcast", "panel", "q&a", "q & a",
    "red carpet", "press conference", "behind the scenes", "reaction",
    "review", "commentary", "reacts", "responds", "debate", "discussion",
    "with ", "and ", "vs ", "versus",
]


def _extract_name_parts(query: str) -> list[str]:
    """Extract likely name parts from a query for matching against titles.
    E.g. 'Jaimie Alexander' -> ['jaimie', 'alexander', 'jaimie alexander']
    E.g. 'Morgan Freeman narration' -> ['morgan', 'freeman', 'morgan freeman']
    """
    # Remove common non-name suffixes
    q = query.lower().strip()
    for strip in ["narration", "narrating", "voice", "speaking", "acting",
                   "monologue", "speech", "scene", "movie", "film", "clip",
                   "interview", "audiobook", "reading"]:
        q = q.replace(strip, "")
    q = q.strip()
    parts = [p for p in q.split() if len(p) >= 2]
    result = list(parts)
    if len(parts) >= 2:
        result.append(" ".join(parts))  # full name
    return result


def _score_candidate_title(title: str, classification: dict,
                           query: str = "") -> float:
    """Score a candidate by title to prefer solo-voice clips with the right person."""
    t = title.lower()
    score = 0.0

    # ── Name relevance (most important for person queries) ──
    if classification.get("is_person") or classification.get("is_performance"):
        name_parts = _extract_name_parts(query)
        if name_parts:
            # Check how many name parts appear in the title
            matches = sum(1 for p in name_parts if p in t)
            if matches == 0:
                # Title doesn't mention the person at all — heavy penalty
                score -= 10.0
            else:
                # Bonus proportional to match quality
                full_name = name_parts[-1] if len(name_parts) >= 3 else ""
                if full_name and full_name in t:
                    score += 5.0  # Full name match
                else:
                    score += 2.0 * matches  # Partial name match

    # ── Content type scoring ──
    for kw in _TITLE_BOOST_KEYWORDS:
        if kw in t:
            score += 1.0
    for kw in _TITLE_PENALTY_KEYWORDS:
        if kw in t:
            score -= 1.5
    if classification.get("is_person") and any(w in t for w in ["movie", "film", "scene"]):
        score += 0.5
    return score


def _search_image(query: str) -> str | None:
    """Find a representative image and return as data URI (avoids CORS issues).
    Uses a background thread with a hard 4-second timeout to avoid hanging."""
    import concurrent.futures

    def _do_search():
        from ddgs import DDGS
        import urllib.request
        with DDGS() as ddgs:
            for r in ddgs.images(query, max_results=3):
                # Prefer thumbnail (smaller, faster) then fall back to full image
                url = r.get("thumbnail", "") or r.get("image", "")
                if not url or not url.startswith("http"):
                    continue
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                    with urllib.request.urlopen(req, timeout=3) as resp:
                        ct = resp.headers.get("Content-Type", "image/jpeg")
                        data = resp.read(200_000)  # max 200KB
                        if len(data) < 500:
                            continue
                        b64 = base64.b64encode(data).decode("ascii")
                        return f"data:{ct};base64,{b64}"
                except Exception:
                    continue
        return None

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_do_search)
            return future.result(timeout=4)
    except (concurrent.futures.TimeoutError, Exception) as e:
        print(f"  [voice-designer] Image search timed out or failed: {e}")
        return None


def identify_subject(query: str) -> dict:
    """Step 1: Identify who or what the user is searching for.
    Uses a single Gemini call for both classification and identification (faster).
    Falls back to DuckDuckGo if Gemini is unavailable."""
    import concurrent.futures

    # Single combined Gemini call: classify + identify in one shot
    gemini_result = _gemini_json(f"""Identify and classify this voice/sound search query. Provide detailed information for voice cloning purposes.

Query: "{query}"

Return JSON with:
- "classification": object with booleans "is_person", "is_performance", "is_sfx", "is_quality" (exactly one true), plus "resolved_name" (full real name if person/performance, else null), "resolved_character" (character name if performance, else null)
- "full_name": the resolved full real name (for people) or precise term (for sounds/qualities)
- "summary": a 2-3 sentence description focusing on voice characteristics and notable vocal performances
- "known_for": array of 3-5 specific works, roles, or performances
- "voice_description": 1-2 sentence voice description using anatomy terms (timbre, pitch, resonance, texture, prosody)
- "suggested_clip_queries": array of 4-6 YouTube search queries for clean solo audio clips. Quote real names.
- "suggested_samples": array of 3-5 objects with "title" and "why" (specific real moments yielding clean voice samples)
- "disambiguation": if ambiguous, array of objects with "name" and "description". Otherwise null.
- "alternatives": array of 2-3 objects with "name" and "reason" for similar-sounding voices
- "image_search_query": search query for a recognizable photo (e.g. "Morgan Freeman actor portrait")""")

    if gemini_result and gemini_result.get("full_name"):
        full_name = gemini_result["full_name"]
        print(f"  [voice-designer] Gemini identified '{query}' as: {full_name}")

        classification = gemini_result.get("classification", {})
        if not isinstance(classification, dict):
            classification = {}
        classification.setdefault("is_person", True)
        classification.setdefault("is_performance", False)
        classification.setdefault("is_sfx", False)
        classification.setdefault("is_quality", False)
        classification.setdefault("resolved_name", full_name)

        # Fetch image in parallel (non-blocking, capped at 4s)
        img_query = gemini_result.get("image_search_query") or f"{full_name} portrait"
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            img_future = pool.submit(_search_image, img_query)
            try:
                image_url = img_future.result(timeout=4)
            except Exception:
                image_url = None

        return {
            "success": True,
            "query": query,
            "classification": classification,
            "name": full_name,
            "summary": gemini_result.get("summary", ""),
            "known_for": gemini_result.get("known_for", []),
            "voice_description": gemini_result.get("voice_description", ""),
            "suggested_clip_queries": gemini_result.get("suggested_clip_queries", []),
            "suggested_samples": gemini_result.get("suggested_samples", []),
            "disambiguation": gemini_result.get("disambiguation"),
            "alternatives": gemini_result.get("alternatives", []),
            "image_url": image_url,
            "sources": [],
            "ai_powered": True,
        }

    # Fallback: DuckDuckGo search
    try:
        from ddgs import DDGS
    except ImportError:
        return {"success": False, "error": "Neither Gemini nor duckduckgo-search available",
                "classification": classification}

    if classification["is_sfx"]:
        search_queries = [f"{query}", f"{query} sound"]
    elif classification["is_quality"]:
        search_queries = [f"{query} vocal technique"]
    elif classification["is_performance"]:
        search_queries = [f'"{query}"', f"{query} actor role"]
    else:
        search_queries = [
            f'"{query}" actor OR singer OR narrator OR voice',
            f'"{query}" famous',
        ]

    candidates = []
    seen_titles = set()
    try:
        with DDGS() as ddgs:
            for sq in search_queries:
                for r in ddgs.text(sq, max_results=5):
                    title = r.get("title", "").strip()
                    body = r.get("body", "").strip()
                    href = r.get("href", "")
                    if not title or title in seen_titles:
                        continue
                    seen_titles.add(title)
                    candidates.append({"title": title, "description": body, "url": href})
                if len(candidates) >= 8:
                    break
    except Exception as e:
        print(f"  [voice-designer] Identify search error: {e}")

    if not candidates:
        return {"success": False, "error": f"No information found for '{query}'",
                "classification": classification}

    name_parts = _extract_name_parts(query)
    relevant = [c for c in candidates if any(p in c["title"].lower() for p in name_parts)]
    summary_parts = [c["description"] for c in (relevant or candidates)[:4] if c["description"]]
    summary = " ".join(summary_parts)
    if len(summary) > 600:
        summary = summary[:597] + "..."

    known_for = []
    summary_lower = summary.lower()
    for indicator in ["known for", "starred in", "appeared in", "famous for",
                      "role in", "voice of", "narrated", "performed in",
                      "cast in", "played", "portrays", "portrayed"]:
        idx = summary_lower.find(indicator)
        if idx >= 0:
            snippet = summary[idx:idx + 120]
            for end_char in [". ", ".", ",", ";", "\n"]:
                end = snippet.find(end_char, 20)
                if end > 0:
                    snippet = snippet[:end]
                    break
            if snippet not in known_for:
                known_for.append(snippet)

    return {
        "success": True,
        "query": query,
        "classification": classification,
        "summary": summary,
        "known_for": known_for[:5],
        "sources": (relevant or candidates)[:5],
        "suggested_clip_queries": _build_clip_queries(query, classification, known_for),
    }


def _build_clip_queries(query: str, classification: dict,
                        known_for: list[str]) -> list[str]:
    """Build targeted clip search queries using Gemini AI."""
    resolved = classification.get("resolved_name") or query
    character = classification.get("resolved_character")

    known_for_str = ", ".join(known_for[:5]) if known_for else "unknown"

    result = _gemini_json(f"""Generate YouTube search queries to find clean, solo voice audio clips.

Target: "{query}"
{"Resolved name: " + resolved if resolved != query else ""}
{"Character/role: " + character if character else ""}
Known for: {known_for_str}
Category: {"specific performance/role" if classification.get("is_performance") else "sound effect" if classification.get("is_sfx") else "vocal quality/style" if classification.get("is_quality") else "specific person"}

Generate 4-8 highly specific YouTube search queries. For each query:
- Target scenes/clips where this person speaks ALONE (monologues, narration, speeches, audiobook readings)
- Reference specific movies, shows, or works they're known for when possible
- ALWAYS quote real names in the search query
- Avoid queries that would return interviews, podcasts, or multi-person discussions
- For sound effects, target isolated/clean samples
- For vocal qualities, target demonstration or example clips

Return JSON: {{"queries": ["query1", "query2", ...]}}""")

    if result and result.get("queries"):
        queries = result["queries"][:8]
        print(f"  [voice-designer] Gemini clip queries: {queries}")
        return queries

    # Fallback: keyword-based
    queries = []
    if classification["is_sfx"]:
        queries = [f"{query} sound effect clean", f"{query} audio isolated"]
    elif classification["is_quality"]:
        queries = [f"{query} example audio", f"{query} vocal sample"]
    elif classification["is_performance"]:
        queries = [f'"{query}" scene', f'"{query}" monologue clip']
    else:
        name = query.strip()
        queries = [
            f'"{name}" monologue movie scene',
            f'"{name}" speech scene clip',
            f'"{name}" narration audiobook',
            f'"{name}" solo scene',
        ]
        for kf in known_for[:3]:
            kf_clean = kf.strip()
            if len(kf_clean) > 10:
                queries.append(f'"{name}" {kf_clean[:40]} scene')
    return queries[:8]


def _web_research_voice(query: str, classification: dict) -> tuple[list[dict], str]:
    """Research a voice/sound using Gemini AI for description + DuckDuckGo for video URLs.
    Returns (video_results, description_text)."""

    # Use Gemini for the voice description (much richer than web snippets)
    resolved = classification.get("resolved_name") or query
    description = _gemini_text(f"""Describe the voice of "{resolved}" in detail for a voice cloning/design system.

Cover these aspects:
- Pitch range (bass/baritone/tenor/alto/soprano)
- Timbre and tonal color (warm/bright/dark/metallic/rich)
- Texture (smooth/raspy/breathy/gravelly/clear)
- Resonance (chest/nasal/head voice/full-bodied)
- Typical speaking tempo and prosody
- Emotional qualities and delivery style
- Any distinctive vocal characteristics or mannerisms

If this is a vocal quality/technique rather than a person, describe what it sounds like and how it's produced.
If this is a sound effect, describe its acoustic properties.

Write 3-5 sentences of plain descriptive text. No markdown, no lists, no headers.""")

    if description:
        print(f"  [voice-designer] Gemini voice description: '{description[:120]}...'")
    else:
        description = ""

    # Use DuckDuckGo for video URL discovery (Gemini can't browse)
    results = []
    try:
        from ddgs import DDGS
    except ImportError:
        return results, description

    video_queries = _build_search_queries(query, classification)
    name_parts = _extract_name_parts(query) if classification.get("is_person") else []

    print(f"  [voice-designer] Web video research for: '{query}'")
    try:
        with DDGS() as ddgs:
            for vq in video_queries[:3]:
                try:
                    for r in ddgs.videos(vq, max_results=5):
                        url = r.get("content", "")
                        title = r.get("title", "")
                        if "youtube.com" not in url and "youtu.be" not in url:
                            continue
                        if name_parts:
                            t_lower = title.lower()
                            if not any(p in t_lower for p in name_parts):
                                print(f"  [voice-designer]   Skipped (no name match): '{title[:50]}'")
                                continue
                        results.append({
                            "url": url,
                            "title": title,
                            "source": "web_research",
                        })
                        print(f"  [voice-designer]   Video: '{title[:50]}' — {url}")
                except Exception:
                    pass
    except Exception as e:
        print(f"  [voice-designer]   Web research error: {e}")

    return results, description.strip()


def _download_clip(video_id: str, url: str, duration: int | None,
                   cache_dir: Path, clip_seconds: int = 15) -> str | None:
    """Download a clip from a YouTube video. Returns error string or None."""
    import yt_dlp

    audio_path = cache_dir / f"{video_id}.wav"
    if audio_path.exists():
        return None  # already cached

    clip_start = 30
    if duration:
        clip_start = max(5, int(duration * 0.25))
        clip_end = min(clip_start + clip_seconds, int(duration * 0.75))
        clip_start = max(5, clip_end - clip_seconds)

    dl_opts = {
        "quiet": True,
        "no_warnings": True,
        "format": "bestaudio/best",
        "outtmpl": str(cache_dir / f"{video_id}.%(ext)s"),
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "wav",
            "preferredquality": "0",
        }],
        "postprocessor_args": ["-ac", "1", "-ar", "16000"],
        "socket_timeout": 20,
        "download_ranges": yt_dlp.utils.download_range_func(
            None, [(clip_start, clip_start + clip_seconds)]
        ),
    }
    try:
        with yt_dlp.YoutubeDL(dl_opts) as ydl:
            ydl.download([url])
        print(f"  [voice-designer]   Downloaded {clip_seconds}s clip from {video_id}")
    except Exception as e:
        err_str = str(e)
        if "Maximum number of downloads" not in err_str:
            print(f"  [voice-designer]   Download failed for {video_id}: {e}")
            return err_str
    return None


def _process_candidate(cand: dict, cache_dir: Path) -> dict:
    """Download clip, extract embedding, build result dict with audio preview."""
    video_id = cand["id"]
    title = cand["title"]
    duration = cand.get("duration")
    url = cand["url"]

    print(f"  [voice-designer]   Processing: '{title[:60]}' ({duration or '?'}s) — {video_id}")

    audio_path = cache_dir / f"{video_id}.wav"
    embedding = None
    audio_b64 = None
    download_error = _download_clip(video_id, url, duration, cache_dir)

    isolation_info = None
    if audio_path.exists():
        try:
            import soundfile as sf
            audio_data, sr = sf.read(str(audio_path), dtype="float32")
            if audio_data.ndim > 1:
                audio_data = audio_data.mean(axis=1)

            # Isolate the target speaker (remove interviewer, audience, etc.)
            isolated_audio, isolation_info = isolate_target_speaker(
                audio_data, sr, segment_duration=2.0, similarity_threshold=0.55)

            # Extract embedding from isolated audio only
            emb_result = extract_embedding(isolated_audio, sr)
            if emb_result["success"]:
                embedding = emb_result["embedding"]
                dur_sec = len(isolated_audio) / sr
                print(f"  [voice-designer]   Extracted {emb_result['dimensions']}D "
                      f"embedding from {dur_sec:.1f}s isolated audio")

            # Encode the isolated audio for preview (base64 PCM f32)
            audio_b64 = base64.b64encode(isolated_audio.tobytes()).decode("ascii")
        except Exception as e:
            download_error = f"Processing failed: {e}"
            print(f"  [voice-designer]   Processing failed: {e}")

    return {
        "video_id": video_id,
        "title": title,
        "duration": duration,
        "url": url,
        "source": cand.get("source", "unknown"),
        "has_audio": audio_path.exists(),
        "audio_base64": audio_b64,
        "audio_sample_rate": 16000 if audio_b64 else None,
        "embedding": embedding,
        "embedding_dimensions": len(embedding) if embedding else None,
        "isolation": isolation_info,
        "error": download_error,
    }


def search_voice_references(query: str, max_results: int = 3,
                            max_duration: int = 300,
                            exclude_ids: list[str] | None = None) -> dict:
    """Search for voice/sound samples using web research + YouTube.
    Downloads audio clips and extracts speaker embeddings.
    Supports actors, specific performances, sound effects, and vocal qualities."""
    try:
        import yt_dlp
    except ImportError:
        return {"success": False, "error": "yt-dlp not installed"}

    cache_dir = _get_reference_cache_dir()
    exclude_set = set(exclude_ids or [])

    # Classify query to choose search strategy
    classification = _classify_query(query)
    print(f"  [voice-designer] Query classification: {classification}")

    # Phase 1: Web research
    web_results, web_description = _web_research_voice(query, classification)

    # Phase 2: YouTube search with tailored queries
    yt_search_queries = _build_search_queries(query, classification)
    name_parts = _extract_name_parts(query) if classification.get("is_person") else []

    yt_entries = []
    yt_skipped = 0
    for sq in yt_search_queries:
        try:
            with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                    "extract_flat": True, "default_search": "ytsearch"}) as ydl:
                r = ydl.extract_info(f"ytsearch10:{sq}", download=False)
                for e in (r.get("entries") or []):
                    if not e or e.get("id") in [x.get("id") for x in yt_entries]:
                        continue
                    # For person queries, filter by name presence in title
                    if name_parts:
                        t = (e.get("title") or "").lower()
                        if not any(p in t for p in name_parts):
                            yt_skipped += 1
                            continue
                    yt_entries.append(e)
        except Exception:
            pass
        if len(yt_entries) >= max_results * 4:
            break
    if yt_skipped:
        print(f"  [voice-designer] Filtered out {yt_skipped} YouTube results (name mismatch)")

    print(f"  [voice-designer] Found {len(web_results)} web, {len(yt_entries)} YouTube results")

    # Combine and deduplicate
    candidates = []
    seen_ids = set(exclude_set)

    for wr in web_results:
        url = wr["url"]
        vid = None
        if "v=" in url:
            vid = url.split("v=")[1].split("&")[0]
        elif "youtu.be/" in url:
            vid = url.split("youtu.be/")[1].split("?")[0]
        if vid and vid not in seen_ids:
            seen_ids.add(vid)
            candidates.append({
                "id": vid, "title": wr.get("title", ""), "duration": None,
                "url": f"https://www.youtube.com/watch?v={vid}", "source": "web_research",
            })

    for e in yt_entries:
        vid = e.get("id", "")
        if vid and vid not in seen_ids:
            seen_ids.add(vid)
            candidates.append({
                "id": vid, "title": e.get("title", "Unknown"),
                "duration": e.get("duration"),
                "url": f"https://www.youtube.com/watch?v={vid}", "source": "youtube_search",
            })

    # Sort: combine duration preference with title quality scoring
    def sort_key(c):
        # Duration score (0 = ideal, 1/2 = less ideal)
        d = c.get("duration") or 9999
        if classification["is_sfx"]:
            dur_score = 0 if d <= 30 else (1 if d <= 120 else 2)
        else:
            dur_score = 0 if 30 <= d <= 300 else (1 if d < 30 else 2)
        # Title quality score (higher = better, so negate for ascending sort)
        title_score = -_score_candidate_title(c.get("title", ""), classification, query)
        return (dur_score, title_score)
    candidates.sort(key=sort_key)
    candidates = candidates[:max_results]

    if not candidates:
        return {"success": False, "error": f"No results found for '{query}'",
                "web_description": web_description}

    results = []
    for cand in candidates:
        results.append(_process_candidate(cand, cache_dir))

    successful = [r for r in results if r["embedding"]]
    return {
        "success": len(successful) > 0,
        "query": query,
        "classification": classification,
        "web_description": web_description,
        "results": results,
        "num_found": len(results),
        "num_with_embeddings": len(successful),
    }


# ── HTTP Server ──────────────────────────────────────────────────────

class VoiceDesignerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  [voice-designer] {args[0]}")

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Sample-Rate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._handle_health()
        elif parsed.path == "/list_profiles":
            self._handle_list_profiles()
        elif parsed.path == "/stack_status":
            self._handle_stack_status()
        elif parsed.path == "/model_status":
            self._handle_model_status()
        elif parsed.path == "/voice_anatomy":
            self._handle_voice_anatomy_get()
        elif parsed.path == "/crafting/archetypes":
            self._handle_crafting_archetypes()
        elif parsed.path == "/crafting/axes":
            self._handle_crafting_axes()
        elif parsed.path.startswith("/crafting/session/"):
            self._handle_crafting_get_session()
        else:
            self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        handlers = {
            "/design": self._handle_design,
            "/design_smart": self._handle_design_smart,
            "/design_with_reference": self._handle_design_with_reference,
            "/extract_embedding": self._handle_extract_embedding,
            "/blend": self._handle_blend,
            "/save_profile": self._handle_save_profile,
            "/delete_profile": self._handle_delete_profile,
            "/preload": self._handle_preload,
            "/search_voice": self._handle_search_voice,
            "/search_voice_stream": self._handle_search_voice_stream,
            "/identify": self._handle_identify,
            "/find_clips": self._handle_find_clips,
            "/compose": self._handle_compose,
            "/decompose": self._handle_decompose,
            "/analyze_anatomy": self._handle_analyze_anatomy,
            "/voice_anatomy": self._handle_voice_anatomy,
            "/suggest_from_palette": self._handle_suggest_from_palette,
            "/generate_clone_sample": self._handle_generate_clone_sample,
            "/interpret": self._handle_interpret,
            # ElevenLabs endpoints
            "/elevenlabs/design": self._handle_elevenlabs_design,
            "/elevenlabs/create_voice": self._handle_elevenlabs_create_voice,
            "/elevenlabs/synthesize": self._handle_elevenlabs_synthesize,
            # Voice crafting endpoints
            "/crafting/start": self._handle_crafting_start,
            "/crafting/explore": self._handle_crafting_explore,
            "/crafting/select": self._handle_crafting_select,
            "/crafting/regenerate": self._handle_crafting_regenerate,
            "/crafting/skip": self._handle_crafting_skip,
            "/crafting/back": self._handle_crafting_back,
            "/crafting/finish": self._handle_crafting_finish,
        }
        handler = handlers.get(parsed.path)
        if handler:
            handler()
        else:
            self.send_error(404)

    def _handle_stack_status(self):
        """Check all stack services server-side (no CORS issues)."""
        import socket

        def check_port(port: int) -> bool:
            try:
                s = socket.create_connection(("127.0.0.1", port), timeout=1)
                s.close()
                return True
            except (ConnectionRefusedError, OSError, TimeoutError):
                return False

        def check_http(port: int, path: str = "/health") -> bool:
            try:
                import http.client
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                conn.request("GET", path)
                resp = conn.getresponse()
                conn.close()
                return resp.status == 200
            except Exception:
                return False

        result = {
            "ws": check_port(21740),
            "alignment": check_http(21747),
            "quality": check_http(21748),
            "designer": True,  # we're running
        }
        self._send_json(200, result)

    def _handle_model_status(self):
        """Return loading status for all models."""
        self._send_json(200, {
            "parler": dict(_loading_status["parler"]),
            "encoder": dict(_loading_status["encoder"]),
        })

    def _handle_preload(self):
        """Trigger model loading in a background thread."""
        models = []
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 0:
                body = self.rfile.read(content_length)
                data = json.loads(body)
                models = data.get("models", ["parler", "encoder"])
            else:
                models = ["parler", "encoder"]
        except Exception:
            models = ["parler", "encoder"]

        def _load():
            if "parler" in models:
                _get_parler()
            if "encoder" in models:
                _get_speaker_encoder()

        threading.Thread(target=_load, daemon=True).start()
        self._send_json(200, {"success": True, "loading": models})

    def _handle_health(self):
        parler, _ = _get_parler() if _parler_model is not None else (None, None)
        # Check Gemini status
        gemini_status = "not_configured"
        if _gemini_client is not None and _gemini_client != "unavailable":
            gemini_status = "connected"
        elif _gemini_client == "unavailable":
            gemini_status = "error"
        else:
            # Not yet initialized — try now
            if _init_gemini():
                gemini_status = "connected"
            else:
                gemini_status = "not_configured"

        body = json.dumps({
            "status": "ok",
            "parler_loaded": _parler_model is not None and _parler_model != "unavailable",
            "speaker_encoder_loaded": _speaker_encoder is not None and _speaker_encoder != "unavailable",
            "gemini": gemini_status,
            "gemini_model": _gemini_model_name if gemini_status == "connected" else None,
            "device": _device,
            "num_profiles": len(list(_get_profiles_dir().glob("*.json"))),
            "elevenlabs": elevenlabs_health(),
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_design(self):
        """Create voice from text description using Parler-TTS."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            description = data.get("description", "")
            preview_text = data.get("preview_text", "Hello, this is a preview of the designed voice.")

            if not description:
                self._send_json(400, {"success": False, "error": "Missing 'description' field"})
                return

            result = design_voice(description, preview_text)
            self._send_json(200 if result["success"] else 500, result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_design_smart(self):
        """Design voice with quality self-analysis and retry loop."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            description = data.get("description", "")
            preview_text = data.get("preview_text", "Hello, this is a preview of the designed voice.")
            max_attempts = min(data.get("max_attempts", 3), 5)
            min_mos = data.get("min_mos", 2.5)

            if not description:
                self._send_json(400, {"success": False, "error": "Missing 'description' field"})
                return

            result = design_voice_smart(description, preview_text, max_attempts, min_mos)
            self._send_json(200 if result["success"] else 500, result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_identify(self):
        """Step 1: Identify the subject of a voice search.
        Returns structured info so the user can confirm before finding clips."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            query = data.get("query", "").strip()
            if not query:
                self._send_json(400, {"success": False, "error": "Missing 'query'"})
                return
            result = identify_subject(query)
            self._send_json(200 if result["success"] else 404, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_find_clips(self):
        """Step 2: Find pure audio clips for a confirmed subject (SSE streaming).
        Searches YouTube with targeted queries, filters by name, downloads clips,
        extracts embeddings, and streams results one at a time for user selection."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            query = data.get("query", "").strip()
            clip_queries = data.get("clip_queries", [])
            max_clips = min(data.get("max_clips", 6), 12)
            exclude_ids = data.get("exclude_ids", [])

            if not query:
                self._send_json(400, {"success": False, "error": "Missing 'query'"})
                return

            self._start_sse()

            try:
                import yt_dlp
            except ImportError:
                self._send_sse("error", {"error": "yt-dlp not installed"})
                return

            classification = _classify_query(query)
            name_parts = _extract_name_parts(query) if classification.get("is_person") or classification.get("is_performance") else []

            # Use provided clip queries or generate them
            if not clip_queries:
                clip_queries = _build_clip_queries(query, classification, [])

            self._send_sse("progress", {
                "stage": "searching",
                "message": f"Searching for clips of {query}...",
                "num_queries": len(clip_queries),
            })

            # Collect YouTube entries across all queries
            all_entries = []
            seen_ids = set(exclude_ids or [])

            for qi, cq in enumerate(clip_queries):
                try:
                    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                            "extract_flat": True, "default_search": "ytsearch"}) as ydl:
                        r = ydl.extract_info(f"ytsearch10:{cq}", download=False)
                        added = 0
                        for e in (r.get("entries") or []):
                            if not e:
                                continue
                            vid = e.get("id", "")
                            if vid in seen_ids:
                                continue
                            title = e.get("title", "")
                            # Name relevance filter
                            if name_parts:
                                t_lower = title.lower()
                                if not any(p in t_lower for p in name_parts):
                                    continue
                            seen_ids.add(vid)
                            all_entries.append(e)
                            added += 1
                    self._send_sse("progress", {
                        "stage": "query_done",
                        "message": f"Query {qi+1}/{len(clip_queries)}: '{cq[:45]}' — {added} new matches",
                        "query_index": qi,
                        "total_matched": len(all_entries),
                    })
                except Exception:
                    pass
                if len(all_entries) >= max_clips * 3:
                    break

            if not all_entries:
                self._send_sse("complete", {
                    "success": False, "clips": [],
                    "message": f"No clips found matching {query}",
                })
                return

            # Score and sort candidates
            scored = []
            for e in all_entries:
                title = e.get("title", "")
                duration = e.get("duration")
                ts = _score_candidate_title(title, classification, query)
                # Duration preference: 30s-5min ideal for speech
                d = duration or 9999
                if classification.get("is_sfx"):
                    dur_score = 0 if d <= 30 else (1 if d <= 120 else 2)
                else:
                    dur_score = 0 if 30 <= d <= 300 else (1 if d < 30 else 2)
                scored.append({
                    "entry": e,
                    "title_score": ts,
                    "dur_score": dur_score,
                })
            scored.sort(key=lambda x: (x["dur_score"], -x["title_score"]))
            top = scored[:max_clips]

            self._send_sse("progress", {
                "stage": "candidates",
                "message": f"Selected {len(top)} best candidates from {len(all_entries)} matches",
                "candidates": [{"title": s["entry"].get("title", "")[:60],
                                "score": round(s["title_score"], 1),
                                "duration": s["entry"].get("duration")}
                               for s in top],
            })

            # Download and process each clip, streaming results individually
            cache_dir = _get_reference_cache_dir()
            clips = []

            for ci, s in enumerate(top):
                e = s["entry"]
                vid = e.get("id", "")
                title = e.get("title", "Unknown")
                duration = e.get("duration")

                self._send_sse("progress", {
                    "stage": "downloading",
                    "message": f"Downloading clip {ci+1}/{len(top)}: {title[:50]}",
                    "clip_index": ci, "total_clips": len(top),
                })

                cand = {
                    "id": vid, "title": title, "duration": duration,
                    "url": f"https://www.youtube.com/watch?v={vid}",
                    "source": "youtube_search",
                }
                result = _process_candidate(cand, cache_dir)

                clip_data = {
                    "video_id": vid,
                    "title": title,
                    "duration": duration,
                    "url": cand["url"],
                    "title_score": round(s["title_score"], 1),
                    "has_embedding": bool(result.get("embedding")),
                    "embedding": result.get("embedding"),
                    "embedding_dimensions": result.get("embedding_dimensions"),
                    "audio_base64": result.get("audio_base64"),
                    "audio_sample_rate": result.get("audio_sample_rate"),
                    "isolation": result.get("isolation"),
                    "error": result.get("error"),
                }
                clips.append(clip_data)

                # Stream each clip as it's ready so the user can start previewing
                iso = result.get("isolation") or {}
                iso_msg = ""
                if iso.get("segments_kept") is not None:
                    iso_msg = (f" | Isolated: {iso['segments_kept']}/"
                               f"{iso['total_segments']} segments")
                status = "ready" if result.get("embedding") else "failed"
                self._send_sse("clip", {
                    "clip": clip_data,
                    "clip_index": ci,
                    "total_clips": len(top),
                    "message": f"Clip {ci+1}/{len(top)}: {title[:40]} — {status}{iso_msg}",
                })

            successful = [c for c in clips if c["has_embedding"]]
            self._send_sse("complete", {
                "success": len(successful) > 0,
                "query": query,
                "clips": clips,
                "num_clips": len(clips),
                "num_with_embeddings": len(successful),
            })

        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                self._send_sse("error", {"error": str(e)})
            except Exception:
                pass

    def _handle_search_voice(self):
        """Search for voice references on YouTube.
        Supports single query or multi-name mode (comma/newline-separated names)."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            query = data.get("query", "")
            max_results = min(data.get("max_results", 3), 20)
            max_duration = data.get("max_duration", 60)
            exclude_ids = data.get("exclude_ids", [])
            mode = data.get("mode", "single")  # "single" or "multi"

            if not query:
                self._send_json(400, {"success": False, "error": "Missing 'query' field"})
                return

            if mode == "multi":
                # Split by commas and newlines, strip whitespace, filter empties
                import re
                names = [n.strip() for n in re.split(r'[,\n]+', query) if n.strip()]
                if len(names) <= 1:
                    # Fall back to single mode if only one name
                    result = search_voice_references(names[0] if names else query,
                                                     max_results, max_duration, exclude_ids)
                    result["mode"] = "single"
                    self._send_json(200 if result["success"] else 500, result)
                    return

                print(f"  [voice-designer] Multi-name search: {len(names)} names — {names}")
                all_results = []
                groups = []
                running_excludes = list(exclude_ids)
                any_success = False

                for name in names:
                    per_name = search_voice_references(
                        name, max_results, max_duration, running_excludes)
                    group = {
                        "name": name,
                        "success": per_name.get("success", False),
                        "classification": per_name.get("classification"),
                        "web_description": per_name.get("web_description", ""),
                        "results": per_name.get("results", []),
                        "num_found": per_name.get("num_found", 0),
                        "num_with_embeddings": per_name.get("num_with_embeddings", 0),
                    }
                    groups.append(group)
                    if group["success"]:
                        any_success = True
                    # Add found IDs to excludes so names don't overlap
                    for r in group["results"]:
                        vid = r.get("video_id")
                        if vid:
                            running_excludes.append(vid)
                    all_results.extend(group["results"])

                self._send_json(200 if any_success else 500, {
                    "success": any_success,
                    "mode": "multi",
                    "query": query,
                    "names": names,
                    "groups": groups,
                    "results": all_results,
                    "num_found": len(all_results),
                    "num_with_embeddings": sum(1 for r in all_results if r.get("embedding")),
                })
            else:
                result = search_voice_references(query, max_results, max_duration, exclude_ids)
                result["mode"] = "single"
                self._send_json(200 if result["success"] else 500, result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_search_voice_stream(self):
        """Streaming search with SSE progress events.
        Sends real-time updates as each stage of the search completes."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            query = data.get("query", "")
            max_results = min(data.get("max_results", 3), 20)
            max_duration = data.get("max_duration", 60)
            exclude_ids = data.get("exclude_ids", [])
            mode = data.get("mode", "single")

            if not query:
                self._send_json(400, {"success": False, "error": "Missing 'query' field"})
                return

            self._start_sse()

            if mode == "multi":
                import re
                names = [n.strip() for n in re.split(r'[,\n]+', query) if n.strip()]
                if len(names) <= 1:
                    names = [query]
                self._send_sse("progress", {
                    "stage": "init", "message": f"Multi-search: {len(names)} names",
                    "names": names, "total_names": len(names),
                })
                all_results = []
                groups = []
                running_excludes = list(exclude_ids)
                any_success = False

                for i, name in enumerate(names):
                    self._send_sse("progress", {
                        "stage": "name_start", "name": name,
                        "name_index": i, "total_names": len(names),
                        "message": f"Searching for {name}... ({i+1}/{len(names)})",
                    })
                    group = self._run_streamed_search(
                        name, max_results, max_duration, running_excludes,
                        name_prefix=f"[{i+1}/{len(names)}] {name}")
                    groups.append({"name": name, **group})
                    if group["success"]:
                        any_success = True
                    for r in group.get("results", []):
                        vid = r.get("video_id")
                        if vid:
                            running_excludes.append(vid)
                    all_results.extend(group.get("results", []))

                self._send_sse("complete", {
                    "success": any_success, "mode": "multi",
                    "query": query, "names": names, "groups": groups,
                    "results": all_results,
                    "num_found": len(all_results),
                    "num_with_embeddings": sum(1 for r in all_results if r.get("embedding")),
                })
            else:
                self._send_sse("progress", {
                    "stage": "init", "message": f"Searching for: {query}",
                })
                result = self._run_streamed_search(query, max_results, max_duration, exclude_ids)
                result["mode"] = "single"
                result["query"] = query
                self._send_sse("complete", result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            try:
                self._send_sse("error", {"error": str(e)})
            except Exception:
                pass

    def _run_streamed_search(self, query: str, max_results: int,
                              max_duration: int, exclude_ids: list,
                              name_prefix: str = "") -> dict:
        """Run a single search with SSE progress events at each stage."""
        try:
            import yt_dlp
        except ImportError:
            self._send_sse("progress", {"stage": "error", "message": "yt-dlp not installed"})
            return {"success": False, "error": "yt-dlp not installed", "results": []}

        pfx = f"{name_prefix}: " if name_prefix else ""
        cache_dir = _get_reference_cache_dir()
        exclude_set = set(exclude_ids or [])

        # Stage 1: Classify
        self._send_sse("progress", {
            "stage": "classify", "message": f"{pfx}Analyzing query type...",
        })
        classification = _classify_query(query)
        self._send_sse("progress", {
            "stage": "classify_done", "message": f"{pfx}Query classified",
            "classification": classification,
        })

        # Stage 2: Web research
        self._send_sse("progress", {
            "stage": "research", "message": f"{pfx}Researching voice characteristics...",
        })
        web_results, web_description = _web_research_voice(query, classification)
        self._send_sse("progress", {
            "stage": "research_done",
            "message": f"{pfx}Found {len(web_results)} web results",
            "web_description": web_description[:200] if web_description else "",
            "num_web": len(web_results),
        })

        # Stage 3: YouTube search
        self._send_sse("progress", {
            "stage": "youtube", "message": f"{pfx}Searching YouTube for clips...",
        })
        yt_search_queries = _build_search_queries(query, classification)
        name_parts = _extract_name_parts(query) if classification.get("is_person") else []
        yt_entries = []
        yt_skipped = 0
        for sq_i, sq in enumerate(yt_search_queries):
            try:
                with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True,
                                        "extract_flat": True, "default_search": "ytsearch"}) as ydl:
                    r = ydl.extract_info(f"ytsearch10:{sq}", download=False)
                    for e in (r.get("entries") or []):
                        if not e or e.get("id") in [x.get("id") for x in yt_entries]:
                            continue
                        # For person queries, filter by name presence in title
                        if name_parts:
                            t = (e.get("title") or "").lower()
                            if not any(p in t for p in name_parts):
                                yt_skipped += 1
                                continue
                        yt_entries.append(e)
                skipped_note = f" ({yt_skipped} filtered)" if yt_skipped else ""
                self._send_sse("progress", {
                    "stage": "youtube_query",
                    "message": f"{pfx}YouTube query {sq_i+1}/{len(yt_search_queries)}: "
                               f"'{sq[:40]}' — {len(yt_entries)} matched{skipped_note}",
                    "query_index": sq_i, "total_queries": len(yt_search_queries),
                    "num_entries": len(yt_entries), "num_skipped": yt_skipped,
                })
            except Exception:
                pass
            if len(yt_entries) >= max_results * 4:
                break

        # Combine and deduplicate candidates
        candidates = []
        seen_ids = set(exclude_set)
        for wr in web_results:
            url = wr["url"]
            vid = None
            if "v=" in url:
                vid = url.split("v=")[1].split("&")[0]
            elif "youtu.be/" in url:
                vid = url.split("youtu.be/")[1].split("?")[0]
            if vid and vid not in seen_ids:
                seen_ids.add(vid)
                candidates.append({
                    "id": vid, "title": wr.get("title", ""), "duration": None,
                    "url": f"https://www.youtube.com/watch?v={vid}", "source": "web_research",
                })
        for e in yt_entries:
            vid = e.get("id", "")
            if vid and vid not in seen_ids:
                seen_ids.add(vid)
                candidates.append({
                    "id": vid, "title": e.get("title", "Unknown"),
                    "duration": e.get("duration"),
                    "url": f"https://www.youtube.com/watch?v={vid}", "source": "youtube_search",
                })

        # Sort by duration + title quality
        def sort_key(c):
            d = c.get("duration") or 9999
            if classification["is_sfx"]:
                dur_score = 0 if d <= 30 else (1 if d <= 120 else 2)
            else:
                dur_score = 0 if 30 <= d <= 300 else (1 if d < 30 else 2)
            title_score = -_score_candidate_title(c.get("title", ""), classification, query)
            return (dur_score, title_score)
        candidates.sort(key=sort_key)
        candidates = candidates[:max_results]

        self._send_sse("progress", {
            "stage": "candidates",
            "message": f"{pfx}{len(candidates)} candidates selected from "
                       f"{len(web_results)} web + {len(yt_entries)} YouTube",
            "candidates": [{"title": c["title"][:60], "id": c["id"],
                            "duration": c.get("duration"),
                            "title_score": round(_score_candidate_title(
                                c.get("title", ""), classification, query), 1)}
                           for c in candidates],
        })

        if not candidates:
            return {"success": False, "results": [],
                    "web_description": web_description,
                    "num_found": 0, "num_with_embeddings": 0}

        # Stage 4: Download & extract embeddings
        results = []
        for ci, cand in enumerate(candidates):
            self._send_sse("progress", {
                "stage": "download",
                "message": f"{pfx}Downloading clip {ci+1}/{len(candidates)}: "
                           f"{cand['title'][:50]}",
                "clip_index": ci, "total_clips": len(candidates),
                "video_id": cand["id"],
            })
            result = _process_candidate(cand, cache_dir)
            emb_status = "embedded" if result.get("embedding") else (result.get("error") or "no embedding")
            iso = result.get("isolation") or {}
            iso_msg = ""
            if iso.get("segments_kept") is not None:
                iso_msg = (f" | Speaker isolated: {iso['segments_kept']}/{iso['total_segments']} "
                           f"segments ({iso.get('kept_duration_s', 0):.1f}s)")
            self._send_sse("progress", {
                "stage": "clip_done",
                "message": f"{pfx}Clip {ci+1}/{len(candidates)}: {emb_status}{iso_msg}",
                "clip_index": ci, "total_clips": len(candidates),
                "video_id": cand["id"],
                "has_embedding": bool(result.get("embedding")),
            })
            results.append(result)

        successful = [r for r in results if r["embedding"]]
        return {
            "success": len(successful) > 0,
            "classification": classification,
            "web_description": web_description,
            "results": results,
            "num_found": len(results),
            "num_with_embeddings": len(successful),
        }

    def _handle_design_with_reference(self):
        """Design voice using a reference audio sample + text description."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            description = data.get("description", "")
            preview_text = data.get("preview_text", "Hello, this is a preview.")
            ref_audio_b64 = data.get("reference_audio_base64", "")
            ref_sample_rate = data.get("reference_sample_rate", 16000)

            if not ref_audio_b64:
                self._send_json(400, {"success": False, "error": "Missing reference_audio_base64"})
                return

            # Decode reference audio
            ref_bytes = base64.b64decode(ref_audio_b64)
            num_samples = len(ref_bytes) // 4
            ref_pcm = np.array(
                struct.unpack(f"<{num_samples}f", ref_bytes[:num_samples * 4]),
                dtype=np.float32,
            )

            # Extract embedding from reference
            emb_result = extract_embedding(ref_pcm, ref_sample_rate)
            if not emb_result["success"]:
                self._send_json(500, {"success": False, "error": f"Embedding extraction failed: {emb_result.get('error')}"})
                return

            # Generate voice with Parler-TTS using description
            design_result = design_voice(description, preview_text)
            if not design_result["success"]:
                self._send_json(500, design_result)
                return

            # Return both the generated audio and the extracted embedding
            design_result["reference_embedding"] = emb_result["embedding"]
            design_result["reference_embedding_dimensions"] = emb_result["dimensions"]
            self._send_json(200, design_result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_extract_embedding(self):
        """Extract speaker embedding from uploaded audio."""
        try:
            sample_rate = int(self.headers.get("X-Sample-Rate", "22050"))
            content_length = int(self.headers.get("Content-Length", 0))
            pcm_bytes = self.rfile.read(content_length)

            if len(pcm_bytes) < 4:
                self._send_json(400, {"success": False, "error": "No audio data received"})
                return

            num_samples = len(pcm_bytes) // 4
            pcm_f32 = np.array(
                struct.unpack(f"<{num_samples}f", pcm_bytes[:num_samples * 4]),
                dtype=np.float32,
            )

            result = extract_embedding(pcm_f32, sample_rate)
            self._send_json(200 if result["success"] else 500, result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_blend(self):
        """Blend multiple speaker embeddings."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            embeddings = data.get("embeddings", [])
            weights = data.get("weights", [1.0] * len(embeddings))

            result = blend_embeddings(embeddings, weights)
            self._send_json(200 if result["success"] else 400, result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_save_profile(self):
        """Save a voice design profile."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            result = save_profile(
                profile_id=data.get("profile_id", ""),
                name=data.get("name", "Unnamed"),
                description=data.get("description", ""),
                embedding=data.get("embedding"),
                reference_audio_b64=data.get("reference_audio_base64"),
                sample_rate=data.get("sample_rate", 22050),
            )
            self._send_json(200, result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_list_profiles(self):
        """List saved voice profiles."""
        profiles = list_profiles()
        self._send_json(200, {"profiles": profiles})

    def _handle_delete_profile(self):
        """Delete a voice profile."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            profile_id = data.get("profile_id", "")
            if not profile_id:
                self._send_json(400, {"success": False, "error": "Missing profile_id"})
                return
            result = delete_profile(profile_id)
            self._send_json(200, result)
        except Exception as e:
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_voice_anatomy_get(self):
        """Return the voice anatomy schema (element definitions + examples)."""
        self._send_json(200, {"elements": VOICE_ANATOMY})

    def _handle_voice_anatomy(self):
        """POST: same as GET, returns anatomy schema."""
        self._send_json(200, {"elements": VOICE_ANATOMY})

    def _handle_decompose(self):
        """Decompose a text description into voice anatomy elements."""
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            description = data.get("description", "")
            if not description:
                self._send_json(400, {"success": False, "error": "Missing 'description'"})
                return
            result = decompose_description(description)
            self._send_json(200, {"success": True, "decomposition": result,
                                   "description": description})
        except Exception as e:
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_analyze_anatomy(self):
        """Analyze uploaded audio and return voice anatomy measurements."""
        try:
            sample_rate = int(self.headers.get("X-Sample-Rate", "16000"))
            content_length = int(self.headers.get("Content-Length", 0))
            pcm_bytes = self.rfile.read(content_length)
            if len(pcm_bytes) < 4:
                self._send_json(400, {"success": False, "error": "No audio data"})
                return
            num_samples = len(pcm_bytes) // 4
            pcm_f32 = np.array(
                struct.unpack(f"<{num_samples}f", pcm_bytes[:num_samples * 4]),
                dtype=np.float32,
            )
            # Isolate target speaker before analyzing
            isolated, iso_info = isolate_target_speaker(pcm_f32, sample_rate)
            analysis = analyze_audio_anatomy(isolated, sample_rate)
            analysis["_isolation"] = iso_info
            self._send_json(200, {"success": True, "anatomy": analysis})
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_compose(self):
        """Compose a voice from references + anatomy specs + description.

        Request body:
        {
            "description": "A warm, deep voice...",
            "preview_text": "Hello world",
            "references": [
                {"embedding": [...], "weight": 0.7, "label": "Morgan Freeman"},
                {"embedding": [...], "weight": 0.3, "label": "James Earl Jones"},
            ],
            "anatomy": {
                "timbre": "warm and rich",
                "pitch": "deep bass",
                "emotion": "authoritative and calm",
                ...
            },
            "max_attempts": 3,
            "min_mos": 2.5
        }
        """
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            description = data.get("description", "")
            preview_text = data.get("preview_text", "Hello, this is a preview.")
            references = data.get("references", [])
            anatomy_specs = data.get("anatomy", {})
            max_attempts = min(data.get("max_attempts", 3), 5)
            min_mos = data.get("min_mos", 2.5)

            if not description and not anatomy_specs:
                self._send_json(400, {"success": False,
                    "error": "Provide 'description' and/or 'anatomy' specs"})
                return

            result = compose_voice(references, anatomy_specs, description,
                                   preview_text, max_attempts, min_mos)
            self._send_json(200 if result.get("success") else 500, result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_suggest_from_palette(self):
        """Analyze palette audio references and suggest a voice description.

        Request body:
        {
            "references": [
                {"audio_base64": "...", "sample_rate": 16000, "label": "..."},
                ...
            ],
            "mode": "commonalities" | "additive"
        }
        """
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            refs = data.get("references", [])
            mode = data.get("mode", "commonalities")

            if not refs:
                self._send_json(400, {"success": False, "error": "No references"})
                return

            # Analyze each reference audio
            analyses = []
            labels = []
            for ref in refs:
                label = ref.get("label", "Unknown")
                labels.append(label)

                audio_b64 = ref.get("audio_base64", "")
                sr = ref.get("sample_rate", 16000)

                if audio_b64:
                    pcm_bytes = base64.b64decode(audio_b64)
                    num_samples = len(pcm_bytes) // 4
                    pcm_f32 = np.array(
                        struct.unpack(f"<{num_samples}f",
                                      pcm_bytes[:num_samples * 4]),
                        dtype=np.float32,
                    )
                    # Isolate target speaker before analyzing
                    isolated, iso_info = isolate_target_speaker(
                        pcm_f32, sr, segment_duration=2.0,
                        similarity_threshold=0.55)
                    analysis = analyze_audio_anatomy(isolated, sr)
                    analysis["_isolation"] = iso_info
                    analyses.append(analysis)
                    print(f"  [voice-designer] Analyzed '{label}': "
                          f"pitch={analysis.get('pitch',{}).get('label','?')}, "
                          f"texture={analysis.get('texture',{}).get('label','?')}")
                else:
                    analyses.append({})
                    print(f"  [voice-designer] No audio data for '{label}'")

            result = suggest_description_from_references(analyses, labels, mode)
            self._send_json(200 if result["success"] else 400, result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_generate_clone_sample(self):
        """Generate a long audio sample suitable for voice cloning.

        Request body:
        {
            "description": "A warm deep voice...",
            "anatomy": { ... },
            "duration_target_s": 15
        }
        """
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            description = data.get("description", "A natural speaking voice")
            anatomy = data.get("anatomy", {})
            duration = min(data.get("duration_target_s", 15), 30)

            result = generate_clone_sample(description, duration, anatomy)
            self._send_json(200 if result["success"] else 500, result)

        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_interpret(self):
        """Interpret a freeform voice creation request using Gemini AI.

        Request body:
        {
            "input": "I want a voice like honey dripping over warm bread"
        }
        """
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            user_input = data.get("input", "").strip()
            if not user_input:
                self._send_json(400, {"success": False, "error": "Missing 'input' field"})
                return
            result = interpret_voice_request(user_input)
            self._send_json(200 if result["success"] else 500, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    # ── ElevenLabs endpoint handlers ────────────────────────────────

    def _handle_elevenlabs_design(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            description = data.get("description", "")
            preview_text = data.get("preview_text", "Hello, this is a preview of the designed voice.")
            if not description:
                self._send_json(400, {"success": False, "error": "Missing 'description'"})
                return
            result = elevenlabs_design_voice(description, preview_text)
            self._send_json(200 if result["success"] else 500, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_elevenlabs_create_voice(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            name = data.get("name", "")
            description = data.get("description", "")
            generated_voice_id = data.get("generated_voice_id", "")
            if not name or not generated_voice_id:
                self._send_json(400, {"success": False, "error": "Missing 'name' or 'generated_voice_id'"})
                return
            result = elevenlabs_create_voice(name, description, generated_voice_id)
            self._send_json(200 if result["success"] else 500, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_elevenlabs_synthesize(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            text = data.get("text", "")
            voice_id = data.get("voice_id", "")
            if not text or not voice_id:
                self._send_json(400, {"success": False, "error": "Missing 'text' or 'voice_id'"})
                return
            result = elevenlabs_synthesize(
                text, voice_id,
                model_id=data.get("model_id", "eleven_multilingual_v2"),
                voice_settings=data.get("voice_settings"),
            )
            self._send_json(200 if result["success"] else 500, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    # ── Voice crafting endpoint handlers ─────────────────────────────

    def _handle_crafting_start(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            engine = _get_crafting_engine()
            result = engine.start_session(
                mode=data.get("mode", "guided"),
                archetype_id=data.get("archetype_id"),
                freeform_text=data.get("freeform_text"),
            )
            self._send_json(200 if result.get("success") else 400, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_crafting_explore(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            engine = _get_crafting_engine()
            result = engine.explore_axis(
                session_id=data.get("session_id", ""),
                axis_id=data.get("axis_id"),
                preview_text=data.get("preview_text"),
            )
            self._send_json(200 if result.get("success") else 400, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_crafting_select(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            engine = _get_crafting_engine()
            result = engine.select_choice(
                session_id=data.get("session_id", ""),
                axis_id=data.get("axis_id", ""),
                archetype_id=data.get("archetype_id", ""),
                preview_index=data.get("preview_index", 0),
            )
            self._send_json(200 if result.get("success") else 400, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_crafting_regenerate(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            engine = _get_crafting_engine()
            result = engine.regenerate(
                session_id=data.get("session_id", ""),
                preview_text=data.get("preview_text"),
            )
            self._send_json(200 if result.get("success") else 400, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_crafting_skip(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            engine = _get_crafting_engine()
            result = engine.skip_axis(session_id=data.get("session_id", ""))
            self._send_json(200 if result.get("success") else 400, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_crafting_back(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            engine = _get_crafting_engine()
            result = engine.go_back(session_id=data.get("session_id", ""))
            self._send_json(200 if result.get("success") else 400, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_crafting_finish(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            engine = _get_crafting_engine()
            result = engine.finish(
                session_id=data.get("session_id", ""),
                profile_name=data.get("profile_name"),
            )
            self._send_json(200 if result.get("success") else 400, result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._send_json(500, {"success": False, "error": str(e)})

    def _handle_crafting_get_session(self):
        parsed = urlparse(self.path)
        session_id = parsed.path.split("/crafting/session/")[-1].strip("/")
        engine = _get_crafting_engine()
        result = engine.get_session(session_id)
        self._send_json(200 if result.get("success") else 404, result)

    def _handle_crafting_archetypes(self):
        from voice_crafting import get_archetypes
        self._send_json(200, {"archetypes": get_archetypes()})

    def _handle_crafting_axes(self):
        from voice_crafting import get_axes
        self._send_json(200, {"axes": get_axes()})

    def _send_json(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _start_sse(self):
        """Begin a Server-Sent Events stream."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()

    def _send_sse(self, event: str, data: dict):
        """Send a single SSE event."""
        payload = json.dumps(data)
        msg = f"event: {event}\ndata: {payload}\n\n"
        self.wfile.write(msg.encode())
        self.wfile.flush()


def main():
    parser = argparse.ArgumentParser(description="Voice designer server for web-vox-pro")
    parser.add_argument("--port", type=int, default=21749)
    parser.add_argument("--device", choices=["cpu", "cuda", "mps"], default=None,
                        help="Override device from device_config.json")
    parser.add_argument("--preload", action="store_true",
                        help="Load models immediately on startup")
    args = parser.parse_args()

    _load_config()

    global _device
    if args.device:
        _device = args.device

    print(f"  [voice-designer] Starting voice designer server on port {args.port}")
    print(f"  [voice-designer] Device: {_device}")
    print(f"  [voice-designer] Profiles directory: {_get_profiles_dir()}")

    if args.preload:
        _get_parler()
        _get_speaker_encoder()

    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True

    server = ThreadedHTTPServer(("127.0.0.1", args.port), VoiceDesignerHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  [voice-designer] Shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
