import './style.css';
import {
  WebVox,
  NativeBridgeEngine,
  WebSocketTransport,
  type VoiceInfo,
  type SynthesisResult,
} from '@web-vox/core';

// @ts-ignore — lamejs has no types
import lamejs from 'lamejs';

// ── DOM refs ──────────────────────────────────────────────
const voiceSelect = document.getElementById('voice-select') as HTMLSelectElement;
const textInput = document.getElementById('text-input') as HTMLTextAreaElement;
const rateSlider = document.getElementById('rate-slider') as HTMLInputElement;
const rateValue = document.getElementById('rate-value') as HTMLSpanElement;
const rateMin = document.getElementById('rate-min') as HTMLSpanElement;
const rateMax = document.getElementById('rate-max') as HTMLSpanElement;
const rateMaxBtn = document.getElementById('rate-max-btn') as HTMLButtonElement;
const rateResetBtn = document.getElementById('rate-reset-btn') as HTMLButtonElement;
const pitchSlider = document.getElementById('pitch-slider') as HTMLInputElement;
const pitchValue = document.getElementById('pitch-value') as HTMLSpanElement;
const formatSelect = document.getElementById('format-select') as HTMLSelectElement;
const generateBtn = document.getElementById('generate-btn') as HTMLButtonElement;
const downloadBtn = document.getElementById('download-btn') as HTMLButtonElement;
const progressSection = document.getElementById('progress-section') as HTMLElement;
const progressFill = document.getElementById('progress-fill') as HTMLDivElement;
const progressText = document.getElementById('progress-text') as HTMLSpanElement;
const playerSection = document.getElementById('player-section') as HTMLElement;
const audioPlayer = document.getElementById('audio-player') as HTMLAudioElement;
const logPanel = document.getElementById('log-panel') as HTMLDivElement;
const highlightSection = document.getElementById('highlight-section') as HTMLElement;
const textDisplay = document.getElementById('text-display') as HTMLDivElement;

// ── State ─────────────────────────────────────────────────
let vox: WebVox;
let voices: VoiceInfo[] = [];
let lastBlob: Blob | null = null;
let lastFormat = 'wav';
let lastPcm: Float32Array | null = null;
let lastSampleRate = 22050;
let isGenerating = false;

// Word boundary data from TTS engine
interface WordBoundary {
  word: string;
  charOffset: number;
  charLength: number;
  startTimeMs: number;
  endTimeMs: number;
}
let lastWordBoundaries: WordBoundary[] = [];
let highlightRafId = 0;

// ── Logger ────────────────────────────────────────────────
function log(msg: string, level: 'info' | 'warn' | 'error' | 'success' = 'info') {
  const el = document.createElement('div');
  el.className = `log-entry log-${level}`;
  const t = new Date().toLocaleTimeString('en-US', { hour12: false });
  el.textContent = `[${t}] ${msg}`;
  logPanel.appendChild(el);
  logPanel.scrollTop = logPanel.scrollHeight;
}

// ── Progress helpers ──────────────────────────────────────
let progressTimer = 0;

function showProgress(estimatedMs: number) {
  progressSection.hidden = false;
  progressFill.classList.remove('indeterminate');
  progressFill.style.width = '0%';
  progressText.textContent = '0%';

  const start = performance.now();
  function tick() {
    const elapsed = performance.now() - start;
    const raw = Math.min(elapsed / estimatedMs, 1);
    const pct = Math.round(raw * 90);
    progressFill.style.width = `${pct}%`;
    progressText.textContent = `${pct}%`;
    if (raw < 1) progressTimer = requestAnimationFrame(tick);
  }
  progressTimer = requestAnimationFrame(tick);
}

function finishProgress() {
  cancelAnimationFrame(progressTimer);
  progressFill.style.width = '100%';
  progressText.textContent = '100%';
}

function hideProgress() {
  setTimeout(() => { progressSection.hidden = true; }, 1500);
}

// ── Audio encoders ────────────────────────────────────────

function encodeWav(samples: Float32Array, sampleRate: number, channels: number): Blob {
  const bps = 16;
  const blockAlign = channels * (bps / 8);
  const dataBytes = samples.length * (bps / 8);
  const buf = new ArrayBuffer(44 + dataBytes);
  const v = new DataView(buf);

  const writeStr = (off: number, s: string) => {
    for (let i = 0; i < s.length; i++) v.setUint8(off + i, s.charCodeAt(i));
  };

  writeStr(0, 'RIFF');
  v.setUint32(4, 36 + dataBytes, true);
  writeStr(8, 'WAVE');
  writeStr(12, 'fmt ');
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, channels, true);
  v.setUint32(24, sampleRate, true);
  v.setUint32(28, sampleRate * blockAlign, true);
  v.setUint16(32, blockAlign, true);
  v.setUint16(34, bps, true);
  writeStr(36, 'data');
  v.setUint32(40, dataBytes, true);

  let off = 44;
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    v.setInt16(off, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
    off += 2;
  }
  return new Blob([buf], { type: 'audio/wav' });
}

function encodeMp3(samples: Float32Array, sampleRate: number): Blob {
  // Convert float32 [-1,1] to int16
  const int16 = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }

  const encoder = new lamejs.Mp3Encoder(1, sampleRate, 128);
  const mp3Chunks: Uint8Array[] = [];
  const blockSize = 1152;

  for (let i = 0; i < int16.length; i += blockSize) {
    const chunk = int16.subarray(i, i + blockSize);
    const mp3buf = encoder.encodeBuffer(chunk);
    if (mp3buf.length > 0) mp3Chunks.push(new Uint8Array(mp3buf));
  }

  const flush = encoder.flush();
  if (flush.length > 0) mp3Chunks.push(new Uint8Array(flush));

  return new Blob(mp3Chunks, { type: 'audio/mpeg' });
}

async function encodeM4a(samples: Float32Array, sampleRate: number): Promise<Blob> {
  // Use Web Audio API → MediaRecorder to get M4A/AAC
  const ctx = new OfflineAudioContext(1, samples.length, sampleRate);
  const buffer = ctx.createBuffer(1, samples.length, sampleRate);
  buffer.getChannelData(0).set(samples);
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(ctx.destination);
  source.start();
  const rendered = await ctx.startRendering();

  // Play rendered buffer through a real AudioContext → MediaRecorder
  const realCtx = new AudioContext({ sampleRate });
  const dest = realCtx.createMediaStreamDestination();
  const realSource = realCtx.createBufferSource();
  realSource.buffer = rendered;
  realSource.connect(dest);

  // Pick best available AAC mime type
  const mimeType = MediaRecorder.isTypeSupported('audio/mp4;codecs=aac')
    ? 'audio/mp4;codecs=aac'
    : MediaRecorder.isTypeSupported('audio/mp4')
      ? 'audio/mp4'
      : MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm';

  const recorder = new MediaRecorder(dest.stream, { mimeType });
  const chunks: Blob[] = [];

  return new Promise<Blob>((resolve) => {
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunks.push(e.data);
    };
    recorder.onstop = () => {
      realCtx.close();
      const ext = mimeType.includes('mp4') ? 'audio/mp4' : 'audio/webm';
      resolve(new Blob(chunks, { type: ext }));
    };
    recorder.start();
    realSource.start();
    // Stop recording after the audio duration + small buffer
    const durationMs = (samples.length / sampleRate) * 1000;
    setTimeout(() => {
      recorder.stop();
      realSource.stop();
    }, durationMs + 100);
  });
}

async function encodeAudio(
  samples: Float32Array,
  sampleRate: number,
  format: string,
): Promise<{ blob: Blob; ext: string }> {
  switch (format) {
    case 'mp3': {
      const blob = encodeMp3(samples, sampleRate);
      return { blob, ext: 'mp3' };
    }
    case 'm4a': {
      const blob = await encodeM4a(samples, sampleRate);
      const ext = blob.type.includes('mp4') ? 'm4a' : 'webm';
      return { blob, ext };
    }
    default: {
      const blob = encodeWav(samples, sampleRate, 1);
      return { blob, ext: 'wav' };
    }
  }
}

// ── Word highlighting ─────────────────────────────────────

function buildHighlightedText(text: string, boundaries: WordBoundary[]) {
  textDisplay.innerHTML = '';
  let lastEnd = 0;

  for (let i = 0; i < boundaries.length; i++) {
    const wb = boundaries[i];
    // Gap text before this word (whitespace, punctuation)
    if (wb.charOffset > lastEnd) {
      textDisplay.appendChild(document.createTextNode(text.slice(lastEnd, wb.charOffset)));
    }
    const span = document.createElement('span');
    span.className = 'word unspoken';
    span.dataset.index = String(i);
    span.textContent = text.slice(wb.charOffset, wb.charOffset + wb.charLength);
    textDisplay.appendChild(span);
    lastEnd = wb.charOffset + wb.charLength;
  }

  // Trailing text after last word
  if (lastEnd < text.length) {
    textDisplay.appendChild(document.createTextNode(text.slice(lastEnd)));
  }

  highlightSection.hidden = false;
}

function startHighlighting() {
  const wordSpans = textDisplay.querySelectorAll('.word');
  let currentIdx = -1;

  function tick() {
    const timeMs = audioPlayer.currentTime * 1000;

    // Find the word active at this time
    let activeIdx = -1;
    for (let i = 0; i < lastWordBoundaries.length; i++) {
      if (timeMs >= lastWordBoundaries[i].startTimeMs && timeMs < lastWordBoundaries[i].endTimeMs) {
        activeIdx = i;
        break;
      }
    }

    if (activeIdx !== currentIdx) {
      if (currentIdx >= 0) {
        wordSpans[currentIdx]?.classList.remove('active');
        wordSpans[currentIdx]?.classList.add('spoken');
        wordSpans[currentIdx]?.classList.remove('unspoken');
      }
      if (activeIdx >= 0) {
        wordSpans[activeIdx]?.classList.add('active');
        wordSpans[activeIdx]?.classList.remove('unspoken');
      }
      currentIdx = activeIdx;
    }

    if (!audioPlayer.paused && !audioPlayer.ended) {
      highlightRafId = requestAnimationFrame(tick);
    } else if (audioPlayer.ended) {
      // Mark all remaining as spoken
      wordSpans.forEach((s) => {
        s.classList.remove('active', 'unspoken');
        s.classList.add('spoken');
      });
    }
  }

  highlightRafId = requestAnimationFrame(tick);
}

function stopHighlighting() {
  cancelAnimationFrame(highlightRafId);
}

// ── Initialization ────────────────────────────────────────
async function init() {
  log('Initializing WebVox with native bridge...');

  log('Probing for native bridge server on ws://localhost:21740...');
  const serverAvailable = await WebSocketTransport.probe();

  if (!serverAvailable) {
    log('Native bridge server not found.', 'error');
    log('Start it with: cargo run --bin web-vox-server', 'error');
    log('(from packages/native-bridge)', 'error');
    return;
  }

  log('Server detected', 'success');

  vox = new WebVox();
  const transport = new WebSocketTransport();
  const engine = new NativeBridgeEngine(transport);

  log('Connecting to native bridge...');
  await engine.initialize();
  vox.registerEngine('native-bridge', engine);
  log('NativeBridgeEngine connected', 'success');

  log('Fetching OS voices...');
  voices = await vox.getVoices();
  log(`Found ${voices.length} voices`, 'success');

  voiceSelect.innerHTML = '';
  for (const voice of voices) {
    const opt = document.createElement('option');
    opt.value = voice.id;
    const gender = voice.gender ? ` [${voice.gender}]` : '';
    opt.textContent = `${voice.name} (${voice.language})${gender}`;
    voiceSelect.appendChild(opt);
  }
  voiceSelect.disabled = false;

  const min = vox.getMinRate();
  const max = vox.getMaxRate();
  rateSlider.min = String(min);
  rateSlider.max = String(max);
  rateSlider.step = '0.1';
  rateMin.textContent = `${min}x`;
  rateMax.textContent = `${max}x`;
  log(`Speed range: ${min}x – ${max}x`);

  generateBtn.disabled = false;
  log('Ready — select a voice and type some text', 'success');
}

// ── Generate ──────────────────────────────────────────────
async function generate() {
  const text = textInput.value.trim();
  if (!text) {
    log('No text entered', 'warn');
    return;
  }
  if (isGenerating) return;

  isGenerating = true;
  generateBtn.textContent = 'Generating...';
  generateBtn.classList.add('generating');
  downloadBtn.disabled = true;
  playerSection.hidden = true;
  lastBlob = null;

  const voice = voiceSelect.value;
  const rate = parseFloat(rateSlider.value);
  const pitch = parseFloat(pitchSlider.value);
  const format = formatSelect.value;
  const voiceName = voiceSelect.options[voiceSelect.selectedIndex]?.text ?? voice;

  log(`Synthesizing: voice="${voiceName}", rate=${rate}x, pitch=${pitch}`);

  const wordCount = text.split(/\s+/).length;
  const estimatedMs = (wordCount / 150) * 60_000 / rate;
  showProgress(estimatedMs);

  try {
    const t0 = performance.now();
    const result: SynthesisResult = await vox.synthesize(text, {
      voice,
      rate,
      pitch,
      engine: 'native-bridge',
    });
    const elapsed = Math.round(performance.now() - t0);

    finishProgress();
    log(`Synthesis complete in ${elapsed}ms`, 'success');
    log(`Words: ${result.metadata.wordTimestamps.length}, duration: ${Math.round(result.metadata.totalDurationMs)}ms`);

    // Store word boundaries from TTS engine
    lastWordBoundaries = result.metadata.wordTimestamps.map((wt) => ({
      word: wt.word,
      charOffset: wt.charOffset,
      charLength: wt.charLength,
      startTimeMs: wt.startTimeMs,
      endTimeMs: wt.endTimeMs,
    }));

    if (lastWordBoundaries.length > 0) {
      log(`Word boundaries: ${lastWordBoundaries.length} from TTS engine`, 'success');
      buildHighlightedText(text, lastWordBoundaries);
    } else {
      log('No word boundary data received from engine', 'warn');
      highlightSection.hidden = true;
    }

    if (result.rawPcm && result.rawPcm.length > 0) {
      lastPcm = result.rawPcm;
      lastSampleRate = result.metadata.sampleRate;
      log(`Captured ${result.rawPcm.length} PCM samples @ ${result.metadata.sampleRate}Hz`);

      log(`Encoding to ${format.toUpperCase()}...`);
      const { blob, ext } = await encodeAudio(result.rawPcm, result.metadata.sampleRate, format);
      lastBlob = blob;
      lastFormat = ext;

      const url = URL.createObjectURL(blob);
      audioPlayer.src = url;
      playerSection.hidden = false;
      downloadBtn.disabled = false;
      log(`${ext.toUpperCase()} file ready (${(blob.size / 1024).toFixed(1)} KB)`, 'success');
    } else {
      log('No audio samples captured — check server logs', 'warn');
    }
  } catch (err) {
    finishProgress();
    log(`Synthesis failed: ${err instanceof Error ? err.message : err}`, 'error');
  } finally {
    hideProgress();
    isGenerating = false;
    generateBtn.textContent = 'Generate';
    generateBtn.classList.remove('generating');
  }
}

// ── Re-encode when format changes (if we already have PCM) ──
async function onFormatChange() {
  const format = formatSelect.value;
  if (!lastPcm || lastPcm.length === 0) return;

  log(`Re-encoding to ${format.toUpperCase()}...`);
  try {
    const { blob, ext } = await encodeAudio(lastPcm, lastSampleRate, format);
    lastBlob = blob;
    lastFormat = ext;
    const url = URL.createObjectURL(blob);
    audioPlayer.src = url;
    playerSection.hidden = false;
    downloadBtn.disabled = false;
    log(`${ext.toUpperCase()} file ready (${(blob.size / 1024).toFixed(1)} KB)`, 'success');
  } catch (err) {
    log(`Encoding failed: ${err instanceof Error ? err.message : err}`, 'error');
  }
}

// ── Download ──────────────────────────────────────────────
function download() {
  if (!lastBlob) return;
  const a = document.createElement('a');
  a.href = URL.createObjectURL(lastBlob);
  a.download = `webvox-${Date.now()}.${lastFormat}`;
  a.click();
  URL.revokeObjectURL(a.href);
  log(`Downloaded ${a.download}`, 'success');
}

// ── Event listeners ───────────────────────────────────────
rateSlider.addEventListener('input', () => {
  rateValue.textContent = parseFloat(rateSlider.value).toFixed(1);
});

pitchSlider.addEventListener('input', () => {
  pitchValue.textContent = parseFloat(pitchSlider.value).toFixed(1);
});

voiceSelect.addEventListener('change', () => {
  const name = voiceSelect.options[voiceSelect.selectedIndex]?.text;
  log(`Voice: ${name}`);
});

textInput.addEventListener('input', () => {
  generateBtn.disabled = textInput.value.trim().length === 0;
});

rateMaxBtn.addEventListener('click', () => {
  const max = vox.getMaxRate();
  rateSlider.value = String(max);
  rateValue.textContent = max.toFixed(1);
  log(`Speed set to maximum: ${max}x`, 'success');
});

rateResetBtn.addEventListener('click', () => {
  rateSlider.value = '1.0';
  rateValue.textContent = '1.0';
  log('Speed reset to 1.0x');
});

audioPlayer.addEventListener('play', () => {
  if (lastWordBoundaries.length > 0) startHighlighting();
});

audioPlayer.addEventListener('pause', stopHighlighting);
audioPlayer.addEventListener('ended', stopHighlighting);
audioPlayer.addEventListener('seeked', () => {
  // Reset highlighting state on seek — let the rAF loop pick up the new position
  if (!audioPlayer.paused && lastWordBoundaries.length > 0) {
    stopHighlighting();
    startHighlighting();
  }
});

formatSelect.addEventListener('change', onFormatChange);
generateBtn.addEventListener('click', generate);
downloadBtn.addEventListener('click', download);

// ── Boot ──────────────────────────────────────────────────
init().catch((err) => log(`Init failed: ${err}`, 'error'));
