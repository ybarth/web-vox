#!/usr/bin/env python3
"""
OCR server for web-vox-pro.

Extracts text from images with spatial bounding box coordinates using
EasyOCR (GPU-accelerable) with optional Tesseract fallback.

Port: 21751

Usage:
    python3 ocr_server.py [--port 21751] [--device cpu|cuda|mps]

Endpoints:
    GET  /health          — server status
    GET  /languages       — supported languages
    POST /extract         — extract text from image (JSON body with base64 image)
    POST /extract_regions — extract text with region-of-interest filtering
"""

import argparse
import base64
import io
import json
import time
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

# ── Configuration ─────────────────────────────────────────────────────

_device = "cpu"
_languages = ["en"]
_reader = None  # lazy-loaded EasyOCR reader

def _load_config():
    global _device, _languages
    config_path = Path(__file__).parent / "device_config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            ocr = config.get("ocr", {})
            _device = ocr.get("device", _device)
            langs = ocr.get("languages", None)
            if langs and isinstance(langs, list):
                _languages = langs
        except Exception as e:
            print(f"  [ocr] Warning: failed to read device_config.json: {e}")


def _get_reader():
    """Lazy-load EasyOCR reader."""
    global _reader
    if _reader is None:
        try:
            import easyocr
            gpu = _device in ("cuda", "mps")
            print(f"  [ocr] Loading EasyOCR reader (languages={_languages}, gpu={gpu})...")
            _reader = easyocr.Reader(_languages, gpu=gpu)
            print(f"  [ocr] EasyOCR reader loaded")
        except ImportError:
            print("  [ocr] ERROR: easyocr not installed. Install with: pip install easyocr")
            raise
    return _reader


# ── Image decoding ───────────────────────────────────────────────────

def _decode_image(data: dict) -> tuple:
    """Decode image from request data. Returns (image_bytes, format_hint).

    Supports:
      - base64 encoded image data (data.image_base64)
      - file path on disk (data.image_path)
    """
    if "image_base64" in data:
        img_bytes = base64.b64decode(data["image_base64"])
        fmt = data.get("image_format", "png")
        return img_bytes, fmt
    elif "image_path" in data:
        path = Path(data["image_path"])
        if not path.exists():
            raise FileNotFoundError(f"Image file not found: {path}")
        img_bytes = path.read_bytes()
        fmt = path.suffix.lstrip(".").lower()
        return img_bytes, fmt
    else:
        raise ValueError("No image data provided. Send 'image_base64' or 'image_path'.")


def _get_image_dimensions(img_bytes: bytes) -> tuple:
    """Get image width/height using PIL if available, else return None."""
    try:
        from PIL import Image
        img = Image.open(io.BytesIO(img_bytes))
        return img.width, img.height
    except ImportError:
        return None, None


# ── OCR extraction ───────────────────────────────────────────────────

def _extract_text(img_bytes: bytes, languages: list = None, detail: int = 1,
                  paragraph: bool = False, min_confidence: float = 0.0) -> dict:
    """Run OCR on image bytes, return structured results."""
    reader = _get_reader()
    t0 = time.time()

    # EasyOCR accepts file-like objects
    results = reader.readtext(img_bytes, detail=detail, paragraph=paragraph)
    elapsed = time.time() - t0

    width, height = _get_image_dimensions(img_bytes)

    if detail == 0:
        # Simple mode: just list of strings
        return {
            "success": True,
            "text": "\n".join(results),
            "confidence": 1.0,
            "bounding_boxes": [],
            "image_width": width,
            "image_height": height,
            "processing_time_ms": round(elapsed * 1000, 1),
        }

    # Detail mode: list of (bbox, text, confidence)
    bounding_boxes = []
    full_text_parts = []
    total_confidence = 0.0

    for bbox, text, conf in results:
        if conf < min_confidence:
            continue

        # bbox is [[x1,y1], [x2,y2], [x3,y3], [x4,y4]] — corners of quadrilateral
        # Convert to axis-aligned bounding box
        xs = [p[0] for p in bbox]
        ys = [p[1] for p in bbox]
        left = min(xs)
        top = min(ys)
        right = max(xs)
        bottom = max(ys)

        bounding_boxes.append({
            "text": text,
            "confidence": round(float(conf), 4),
            "left": round(float(left), 1),
            "top": round(float(top), 1),
            "right": round(float(right), 1),
            "bottom": round(float(bottom), 1),
            "width": round(float(right - left), 1),
            "height": round(float(bottom - top), 1),
            "polygon": [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in bbox],
        })
        full_text_parts.append(text)
        total_confidence += conf

    avg_confidence = total_confidence / len(results) if results else 0.0

    return {
        "success": True,
        "text": "\n".join(full_text_parts),
        "confidence": round(float(avg_confidence), 4),
        "bounding_boxes": bounding_boxes,
        "total_regions": len(bounding_boxes),
        "image_width": width,
        "image_height": height,
        "processing_time_ms": round(elapsed * 1000, 1),
    }


def _extract_regions(img_bytes: bytes, regions: list, languages: list = None) -> dict:
    """Extract text from specific regions of interest in the image."""
    try:
        from PIL import Image
    except ImportError:
        return {
            "success": False,
            "error": "PIL/Pillow required for region extraction. Install with: pip install Pillow",
        }

    img = Image.open(io.BytesIO(img_bytes))
    t0 = time.time()
    region_results = []

    for i, region in enumerate(regions):
        left = region.get("left", 0)
        top = region.get("top", 0)
        right = region.get("right", img.width)
        bottom = region.get("bottom", img.height)
        label = region.get("label", f"region_{i}")

        # Crop region
        cropped = img.crop((left, top, right, bottom))
        buf = io.BytesIO()
        cropped.save(buf, format="PNG")
        crop_bytes = buf.getvalue()

        # OCR on cropped region
        result = _extract_text(crop_bytes, languages)
        # Offset bounding boxes back to full image coordinates
        for box in result.get("bounding_boxes", []):
            box["left"] += left
            box["top"] += top
            box["right"] += left
            box["bottom"] += top

        region_results.append({
            "label": label,
            "region": {"left": left, "top": top, "right": right, "bottom": bottom},
            "text": result.get("text", ""),
            "confidence": result.get("confidence", 0.0),
            "bounding_boxes": result.get("bounding_boxes", []),
        })

    elapsed = time.time() - t0
    return {
        "success": True,
        "regions": region_results,
        "total_regions": len(region_results),
        "image_width": img.width,
        "image_height": img.height,
        "processing_time_ms": round(elapsed * 1000, 1),
    }


# ── HTTP Handler ─────────────────────────────────────────────────────

class OcrHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # Suppress default logging

    def _send_json(self, data: dict, status: int = 200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_cors_headers(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._send_cors_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            # Check if EasyOCR is importable
            easyocr_available = False
            try:
                import easyocr
                easyocr_available = True
            except ImportError:
                pass

            self._send_json({
                "status": "ok",
                "service": "ocr",
                "device": _device,
                "languages": _languages,
                "easyocr_available": easyocr_available,
                "model_loaded": _reader is not None,
            })
        elif path == "/languages":
            self._send_json({
                "success": True,
                "configured": _languages,
                "supported": [
                    "en", "fr", "de", "es", "it", "pt", "nl", "ru", "uk",
                    "ar", "fa", "ur", "hi", "bn", "ta", "te",
                    "zh", "ja", "ko", "th", "vi",
                ],
            })
        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length) if content_length > 0 else b""

        if path == "/extract":
            self._handle_extract(body)
        elif path == "/extract_regions":
            self._handle_extract_regions(body)
        else:
            self._send_json({"error": "Not found"}, 404)

    def _handle_extract(self, body: bytes):
        try:
            req = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._send_json({"success": False, "error": f"Invalid JSON: {e}"}, 400)
            return

        try:
            img_bytes, fmt = _decode_image(req)
        except (ValueError, FileNotFoundError) as e:
            self._send_json({"success": False, "error": str(e)}, 400)
            return

        min_confidence = req.get("min_confidence", 0.0)
        paragraph = req.get("paragraph", False)

        print(f"  [ocr] Extracting text from {fmt} image ({len(img_bytes)} bytes)")

        try:
            result = _extract_text(
                img_bytes,
                min_confidence=min_confidence,
                paragraph=paragraph,
            )
            print(f"  [ocr] Found {result.get('total_regions', 0)} text regions "
                  f"in {result.get('processing_time_ms', 0)}ms")
            self._send_json(result)
        except Exception as e:
            print(f"  [ocr] Error: {e}")
            self._send_json({"success": False, "error": str(e)}, 500)

    def _handle_extract_regions(self, body: bytes):
        try:
            req = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            self._send_json({"success": False, "error": f"Invalid JSON: {e}"}, 400)
            return

        try:
            img_bytes, fmt = _decode_image(req)
        except (ValueError, FileNotFoundError) as e:
            self._send_json({"success": False, "error": str(e)}, 400)
            return

        regions = req.get("regions", [])
        if not regions:
            self._send_json({"success": False, "error": "No regions specified"}, 400)
            return

        print(f"  [ocr] Extracting text from {len(regions)} regions")

        try:
            result = _extract_regions(img_bytes, regions)
            self._send_json(result)
        except Exception as e:
            print(f"  [ocr] Error: {e}")
            self._send_json({"success": False, "error": str(e)}, 500)


# ── Main ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="OCR server for web-vox-pro")
    parser.add_argument("--port", type=int, default=21751)
    parser.add_argument("--device", choices=["cpu", "cuda", "mps"], default=None,
                        help="Override device from device_config.json")
    parser.add_argument("--preload", action="store_true",
                        help="Load OCR model immediately on startup")
    args = parser.parse_args()

    _load_config()
    if args.device:
        global _device
        _device = args.device

    if args.preload:
        _get_reader()

    server = HTTPServer(("127.0.0.1", args.port), OcrHandler)
    print(f"  [ocr] OCR server running on http://127.0.0.1:{args.port}")
    print(f"  [ocr] Device: {_device}, Languages: {_languages}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  [ocr] Shutting down.")
        server.server_close()


if __name__ == "__main__":
    main()
