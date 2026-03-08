#!/usr/bin/env bash
# Downloads / installs test TTS engines for web-vox.
# Run from the repo root:  bash test-engines/setup.sh

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== web-vox test-engines setup ==="
echo ""

# ── 1. Piper TTS ──────────────────────────────────────────
PIPER_DIR="$SCRIPT_DIR/piper"
PIPER_VERSION="2023.11.14-2"
PIPER1_GPL_VERSION="1.4.1"

# Detect architecture
ARCH=$(uname -m)

if [ -x "$PIPER_DIR/piper" ]; then
  echo "[piper] Already installed at $PIPER_DIR/piper"
else
  mkdir -p "$PIPER_DIR"
  if [ "$ARCH" = "arm64" ] && [ "$(uname -s)" = "Darwin" ]; then
    # rhasspy/piper's macos_aarch64 release contains an x86_64 binary (upstream bug).
    # Use OHF-Voice/piper1-gpl Python wheel instead — it ships a native ARM64 build.
    VENV_DIR="$SCRIPT_DIR/piper-venv"
    WHEEL_URL="https://github.com/OHF-Voice/piper1-gpl/releases/download/v${PIPER1_GPL_VERSION}/piper_tts-${PIPER1_GPL_VERSION}-cp39-abi3-macosx_11_0_arm64.whl"
    echo "[piper] macOS ARM64 detected — installing via Python venv (OHF-Voice/piper1-gpl v${PIPER1_GPL_VERSION})..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install --quiet "$WHEEL_URL" pathvalidate
    # Create a thin wrapper so the rest of the code can call test-engines/piper/piper as normal
    cat > "$PIPER_DIR/piper" << 'WRAPPER'
#!/usr/bin/env bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$SCRIPT_DIR/../piper-venv/bin/piper" "$@"
WRAPPER
    chmod +x "$PIPER_DIR/piper"
    echo "[piper] Installed (ARM64 venv wrapper) at $PIPER_DIR/piper"
  else
    if [ "$ARCH" = "arm64" ]; then
      PIPER_ARCHIVE="piper_macos_aarch64.tar.gz"
    else
      PIPER_ARCHIVE="piper_macos_x64.tar.gz"
    fi
    PIPER_URL="https://github.com/rhasspy/piper/releases/download/${PIPER_VERSION}/${PIPER_ARCHIVE}"
    echo "[piper] Downloading ${PIPER_ARCHIVE}..."
    curl -L "$PIPER_URL" -o "$PIPER_DIR/piper.tar.gz"
    echo "[piper] Extracting..."
    tar -xzf "$PIPER_DIR/piper.tar.gz" -C "$PIPER_DIR" --strip-components=1
    rm "$PIPER_DIR/piper.tar.gz"
    chmod +x "$PIPER_DIR/piper"
    echo "[piper] Installed to $PIPER_DIR/piper"
  fi
fi

# Download a voice model (en_US-lessac-medium — good quality, ~60MB)
VOICE_DIR="$PIPER_DIR/voices"
VOICE_NAME="en_US-lessac-medium"
VOICE_ONNX="$VOICE_DIR/${VOICE_NAME}.onnx"
VOICE_JSON="$VOICE_DIR/${VOICE_NAME}.onnx.json"
HF_BASE="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"

if [ -f "$VOICE_ONNX" ] && [ -f "$VOICE_JSON" ]; then
  echo "[piper] Voice model '$VOICE_NAME' already downloaded"
else
  mkdir -p "$VOICE_DIR"
  echo "[piper] Downloading voice model: $VOICE_NAME (~60MB)..."
  curl -L "${HF_BASE}/${VOICE_NAME}.onnx" -o "$VOICE_ONNX"
  curl -L "${HF_BASE}/${VOICE_NAME}.onnx.json" -o "$VOICE_JSON"
  echo "[piper] Voice model ready"
fi

# Also grab a smaller/different voice for variety
VOICE2_NAME="en_US-amy-low"
VOICE2_ONNX="$VOICE_DIR/${VOICE2_NAME}.onnx"
VOICE2_JSON="$VOICE_DIR/${VOICE2_NAME}.onnx.json"
HF_BASE2="https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/low"

if [ -f "$VOICE2_ONNX" ] && [ -f "$VOICE2_JSON" ]; then
  echo "[piper] Voice model '$VOICE2_NAME' already downloaded"
else
  echo "[piper] Downloading voice model: $VOICE2_NAME (~15MB)..."
  curl -L "${HF_BASE2}/${VOICE2_NAME}.onnx" -o "$VOICE2_ONNX"
  curl -L "${HF_BASE2}/${VOICE2_NAME}.onnx.json" -o "$VOICE2_JSON"
  echo "[piper] Voice model ready"
fi

echo ""

# ── 2. espeak-ng ──────────────────────────────────────────
if command -v espeak-ng &>/dev/null; then
  echo "[espeak-ng] Already installed: $(which espeak-ng)"
else
  echo "[espeak-ng] Installing via Homebrew..."
  if ! command -v brew &>/dev/null; then
    echo "[espeak-ng] ERROR: Homebrew not found. Install it from https://brew.sh"
    exit 1
  fi
  brew install espeak-ng
  echo "[espeak-ng] Installed: $(which espeak-ng)"
fi

echo ""
echo "=== Setup complete ==="
echo ""
echo "Piper binary:  $PIPER_DIR/piper"
echo "Piper voices:  $VOICE_DIR/"
echo "espeak-ng:     $(which espeak-ng)"
echo ""
echo "Now rebuild the server:  cargo build --bin web-vox-server"
