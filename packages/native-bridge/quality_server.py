#!/usr/bin/env python3
"""
Quality analysis server for web-vox-pro.

Accepts synthesized audio + transcript, returns quality scores from a
"model council": ASR verification (Whisper), MOS prediction (UTMOS),
prosody analysis (librosa), and signal quality metrics.

Port: 21748

Usage:
    python3 quality_server.py [--device cpu|cuda|mps] [--port 21748]
"""

import argparse
import json
import struct
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

# ── Lazy-loaded models ────────────────────────────────────────────────

_whisper_model = None
_utmos_model = None
_device = "cpu"
_whisper_model_size = "small"


def _load_config():
    """Load device config from device_config.json if present."""
    global _device, _whisper_model_size
    config_path = Path(__file__).parent / "device_config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            quality = config.get("quality", {})
            _device = quality.get("device", _device)
            models = quality.get("models", {})
            whisper_cfg = models.get("whisper", {})
            if "model_size" in whisper_cfg:
                _whisper_model_size = whisper_cfg["model_size"]
        except Exception as e:
            print(f"  [quality] Warning: failed to read device_config.json: {e}")


def _get_whisper():
    global _whisper_model
    if _whisper_model is None:
        import stable_whisper
        print(f"  [quality] Loading Whisper '{_whisper_model_size}' on {_device} for ASR verification...")
        t0 = time.time()
        _whisper_model = stable_whisper.load_model(_whisper_model_size, device=_device)
        print(f"  [quality] Whisper loaded in {time.time() - t0:.1f}s")
    return _whisper_model


def _get_utmos():
    """Load UTMOS MOS predictor (torch Hub model from sarulab-speech)."""
    global _utmos_model
    if _utmos_model is None:
        try:
            import torch
            print(f"  [quality] Loading UTMOS predictor on {_device}...")
            t0 = time.time()
            _utmos_model = torch.hub.load(
                "tarepan/SpeechMOS:v1.2.0", "utmos22_strong",
                trust_repo=True
            )
            if _device != "cpu":
                _utmos_model = _utmos_model.to(_device)
            _utmos_model.eval()
            print(f"  [quality] UTMOS loaded in {time.time() - t0:.1f}s")
        except Exception as e:
            print(f"  [quality] UTMOS unavailable: {e}")
            _utmos_model = "unavailable"
    return _utmos_model


# ── Analysis functions ────────────────────────────────────────────────

def _compute_wer(reference: str, hypothesis: str) -> float:
    """Compute word error rate between reference and hypothesis transcripts."""
    ref_words = reference.lower().split()
    hyp_words = hypothesis.lower().split()

    if not ref_words:
        return 0.0 if not hyp_words else 1.0

    # Levenshtein distance on word level
    d = [[0] * (len(hyp_words) + 1) for _ in range(len(ref_words) + 1)]
    for i in range(len(ref_words) + 1):
        d[i][0] = i
    for j in range(len(hyp_words) + 1):
        d[0][j] = j

    for i in range(1, len(ref_words) + 1):
        for j in range(1, len(hyp_words) + 1):
            cost = 0 if ref_words[i - 1] == hyp_words[j - 1] else 1
            d[i][j] = min(
                d[i - 1][j] + 1,       # deletion
                d[i][j - 1] + 1,       # insertion
                d[i - 1][j - 1] + cost  # substitution
            )

    return min(d[len(ref_words)][len(hyp_words)] / len(ref_words), 1.0)


def _asr_verify(pcm_f32: np.ndarray, sample_rate: int, transcript: str) -> dict:
    """Use Whisper to transcribe audio and compare with expected transcript."""
    try:
        model = _get_whisper()
        # Resample to 16kHz if needed
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

        result = model.transcribe(audio, language="en")
        hypothesis = result.text.strip()

        wer = _compute_wer(transcript, hypothesis)

        return {
            "available": True,
            "hypothesis": hypothesis,
            "wer": round(wer, 4),
            "confidence": round(1.0 - wer, 4),
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


def _mos_predict(pcm_f32: np.ndarray, sample_rate: int) -> dict:
    """Predict Mean Opinion Score using UTMOS."""
    try:
        model = _get_utmos()
        if model == "unavailable":
            return {"available": False, "error": "UTMOS model not loaded"}

        import torch

        # UTMOS expects 16kHz
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

        tensor = torch.from_numpy(audio).unsqueeze(0).float()
        if _device != "cpu":
            tensor = tensor.to(_device)

        with torch.no_grad():
            score = model(tensor, 16000)

        mos = float(score.item())
        return {
            "available": True,
            "mos": round(mos, 3),
            "rating": _mos_rating(mos),
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


def _mos_rating(mos: float) -> str:
    """Map MOS score to human-readable rating."""
    if mos >= 4.5:
        return "excellent"
    elif mos >= 4.0:
        return "good"
    elif mos >= 3.5:
        return "fair"
    elif mos >= 3.0:
        return "poor"
    else:
        return "bad"


def _prosody_analyze(pcm_f32: np.ndarray, sample_rate: int) -> dict:
    """Analyze prosody: F0 statistics, energy contour, speaking rate estimate."""
    try:
        import librosa

        # F0 via pyin (reliable pitch tracker)
        f0, voiced_flag, voiced_prob = librosa.pyin(
            pcm_f32, fmin=50, fmax=500, sr=sample_rate
        )
        f0_voiced = f0[~np.isnan(f0)]

        f0_stats = {}
        if len(f0_voiced) > 0:
            f0_stats = {
                "mean_hz": round(float(np.mean(f0_voiced)), 1),
                "std_hz": round(float(np.std(f0_voiced)), 1),
                "min_hz": round(float(np.min(f0_voiced)), 1),
                "max_hz": round(float(np.max(f0_voiced)), 1),
                "range_hz": round(float(np.max(f0_voiced) - np.min(f0_voiced)), 1),
                "voiced_ratio": round(float(np.sum(~np.isnan(f0)) / len(f0)), 3),
            }
        else:
            f0_stats = {"voiced_ratio": 0.0}

        # RMS energy
        rms = librosa.feature.rms(y=pcm_f32)[0]
        energy_stats = {
            "mean_db": round(float(20 * np.log10(np.mean(rms) + 1e-10)), 1),
            "max_db": round(float(20 * np.log10(np.max(rms) + 1e-10)), 1),
            "dynamic_range_db": round(
                float(20 * np.log10((np.max(rms) + 1e-10) / (np.min(rms) + 1e-10))), 1
            ),
        }

        # Spectral centroid (brightness)
        spec_centroid = librosa.feature.spectral_centroid(y=pcm_f32, sr=sample_rate)[0]
        brightness = {
            "mean_hz": round(float(np.mean(spec_centroid)), 1),
            "std_hz": round(float(np.std(spec_centroid)), 1),
        }

        return {
            "available": True,
            "f0": f0_stats,
            "energy": energy_stats,
            "brightness": brightness,
        }
    except Exception as e:
        return {"available": False, "error": str(e)}


def _signal_quality(pcm_f32: np.ndarray, sample_rate: int) -> dict:
    """Compute signal-level quality metrics: SNR, clipping, silence."""
    # Clipping detection (samples near ±1.0)
    clip_threshold = 0.99
    num_clipped = int(np.sum(np.abs(pcm_f32) > clip_threshold))
    clip_ratio = num_clipped / max(len(pcm_f32), 1)

    # Silence detection (RMS below threshold)
    frame_size = int(0.025 * sample_rate)  # 25ms frames
    hop_size = int(0.010 * sample_rate)    # 10ms hop
    silence_threshold_db = -40

    num_frames = 0
    num_silent = 0
    for start in range(0, len(pcm_f32) - frame_size, hop_size):
        frame = pcm_f32[start:start + frame_size]
        rms = np.sqrt(np.mean(frame ** 2))
        rms_db = 20 * np.log10(rms + 1e-10)
        num_frames += 1
        if rms_db < silence_threshold_db:
            num_silent += 1

    silence_ratio = num_silent / max(num_frames, 1)

    # SNR estimate (signal vs silence floor)
    overall_rms = np.sqrt(np.mean(pcm_f32 ** 2))
    # Use quietest 10% of frames as noise estimate
    frame_rms_list = []
    for start in range(0, len(pcm_f32) - frame_size, hop_size):
        frame = pcm_f32[start:start + frame_size]
        frame_rms_list.append(np.sqrt(np.mean(frame ** 2)))

    if frame_rms_list:
        frame_rms_list.sort()
        noise_floor = np.mean(frame_rms_list[:max(1, len(frame_rms_list) // 10)])
        snr_db = 20 * np.log10((overall_rms + 1e-10) / (noise_floor + 1e-10))
    else:
        snr_db = 0.0

    # Artifact indicators
    artifacts = []
    if clip_ratio > 0.001:
        artifacts.append({"type": "clipping", "severity": "high" if clip_ratio > 0.01 else "low",
                          "detail": f"{clip_ratio * 100:.2f}% samples clipped"})
    if silence_ratio > 0.5:
        artifacts.append({"type": "excessive_silence", "severity": "medium",
                          "detail": f"{silence_ratio * 100:.1f}% silent frames"})
    if snr_db < 10:
        artifacts.append({"type": "low_snr", "severity": "high" if snr_db < 5 else "medium",
                          "detail": f"SNR {snr_db:.1f} dB"})

    return {
        "snr_db": round(float(snr_db), 1),
        "clip_ratio": round(float(clip_ratio), 5),
        "silence_ratio": round(float(silence_ratio), 3),
        "artifacts": artifacts,
    }


def analyze_audio(pcm_f32: np.ndarray, sample_rate: int, transcript: str,
                  analyzers: list[str] | None = None) -> dict:
    """
    Run the quality analysis council on synthesized audio.

    analyzers: list of which analyses to run. Default: all.
      Options: "asr", "mos", "prosody", "signal"
    """
    if analyzers is None:
        analyzers = ["asr", "mos", "prosody", "signal"]

    result = {}

    if "asr" in analyzers:
        result["asr"] = _asr_verify(pcm_f32, sample_rate, transcript)

    if "mos" in analyzers:
        result["mos"] = _mos_predict(pcm_f32, sample_rate)

    if "prosody" in analyzers:
        result["prosody"] = _prosody_analyze(pcm_f32, sample_rate)

    if "signal" in analyzers:
        result["signal"] = _signal_quality(pcm_f32, sample_rate)

    # Compute overall score (weighted average of available metrics)
    result["overall"] = _compute_overall(result)

    # Generate recommendations
    result["recommendations"] = _generate_recommendations(result)

    return result


def _compute_overall(scores: dict) -> dict:
    """Compute a weighted overall quality score from individual analyses."""
    components = []
    weights = []

    if "asr" in scores and scores["asr"].get("available"):
        # ASR confidence maps to 1-5 scale
        asr_score = scores["asr"]["confidence"] * 5.0
        components.append(asr_score)
        weights.append(0.35)

    if "mos" in scores and scores["mos"].get("available"):
        components.append(scores["mos"]["mos"])
        weights.append(0.35)

    if "signal" in scores:
        # Signal quality: penalize artifacts
        signal_score = 5.0
        snr = scores["signal"]["snr_db"]
        if snr < 20:
            signal_score -= (20 - snr) * 0.1
        signal_score -= scores["signal"]["clip_ratio"] * 100
        signal_score -= scores["signal"]["silence_ratio"] * 2
        signal_score = max(1.0, min(5.0, signal_score))
        components.append(signal_score)
        weights.append(0.2)

    if "prosody" in scores and scores["prosody"].get("available"):
        # Prosody: penalize monotone (low F0 range) and low voiced ratio
        f0 = scores["prosody"].get("f0", {})
        prosody_score = 4.0
        if "range_hz" in f0:
            if f0["range_hz"] < 30:
                prosody_score -= 1.0  # monotone
            elif f0["range_hz"] > 200:
                prosody_score += 0.5  # expressive
        if "voiced_ratio" in f0 and f0["voiced_ratio"] < 0.3:
            prosody_score -= 1.0
        prosody_score = max(1.0, min(5.0, prosody_score))
        components.append(prosody_score)
        weights.append(0.1)

    if not components:
        return {"score": 0.0, "rating": "unknown", "num_analyzers": 0}

    total_weight = sum(weights)
    weighted_score = sum(c * w for c, w in zip(components, weights)) / total_weight

    return {
        "score": round(weighted_score, 2),
        "rating": _mos_rating(weighted_score),
        "num_analyzers": len(components),
    }


def _generate_recommendations(scores: dict) -> list[str]:
    """Generate actionable recommendations based on analysis results."""
    recs = []

    if "asr" in scores and scores["asr"].get("available"):
        wer = scores["asr"].get("wer", 0)
        if wer > 0.3:
            recs.append("High word error rate — audio may be unintelligible. Try a different engine or voice.")
        elif wer > 0.1:
            recs.append("Some words were misrecognized — consider re-synthesizing with a higher-quality engine.")

    if "mos" in scores and scores["mos"].get("available"):
        mos = scores["mos"]["mos"]
        if mos < 3.0:
            recs.append("Low MOS score — audio quality is poor. Try a neural TTS engine (Kokoro, XTTS, Qwen).")
        elif mos < 3.5:
            recs.append("Below-average MOS — consider using a higher-quality voice.")

    if "signal" in scores:
        for artifact in scores["signal"].get("artifacts", []):
            if artifact["type"] == "clipping" and artifact["severity"] == "high":
                recs.append("Severe clipping detected — reduce volume or check the TTS engine output.")
            elif artifact["type"] == "excessive_silence":
                recs.append("Excessive silence — the audio contains long pauses. Check text parsing.")
            elif artifact["type"] == "low_snr":
                recs.append("Low signal-to-noise ratio — audio may sound noisy.")

    if "prosody" in scores and scores["prosody"].get("available"):
        f0 = scores["prosody"].get("f0", {})
        if "range_hz" in f0 and f0["range_hz"] < 30:
            recs.append("Monotone speech detected — try a more expressive voice or engine.")

    return recs


# ── HTTP Server ──────────────────────────────────────────────────────

class QualityHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"  [quality] {args[0]}")

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            body = json.dumps({
                "status": "ok",
                "whisper_loaded": _whisper_model is not None,
                "utmos_loaded": _utmos_model is not None and _utmos_model != "unavailable",
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
        if parsed.path == "/analyze":
            self._handle_analyze()
        else:
            self.send_error(404)

    def _handle_analyze(self):
        try:
            sample_rate = int(self.headers.get("X-Sample-Rate", "22050"))
            channels = int(self.headers.get("X-Channels", "1"))
            transcript = self.headers.get("X-Transcript", "")
            request_id = self.headers.get("X-Request-Id", "unknown")
            analyzers_header = self.headers.get("X-Analyzers", "")

            content_length = int(self.headers.get("Content-Length", 0))
            pcm_bytes = self.rfile.read(content_length)

            if len(pcm_bytes) < 4:
                self._send_error(400, "No audio data received")
                return

            num_samples = len(pcm_bytes) // 4
            pcm_f32 = np.array(
                struct.unpack(f"<{num_samples}f", pcm_bytes[:num_samples * 4]),
                dtype=np.float32,
            )

            if channels > 1:
                pcm_f32 = pcm_f32.reshape(-1, channels).mean(axis=1)

            analyzers = None
            if analyzers_header:
                analyzers = [a.strip() for a in analyzers_header.split(",") if a.strip()]

            print(f"  [quality] Analyzing {len(pcm_f32)} samples @ {sample_rate}Hz, "
                  f"request={request_id}, analyzers={analyzers or 'all'}")

            t0 = time.time()
            result = analyze_audio(pcm_f32, sample_rate, transcript, analyzers)
            elapsed = time.time() - t0

            print(f"  [quality] Analysis complete in {elapsed:.2f}s — "
                  f"overall={result['overall']['score']:.2f} ({result['overall']['rating']})")

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
    parser = argparse.ArgumentParser(description="Quality analysis server for web-vox-pro")
    parser.add_argument("--port", type=int, default=21748)
    parser.add_argument("--device", choices=["cpu", "cuda", "mps"], default=None,
                        help="Override device from device_config.json")
    parser.add_argument("--preload", action="store_true",
                        help="Load models immediately on startup")
    args = parser.parse_args()

    _load_config()

    global _device
    if args.device:
        _device = args.device

    print(f"  [quality] Starting quality analysis server on port {args.port}")
    print(f"  [quality] Device: {_device}")

    if args.preload:
        _get_whisper()
        _get_utmos()

    server = HTTPServer(("127.0.0.1", args.port), QualityHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  [quality] Shutting down")
        server.server_close()


if __name__ == "__main__":
    main()
