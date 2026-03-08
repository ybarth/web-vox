import './style.css';
import {
  WebVox,
  NativeBridgeEngine,
  WebSocketTransport,
  type VoiceInfo,
  type SynthesisResult,
  type SystemInfo,
  type PiperCatalogVoice,
  type VoiceSampleInfo,
  type ServerProcessStats,
  type DocumentAnalysisResult,
  type DocumentElement,
} from '@web-vox/core';

// @ts-ignore — lamejs has no types
import lamejs from 'lamejs';

// ── DOM refs ──────────────────────────────────────────────
const voiceSearch = document.getElementById('voice-search') as HTMLInputElement;
const refreshVoicesBtn = document.getElementById('refresh-voices-btn') as HTMLButtonElement;
const showFavoritesBtn = document.getElementById('show-favorites-btn') as HTMLButtonElement;
const voiceList = document.getElementById('voice-list') as HTMLDivElement;
const filterLanguage = document.getElementById('filter-language') as HTMLSelectElement;
const filterEngine = document.getElementById('filter-engine') as HTMLSelectElement;
const voiceSelectedDisplay = document.getElementById('voice-selected-display') as HTMLDivElement;
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
const alignmentSelect = document.getElementById('alignment-select') as HTMLSelectElement;
const qualityCheck = document.getElementById('quality-check') as HTMLInputElement;
const qualitySection = document.getElementById('quality-section') as HTMLElement;
const qualityGrid = document.getElementById('quality-grid') as HTMLDivElement;
const qualityRecommendations = document.getElementById('quality-recommendations') as HTMLDivElement;
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
const systemInfoBar = document.getElementById('system-info-bar') as HTMLDivElement;

// Context menu
const contextMenu = document.getElementById('voice-context-menu') as HTMLDivElement;
const contextMenuHeader = document.getElementById('context-menu-header') as HTMLDivElement;
const contextMenuBody = document.getElementById('context-menu-body') as HTMLDivElement;
const contextMenuValidate = document.getElementById('context-menu-validate') as HTMLButtonElement;
const contextMenuClose = document.getElementById('context-menu-close') as HTMLButtonElement;

// Piper modal
const piperModal = document.getElementById('piper-modal') as HTMLDivElement;
const piperSearch = document.getElementById('piper-search') as HTMLInputElement;
const piperLangFilter = document.getElementById('piper-lang-filter') as HTMLSelectElement;
const piperQualityFilter = document.getElementById('piper-quality-filter') as HTMLSelectElement;
const piperCatalogList = document.getElementById('piper-catalog-list') as HTMLDivElement;
const piperStatus = document.getElementById('piper-status') as HTMLSpanElement;
const piperModalClose = document.getElementById('piper-modal-close') as HTMLButtonElement;
const piperDownloadBtn = document.getElementById('piper-download-btn') as HTMLButtonElement;

// Voice sample modal
const voiceSampleBtn = document.getElementById('voice-sample-btn') as HTMLButtonElement;
const sampleModal = document.getElementById('sample-modal') as HTMLDivElement;
const sampleNameInput = document.getElementById('sample-name-input') as HTMLInputElement;
const sampleRecordBtn = document.getElementById('sample-record-btn') as HTMLButtonElement;
const sampleStopBtn = document.getElementById('sample-stop-btn') as HTMLButtonElement;
const sampleRecordStatus = document.getElementById('sample-record-status') as HTMLDivElement;
const samplePreviewSection = document.getElementById('sample-preview-section') as HTMLElement;
const samplePreviewPlayer = document.getElementById('sample-preview-player') as HTMLAudioElement;
const sampleSaveBtn = document.getElementById('sample-save-btn') as HTMLButtonElement;
const sampleFileInput = document.getElementById('sample-file-input') as HTMLInputElement;
const sampleUploadBtn = document.getElementById('sample-upload-btn') as HTMLButtonElement;
const sampleList = document.getElementById('sample-list') as HTMLDivElement;
const sampleStatus = document.getElementById('sample-status') as HTMLSpanElement;
const sampleModalClose = document.getElementById('sample-modal-close') as HTMLButtonElement;
const cloneEngineSelect = document.getElementById('clone-engine-select') as HTMLSelectElement;

// Stack status bar
const stackDotWs = document.getElementById('stack-dot-ws') as HTMLSpanElement;
const stackDotAlignment = document.getElementById('stack-dot-alignment') as HTMLSpanElement;
const stackDotQuality = document.getElementById('stack-dot-quality') as HTMLSpanElement;
const stackDotDocAnalyzer = document.getElementById('stack-dot-doc-analyzer') as HTMLSpanElement;
const stackSummary = document.getElementById('stack-summary') as HTMLSpanElement;

// Server dashboard
const serverDashboardBtn = document.getElementById('server-dashboard-btn') as HTMLButtonElement;
const serverDashboard = document.getElementById('server-dashboard') as HTMLDivElement;
const serverDashboardBody = document.getElementById('server-dashboard-body') as HTMLDivElement;
const serverDashboardStatus = document.getElementById('server-dashboard-status') as HTMLSpanElement;
const serverDashboardRefresh = document.getElementById('server-dashboard-refresh') as HTMLButtonElement;
const serverDashboardClose = document.getElementById('server-dashboard-close') as HTMLButtonElement;

// Error dialog
const errorDialog = document.getElementById('error-dialog') as HTMLDivElement;
const errorDialogTitle = document.getElementById('error-dialog-title') as HTMLHeadingElement;
const errorDialogBody = document.getElementById('error-dialog-body') as HTMLDivElement;
const errorDialogClose = document.getElementById('error-dialog-close') as HTMLButtonElement;

// ── State ─────────────────────────────────────────────────
let vox: WebVox;
let nativeEngine: NativeBridgeEngine;
let voices: VoiceInfo[] = [];
let selectedVoiceId: string | null = null;
let lastBlob: Blob | null = null;
let lastFormat = 'wav';
let lastPcm: Float32Array | null = null;
let lastSampleRate = 22050;
let isGenerating = false;
let showingFavoritesOnly = false;
let systemInfo: SystemInfo | null = null;

// Favorites persisted in localStorage
const FAVORITES_KEY = 'webvox-favorite-voices';
function getFavorites(): Set<string> {
  try {
    const raw = localStorage.getItem(FAVORITES_KEY);
    return raw ? new Set(JSON.parse(raw)) : new Set();
  } catch { return new Set(); }
}
function saveFavorites(favs: Set<string>) {
  localStorage.setItem(FAVORITES_KEY, JSON.stringify([...favs]));
}
let favorites = getFavorites();

// Failed voices tracking (voices that failed validation)
const failedVoices = new Map<string, string>(); // voiceId -> error message

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

// Context menu state
let contextMenuVoiceId: string | null = null;

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
    // Asymptotic curve: moves quickly at first, then slows but never freezes.
    // Approaches 99% but never reaches it, so progress always appears alive.
    const pct = Math.round((1 - Math.exp(-2 * elapsed / estimatedMs)) * 99);
    progressFill.style.width = `${pct}%`;
    progressText.textContent = `${pct}%`;
    if (pct < 99) progressTimer = requestAnimationFrame(tick);
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
  const int16 = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
  }

  const encoder = new lamejs.Mp3Encoder(1, sampleRate, 128);
  const mp3Chunks: BlobPart[] = [];
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
  const ctx = new OfflineAudioContext(1, samples.length, sampleRate);
  const buffer = ctx.createBuffer(1, samples.length, sampleRate);
  buffer.getChannelData(0).set(samples);
  const source = ctx.createBufferSource();
  source.buffer = buffer;
  source.connect(ctx.destination);
  source.start();
  const rendered = await ctx.startRendering();

  const realCtx = new AudioContext({ sampleRate });
  const dest = realCtx.createMediaStreamDestination();
  const realSource = realCtx.createBufferSource();
  realSource.buffer = rendered;
  realSource.connect(dest);

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

// ── Voice Picker ──────────────────────────────────────────

function getEngineClass(engine: string): string {
  if (engine.includes('macos') || engine.includes('avspeech')) return 'engine-macos';
  if (engine.includes('piper')) return 'engine-piper';
  if (engine.includes('espeak')) return 'engine-espeak';
  if (engine.includes('chatterbox')) return 'engine-chatterbox';
  if (engine.includes('kokoro')) return 'engine-kokoro';
  if (engine.includes('coqui-xtts')) return 'engine-coqui-xtts';
  if (engine.includes('coqui')) return 'engine-coqui';
  if (engine.includes('qwen-clone')) return 'engine-qwen-clone';
  if (engine.includes('qwen')) return 'engine-qwen';
  return '';
}

function getEngineLabel(engine: string): string {
  if (engine.includes('macos') || engine.includes('avspeech')) return 'macOS';
  if (engine.includes('piper')) return 'Piper';
  if (engine.includes('espeak')) return 'eSpeak';
  if (engine.includes('chatterbox')) return 'Chatterbox';
  if (engine.includes('kokoro')) return 'Kokoro';
  if (engine.includes('coqui-xtts')) return 'XTTS Clone';
  if (engine.includes('coqui')) return 'Coqui';
  if (engine.includes('qwen-clone')) return 'Qwen Clone';
  if (engine.includes('qwen')) return 'Qwen';
  return engine;
}

function getQualityClass(quality?: string): string {
  if (!quality) return '';
  if (quality === 'premium' || quality === 'enhanced') return 'quality-premium';
  if (quality === 'neural' || quality === 'neural-clone') return 'quality-neural';
  if (quality === 'compact') return 'quality-compact';
  return '';
}

function populateFilters() {
  const languages = [...new Set(voices.map(v => v.language))].sort();
  const engines = [...new Set(voices.map(v => v.engine))].sort();

  filterLanguage.innerHTML = '<option value="">All Languages</option>';
  for (const lang of languages) {
    const opt = document.createElement('option');
    opt.value = lang;
    opt.textContent = lang;
    filterLanguage.appendChild(opt);
  }

  filterEngine.innerHTML = '<option value="">All Engines</option>';
  for (const eng of engines) {
    const opt = document.createElement('option');
    opt.value = eng;
    opt.textContent = getEngineLabel(eng);
    filterEngine.appendChild(opt);
  }
}

function renderVoiceList() {
  const query = voiceSearch.value.toLowerCase().trim();
  const langFilter = filterLanguage.value;
  const engineFilter = filterEngine.value;
  const filtered = voices.filter(v => {
    if (showingFavoritesOnly && !favorites.has(v.id)) return false;
    if (langFilter && v.language !== langFilter) return false;
    if (engineFilter && v.engine !== engineFilter) return false;
    if (!query) return true;
    return v.name.toLowerCase().includes(query)
      || v.language.toLowerCase().includes(query)
      || v.engine.toLowerCase().includes(query)
      || (v.gender && v.gender.toLowerCase().includes(query))
      || v.id.toLowerCase().includes(query);
  });

  // Sort: favorites first, then by name
  filtered.sort((a, b) => {
    const aFav = favorites.has(a.id) ? 0 : 1;
    const bFav = favorites.has(b.id) ? 0 : 1;
    if (aFav !== bFav) return aFav - bFav;
    return a.name.localeCompare(b.name);
  });

  voiceList.innerHTML = '';

  if (filtered.length === 0) {
    const empty = document.createElement('div');
    empty.className = 'voice-list-empty';
    empty.textContent = showingFavoritesOnly
      ? 'No favorite voices. Click the star on a voice to add it.'
      : 'No voices match your search.';
    voiceList.appendChild(empty);
    return;
  }

  for (const voice of filtered) {
    const item = document.createElement('div');
    item.className = 'voice-item';
    if (voice.id === selectedVoiceId) item.classList.add('selected');
    item.dataset.voiceId = voice.id;

    // Favorite button
    const favBtn = document.createElement('button');
    favBtn.type = 'button';
    favBtn.className = 'voice-fav-btn';
    if (favorites.has(voice.id)) favBtn.classList.add('is-favorite');
    favBtn.innerHTML = favorites.has(voice.id) ? '&#9733;' : '&#9734;';
    favBtn.title = favorites.has(voice.id) ? 'Remove from favorites' : 'Add to favorites';
    favBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleFavorite(voice.id);
    });

    // Name
    const nameSpan = document.createElement('span');
    nameSpan.className = 'voice-name';
    nameSpan.textContent = voice.name;

    // Language
    const langSpan = document.createElement('span');
    langSpan.className = 'voice-lang';
    langSpan.textContent = voice.language;

    // Gender
    const genderSpan = document.createElement('span');
    genderSpan.className = 'voice-gender';
    genderSpan.textContent = voice.gender ?? '';

    // Engine badge
    const engineBadge = document.createElement('span');
    engineBadge.className = `voice-engine-badge ${getEngineClass(voice.engine)}`;
    engineBadge.textContent = getEngineLabel(voice.engine);

    // Quality badge
    if (voice.quality) {
      const qualityBadge = document.createElement('span');
      qualityBadge.className = `voice-quality-badge ${getQualityClass(voice.quality)}`;
      qualityBadge.textContent = voice.quality;
      item.appendChild(favBtn);
      item.appendChild(nameSpan);
      item.appendChild(langSpan);
      item.appendChild(genderSpan);
      item.appendChild(qualityBadge);
      item.appendChild(engineBadge);
    } else {
      item.appendChild(favBtn);
      item.appendChild(nameSpan);
      item.appendChild(langSpan);
      item.appendChild(genderSpan);
      item.appendChild(engineBadge);
    }

    // Left-click to select
    item.addEventListener('click', () => selectVoice(voice.id));

    // Right-click for context menu
    item.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      showVoiceContextMenu(voice);
    });

    voiceList.appendChild(item);
  }
}

function selectVoice(voiceId: string) {
  selectedVoiceId = voiceId;
  const voice = voices.find(v => v.id === voiceId);
  if (voice) {
    voiceSelectedDisplay.innerHTML = `Selected: <span class="selected-voice-name">${voice.name}</span> (${voice.language})`;
    log(`Voice: ${voice.name}`);
  }
  generateBtn.disabled = textInput.value.trim().length === 0;
  renderVoiceList();
}

function toggleFavorite(voiceId: string) {
  if (favorites.has(voiceId)) {
    favorites.delete(voiceId);
  } else {
    favorites.add(voiceId);
  }
  saveFavorites(favorites);
  renderVoiceList();
}

// ── Voice Context Menu (right-click) ──────────────────────

function showVoiceContextMenu(voice: VoiceInfo) {
  contextMenuVoiceId = voice.id;
  contextMenuHeader.textContent = voice.name;

  const rows = [
    { label: 'ID', value: voice.id },
    { label: 'Language', value: voice.language },
    { label: 'Gender', value: voice.gender ?? 'Unknown' },
    { label: 'Engine', value: voice.engine },
    { label: 'Quality', value: voice.quality ?? 'Standard' },
    { label: 'Sample Rate', value: voice.sampleRate ? `${voice.sampleRate} Hz` : 'Default' },
    { label: 'Description', value: voice.description ?? 'No description available' },
  ];

  let html = '';
  for (const row of rows) {
    html += `<div class="detail-row"><span class="detail-label">${row.label}</span><span class="detail-value">${row.value}</span></div>`;
  }

  // Show cached validation result if available
  if (failedVoices.has(voice.id)) {
    html += `<div class="validation-result invalid">Previously failed: ${failedVoices.get(voice.id)}</div>`;
  }

  contextMenuBody.innerHTML = html;
  contextMenuValidate.disabled = false;
  contextMenuValidate.textContent = 'Validate Voice';
  contextMenu.hidden = false;
}

function hideContextMenu() {
  contextMenu.hidden = true;
  contextMenuVoiceId = null;
}

async function validateContextMenuVoice() {
  if (!contextMenuVoiceId) return;
  contextMenuValidate.disabled = true;
  contextMenuValidate.textContent = 'Validating...';

  try {
    const result = await nativeEngine.validateVoice(contextMenuVoiceId);
    const existing = contextMenuBody.querySelector('.validation-result');
    if (existing) existing.remove();

    const div = document.createElement('div');
    if (result.valid) {
      div.className = 'validation-result valid';
      div.textContent = 'Voice is properly installed and working.';
      failedVoices.delete(contextMenuVoiceId);
    } else {
      div.className = 'validation-result invalid';
      div.innerHTML = `Error: ${result.error ?? 'Unknown error'}`;
      if (result.suggestion) {
        div.innerHTML += `<span class="suggestion">${result.suggestion}</span>`;
      }
      failedVoices.set(contextMenuVoiceId, result.error ?? 'Validation failed');
    }
    contextMenuBody.appendChild(div);
  } catch (err) {
    const div = document.createElement('div');
    div.className = 'validation-result invalid';
    div.textContent = `Validation request failed: ${err instanceof Error ? err.message : err}`;
    contextMenuBody.appendChild(div);
  } finally {
    contextMenuValidate.disabled = false;
    contextMenuValidate.textContent = 'Validate Voice';
  }
}

// ── Error Dialog ──────────────────────────────────────────

function showErrorDialog(title: string, errorMsg: string, suggestion?: string) {
  errorDialogTitle.textContent = title;

  let html = `<p>The selected voice could not complete synthesis.</p>`;
  html += `<div class="error-detail">${errorMsg}</div>`;

  if (suggestion) {
    html += `<div class="error-suggestion">${suggestion}</div>`;
  }

  if (systemInfo) {
    html += `<div class="system-context">`;
    html += `System: ${systemInfo.os} ${systemInfo.osVersion} (${systemInfo.arch})`;
    html += `<br>Available engines: ${systemInfo.availableEngines.join(', ') || 'none'}`;
    html += `</div>`;
  }

  errorDialogBody.innerHTML = html;
  errorDialog.hidden = false;
}

function hideErrorDialog() {
  errorDialog.hidden = true;
}

// ── System Info ───────────────────────────────────────────

function renderSystemInfo(info: SystemInfo) {
  systemInfoBar.innerHTML = '';
  const items = [
    { label: 'OS', value: `${info.os} ${info.osVersion}` },
    { label: 'Arch', value: info.arch },
    { label: 'Cores', value: String(info.cpuCores) },
    { label: 'Engines', value: info.availableEngines.join(', ') || 'none' },
  ];
  for (const item of items) {
    const el = document.createElement('span');
    el.className = 'info-item';
    el.innerHTML = `<span class="info-label">${item.label}:</span> ${item.value}`;
    systemInfoBar.appendChild(el);
  }
  systemInfoBar.hidden = false;
}

// ── Classify synthesis errors ─────────────────────────────

function classifySynthesisError(errorMsg: string, voiceId: string): { title: string; suggestion?: string } {
  const msg = errorMsg.toLowerCase();

  if (msg.includes('voice not found') || msg.includes('voicenotfound')) {
    return {
      title: 'Voice Not Found',
      suggestion: getVoiceInstallSuggestion(voiceId),
    };
  }

  if (msg.includes('not available') || msg.includes('notavailable')) {
    return {
      title: 'Engine Not Available',
      suggestion: getEngineInstallSuggestion(voiceId),
    };
  }

  if (msg.includes('synthesis failed') || msg.includes('synthesisfailed')) {
    return {
      title: 'Synthesis Failed',
      suggestion: `The voice "${voiceId}" encountered an error during synthesis. ` +
        'Try selecting a different voice, or right-click the voice to validate it.',
    };
  }

  if (msg.includes('platform error') || msg.includes('platformerror')) {
    return {
      title: 'Platform Error',
      suggestion: 'This error is related to your operating system. ' +
        'Ensure your OS is up to date and the required TTS components are installed.',
    };
  }

  return { title: 'Synthesis Error' };
}

function getVoiceInstallSuggestion(voiceId: string): string {
  if (voiceId.startsWith('chatterbox:')) {
    return 'Ensure the Chatterbox server is running: ' +
      'cd packages/native-bridge && python3 chatterbox_server.py';
  }
  if (voiceId.startsWith('piper:')) {
    return 'This Piper voice model is not installed. Download .onnx model files ' +
      'from the Piper releases page and place them in test-engines/piper/voices/.';
  }
  if (voiceId.startsWith('espeak-ng:')) {
    return 'This eSpeak-NG voice is not available. Ensure espeak-ng is installed: ' +
      'brew install espeak-ng (macOS) or apt install espeak-ng (Linux).';
  }
  if (voiceId.startsWith('kokoro:')) {
    return 'Ensure the Kokoro server is running: ' +
      'cd packages/native-bridge && python3 kokoro_server.py';
  }
  if (voiceId.startsWith('coqui-xtts:')) {
    return 'Ensure the Coqui XTTS server is running: ' +
      'cd packages/native-bridge && python3 coqui_xtts_server.py';
  }
  if (voiceId.startsWith('coqui:')) {
    return 'Ensure the Coqui TTS server is running: ' +
      'cd packages/native-bridge && python3 coqui_server.py';
  }
  if (voiceId.startsWith('qwen-clone:')) {
    return 'Ensure the Qwen3-TTS Clone server is running: ' +
      'cd packages/native-bridge && python3.12 qwen_tts_clone_server.py';
  }
  if (voiceId.startsWith('qwen:')) {
    return 'Ensure the Qwen3-TTS server is running: ' +
      'cd packages/native-bridge && python3.12 qwen_tts_server.py';
  }
  // macOS voice
  if (systemInfo?.os === 'macos') {
    return 'This macOS voice may need to be downloaded. Go to System Settings > ' +
      'Accessibility > Spoken Content > System Voice > Manage Voices to install it.';
  }
  return 'This voice may not be properly installed on your system.';
}

function getEngineInstallSuggestion(voiceId: string): string {
  if (voiceId.startsWith('chatterbox:')) {
    return 'The Chatterbox TTS server is not running. Start it with: ' +
      'cd packages/native-bridge && python3 chatterbox_server.py';
  }
  if (voiceId.startsWith('piper:')) {
    return 'The Piper TTS engine is not available. Ensure the piper binary exists ' +
      'at test-engines/piper/piper.';
  }
  if (voiceId.startsWith('espeak-ng:')) {
    return 'eSpeak-NG is not installed. Install it with: brew install espeak-ng (macOS) ' +
      'or apt install espeak-ng (Linux).';
  }
  if (voiceId.startsWith('kokoro:')) {
    return 'The Kokoro TTS server is not running. Start it with: ' +
      'cd packages/native-bridge && python3 kokoro_server.py';
  }
  if (voiceId.startsWith('coqui-xtts:')) {
    return 'The Coqui XTTS server is not running. Start it with: ' +
      'cd packages/native-bridge && python3 coqui_xtts_server.py';
  }
  if (voiceId.startsWith('coqui:')) {
    return 'The Coqui TTS server is not running. Start it with: ' +
      'cd packages/native-bridge && python3 coqui_server.py';
  }
  if (voiceId.startsWith('qwen-clone:')) {
    return 'The Qwen3-TTS Clone server is not running. Start it with: ' +
      'cd packages/native-bridge && python3.12 qwen_tts_clone_server.py';
  }
  if (voiceId.startsWith('qwen:')) {
    return 'The Qwen3-TTS server is not running. Start it with: ' +
      'cd packages/native-bridge && python3.12 qwen_tts_server.py';
  }
  return 'The TTS engine for this voice is not available on your system.';
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
  nativeEngine = new NativeBridgeEngine(transport);

  log('Connecting to native bridge...');
  await nativeEngine.initialize();
  vox.registerEngine('native-bridge', nativeEngine);
  log('NativeBridgeEngine connected', 'success');

  // Fetch system info first (sequential to avoid id-less response race)
  try {
    systemInfo = await nativeEngine.getSystemInfo();
    renderSystemInfo(systemInfo);
    log(`System: ${systemInfo.os} ${systemInfo.osVersion} (${systemInfo.arch}), ${systemInfo.cpuCores} cores`);
    log(`Available engines: ${systemInfo.availableEngines.join(', ')}`);
  } catch (err) {
    log(`Could not fetch system info: ${err}`, 'warn');
  }

  log('Fetching OS voices...');
  voices = await vox.getVoices();
  log(`Found ${voices.length} voices`, 'success');

  populateFilters();
  renderVoiceList();

  // Auto-select first voice
  if (voices.length > 0) {
    // Prefer a favorite, otherwise first
    const firstFav = voices.find(v => favorites.has(v.id));
    selectVoice(firstFav?.id ?? voices[0].id);
  }

  const min = vox.getMinRate();
  const max = vox.getMaxRate();
  rateSlider.min = String(min);
  rateSlider.max = String(max);
  rateSlider.step = '0.1';
  rateMin.textContent = `${min}x`;
  rateMax.textContent = `${max}x`;
  log(`Speed range: ${min}x - ${max}x`);

  generateBtn.disabled = textInput.value.trim().length === 0;
  log('Ready - select a voice and type some text', 'success');
}

// ── Piper Voice Catalog ───────────────────────────────────
let piperCatalog: PiperCatalogVoice[] = [];
let piperDownloading = new Set<string>();
let piperNewlyDownloaded = false;

async function openPiperModal() {
  piperModal.hidden = false;
  piperNewlyDownloaded = false;
  piperCatalogList.innerHTML = '<div class="piper-loading">Loading catalog...</div>';
  piperStatus.textContent = '';
  piperSearch.value = '';
  piperLangFilter.innerHTML = '<option value="">All Languages</option>';
  piperQualityFilter.innerHTML = '<option value="">All Qualities</option>';

  try {
    log('Fetching Piper voice catalog...');
    piperCatalog = await nativeEngine.listPiperCatalog();
    log(`Piper catalog: ${piperCatalog.length} voices available`, 'success');

    // Populate filters
    const languages = [...new Set(piperCatalog.map(v => v.language_name || v.language))].sort();
    for (const lang of languages) {
      const opt = document.createElement('option');
      opt.value = lang;
      opt.textContent = lang;
      piperLangFilter.appendChild(opt);
    }

    const qualities = [...new Set(piperCatalog.map(v => v.quality))].sort();
    for (const q of qualities) {
      const opt = document.createElement('option');
      opt.value = q;
      opt.textContent = q;
      piperQualityFilter.appendChild(opt);
    }

    renderPiperCatalog();
  } catch (err) {
    piperCatalogList.innerHTML = `<div class="piper-empty">Failed to load catalog: ${err instanceof Error ? err.message : err}</div>`;
    log(`Failed to fetch Piper catalog: ${err instanceof Error ? err.message : err}`, 'error');
  }
}

function renderPiperCatalog() {
  const query = piperSearch.value.toLowerCase().trim();
  const langFilter = piperLangFilter.value;
  const qualityFilter = piperQualityFilter.value;

  const filtered = piperCatalog.filter(v => {
    if (langFilter && (v.language_name || v.language) !== langFilter) return false;
    if (qualityFilter && v.quality !== qualityFilter) return false;
    if (!query) return true;
    return v.name.toLowerCase().includes(query)
      || v.key.toLowerCase().includes(query)
      || v.language.toLowerCase().includes(query)
      || v.language_name.toLowerCase().includes(query);
  });

  piperCatalogList.innerHTML = '';

  if (filtered.length === 0) {
    piperCatalogList.innerHTML = '<div class="piper-empty">No voices match your search.</div>';
    return;
  }

  for (const voice of filtered) {
    const row = document.createElement('div');
    row.className = 'piper-voice-row';

    const nameSpan = document.createElement('span');
    nameSpan.className = 'piper-voice-name';
    nameSpan.textContent = voice.key;
    nameSpan.title = voice.key;

    const langSpan = document.createElement('span');
    langSpan.className = 'piper-voice-lang';
    langSpan.textContent = voice.language_name || voice.language;

    const qualitySpan = document.createElement('span');
    qualitySpan.className = 'piper-voice-quality';
    qualitySpan.textContent = voice.quality;

    const sizeSpan = document.createElement('span');
    sizeSpan.className = 'piper-voice-size';
    sizeSpan.textContent = formatBytes(voice.size_bytes);

    const actionDiv = document.createElement('div');
    actionDiv.className = 'piper-voice-action';

    const btn = document.createElement('button');
    if (voice.installed) {
      btn.className = 'piper-btn-installed';
      btn.textContent = 'Installed';
      btn.disabled = true;
    } else if (piperDownloading.has(voice.key)) {
      btn.className = 'piper-btn-downloading';
      btn.textContent = 'Downloading...';
      btn.disabled = true;
    } else {
      btn.className = 'piper-btn-download';
      btn.textContent = 'Download';
      btn.addEventListener('click', () => downloadPiperVoice(voice.key));
    }

    actionDiv.appendChild(btn);
    row.appendChild(nameSpan);
    row.appendChild(langSpan);
    row.appendChild(qualitySpan);
    row.appendChild(sizeSpan);
    row.appendChild(actionDiv);
    piperCatalogList.appendChild(row);
  }

  const installed = piperCatalog.filter(v => v.installed).length;
  piperStatus.textContent = `${filtered.length} voices shown, ${installed} installed`;
}

async function downloadPiperVoice(key: string) {
  piperDownloading.add(key);
  renderPiperCatalog();
  log(`Downloading Piper voice: ${key}...`);

  try {
    const result = await nativeEngine.downloadPiperVoice(key);
    if (result.success) {
      log(`Piper voice "${key}" downloaded successfully`, 'success');
      piperNewlyDownloaded = true;
      const entry = piperCatalog.find(v => v.key === key);
      if (entry) entry.installed = true;
    } else {
      log(`Failed to download "${key}": ${result.error}`, 'error');
    }
  } catch (err) {
    log(`Download failed: ${err instanceof Error ? err.message : err}`, 'error');
  } finally {
    piperDownloading.delete(key);
    renderPiperCatalog();
  }
}

function closePiperModal() {
  piperModal.hidden = true;
  if (piperNewlyDownloaded) {
    refreshVoices();
  }
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1048576).toFixed(1)} MB`;
}

// ── Refresh Voices ────────────────────────────────────────
async function refreshVoices() {
  refreshVoicesBtn.disabled = true;
  refreshVoicesBtn.classList.add('refreshing');
  log('Refreshing voice list from OS...');

  try {
    const oldCount = voices.length;
    voices = await vox.getVoices();
    const diff = voices.length - oldCount;

    populateFilters();
    renderVoiceList();

    if (diff > 0) {
      log(`Found ${diff} new voice${diff === 1 ? '' : 's'} (${voices.length} total)`, 'success');
    } else if (diff < 0) {
      log(`${Math.abs(diff)} voice${Math.abs(diff) === 1 ? '' : 's'} removed (${voices.length} total)`, 'warn');
    } else {
      log(`Voice list unchanged (${voices.length} voices)`, 'info');
    }

    // Re-validate selected voice still exists
    if (selectedVoiceId && !voices.find(v => v.id === selectedVoiceId)) {
      log(`Previously selected voice is no longer available`, 'warn');
      selectedVoiceId = null;
      voiceSelectedDisplay.textContent = 'No voice selected';
      generateBtn.disabled = true;
    }
  } catch (err) {
    log(`Failed to refresh voices: ${err instanceof Error ? err.message : err}`, 'error');
  } finally {
    refreshVoicesBtn.disabled = false;
    refreshVoicesBtn.classList.remove('refreshing');
  }
}

// ── Generate ──────────────────────────────────────────────
async function generate() {
  const text = textInput.value.trim();
  if (!text) {
    log('No text entered', 'warn');
    return;
  }
  if (isGenerating) return;
  if (!selectedVoiceId) {
    log('No voice selected', 'warn');
    return;
  }

  isGenerating = true;
  generateBtn.textContent = 'Generating...';
  generateBtn.classList.add('generating');
  downloadBtn.disabled = true;
  playerSection.hidden = true;
  lastBlob = null;

  const voice = selectedVoiceId;
  const rate = parseFloat(rateSlider.value);
  const pitch = parseFloat(pitchSlider.value);
  const format = formatSelect.value;
  const voiceObj = voices.find(v => v.id === voice);
  const voiceName = voiceObj?.name ?? voice;

  log(`Synthesizing: voice="${voiceName}", rate=${rate}x, pitch=${pitch}`);

  const wordCount = text.split(/\s+/).length;
  const estimatedMs = (wordCount / 150) * 60_000 / rate;
  showProgress(estimatedMs);

  try {
    const t0 = performance.now();
    const alignment = alignmentSelect.value as 'none' | 'word' | 'word+syllable' | 'word+phoneme' | 'full';
    const analyzeQuality = qualityCheck.checked;
    const result: SynthesisResult = await vox.synthesize(text, {
      voice,
      rate,
      pitch,
      engine: 'native-bridge',
      alignment,
      analyzeQuality,
    });
    const elapsed = Math.round(performance.now() - t0);

    finishProgress();
    log(`Synthesis complete in ${elapsed}ms`, 'success');
    log(`Words: ${result.metadata.wordTimestamps.length}, duration: ${Math.round(result.metadata.totalDurationMs)}ms`);

    // ── Quality score display ──
    if (result.qualityScore) {
      const qs = result.qualityScore;
      qualitySection.hidden = false;
      qualityGrid.innerHTML = '';

      const addMetric = (label: string, value: string | number | undefined, unit?: string) => {
        if (value === undefined || value === null) return;
        const el = document.createElement('div');
        el.className = 'quality-metric';
        el.innerHTML = `<span class="metric-label">${label}</span><span class="metric-value">${value}${unit ?? ''}</span>`;
        qualityGrid.appendChild(el);
      };

      const ratingColors: Record<string, string> = {
        excellent: '#22c55e', good: '#84cc16', fair: '#eab308', poor: '#f97316', bad: '#ef4444',
      };
      const badge = document.createElement('div');
      badge.className = 'quality-badge';
      badge.style.borderColor = ratingColors[qs.overallRating] ?? '#888';
      badge.innerHTML = `<span class="badge-score">${qs.overallScore.toFixed(1)}</span><span class="badge-rating">${qs.overallRating}</span>`;
      qualityGrid.appendChild(badge);

      addMetric('ASR Confidence', qs.asrConfidence?.toFixed(2));
      addMetric('Word Error Rate', qs.asrWer?.toFixed(3));
      addMetric('MOS', qs.mos?.toFixed(2), ` (${qs.mosRating ?? ''})`);
      addMetric('SNR', qs.snrDb?.toFixed(1), ' dB');
      addMetric('F0 Mean', qs.f0MeanHz?.toFixed(0), ' Hz');
      addMetric('F0 Range', qs.f0RangeHz?.toFixed(0), ' Hz');

      if (qs.artifacts.length > 0) {
        for (const a of qs.artifacts) {
          addMetric(`Artifact: ${a.type}`, `${a.severity} — ${a.detail}`);
        }
      }

      qualityRecommendations.innerHTML = '';
      if (qs.recommendations.length > 0) {
        const ul = document.createElement('ul');
        for (const rec of qs.recommendations) {
          const li = document.createElement('li');
          li.textContent = rec;
          ul.appendChild(li);
        }
        qualityRecommendations.appendChild(ul);
      }

      log(`Quality: ${qs.overallScore.toFixed(1)}/5.0 (${qs.overallRating})`, qs.overallScore >= 3.5 ? 'success' : 'warn');
    } else {
      qualitySection.hidden = true;
    }

    // Clear any previous failure record for this voice
    failedVoices.delete(voice);

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
      log('No audio samples captured - check server logs', 'warn');
    }
  } catch (err) {
    finishProgress();
    const errorMsg = err instanceof Error ? err.message : String(err);
    log(`Synthesis failed: ${errorMsg}`, 'error');

    // Track this voice as failed
    failedVoices.set(voice, errorMsg);

    // Show error dialog with helpful information
    const { title, suggestion } = classifySynthesisError(errorMsg, voice);
    showErrorDialog(title, errorMsg, suggestion);
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
voiceSearch.addEventListener('input', () => {
  renderVoiceList();
});

filterLanguage.addEventListener('change', () => {
  renderVoiceList();
});

filterEngine.addEventListener('change', () => {
  renderVoiceList();
});

refreshVoicesBtn.addEventListener('click', refreshVoices);

showFavoritesBtn.addEventListener('click', () => {
  showingFavoritesOnly = !showingFavoritesOnly;
  showFavoritesBtn.classList.toggle('active', showingFavoritesOnly);
  showFavoritesBtn.querySelector('.star-icon')!.innerHTML = showingFavoritesOnly ? '&#9733;' : '&#9734;';
  showFavoritesBtn.title = showingFavoritesOnly ? 'Show all voices' : 'Show favorites only';
  renderVoiceList();
});

rateSlider.addEventListener('input', () => {
  rateValue.textContent = parseFloat(rateSlider.value).toFixed(1);
});

pitchSlider.addEventListener('input', () => {
  pitchValue.textContent = parseFloat(pitchSlider.value).toFixed(1);
});

textInput.addEventListener('input', () => {
  generateBtn.disabled = textInput.value.trim().length === 0 || !selectedVoiceId;
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
  if (lastWordBoundaries.length > 0) {
    // Reset all words to unspoken state before starting highlight loop
    textDisplay.querySelectorAll('.word').forEach((s) => {
      s.classList.remove('active', 'spoken');
      s.classList.add('unspoken');
    });
    startHighlighting();
  }
});

audioPlayer.addEventListener('pause', stopHighlighting);
audioPlayer.addEventListener('ended', stopHighlighting);
audioPlayer.addEventListener('seeked', () => {
  if (!audioPlayer.paused && lastWordBoundaries.length > 0) {
    stopHighlighting();
    startHighlighting();
  }
});

formatSelect.addEventListener('change', onFormatChange);
generateBtn.addEventListener('click', generate);
downloadBtn.addEventListener('click', download);

// Context menu events
contextMenuValidate.addEventListener('click', validateContextMenuVoice);
contextMenuClose.addEventListener('click', hideContextMenu);
contextMenu.addEventListener('click', (e) => {
  if (e.target === contextMenu) hideContextMenu();
});

// Error dialog events
errorDialogClose.addEventListener('click', hideErrorDialog);
errorDialog.addEventListener('click', (e) => {
  if (e.target === errorDialog) hideErrorDialog();
});

// Piper modal events
piperDownloadBtn.addEventListener('click', openPiperModal);
piperModalClose.addEventListener('click', closePiperModal);
piperModal.addEventListener('click', (e) => {
  if (e.target === piperModal) closePiperModal();
});
piperSearch.addEventListener('input', renderPiperCatalog);
piperLangFilter.addEventListener('change', renderPiperCatalog);
piperQualityFilter.addEventListener('change', renderPiperCatalog);

// ── Voice Sample / Cloning ────────────────────────────────
let sampleMediaRecorder: MediaRecorder | null = null;
let sampleRecordedChunks: Blob[] = [];
let sampleRecordedBlob: Blob | null = null;
let sampleNewlyUploaded = false;

async function openSampleModal() {
  sampleModal.hidden = false;
  sampleNewlyUploaded = false;
  sampleStatus.textContent = '';
  samplePreviewSection.hidden = true;
  sampleRecordStatus.textContent = '';
  await renderSampleList();
}

function closeSampleModal() {
  sampleModal.hidden = true;
  if (sampleMediaRecorder && sampleMediaRecorder.state !== 'inactive') {
    sampleMediaRecorder.stop();
    sampleMediaRecorder.stream.getTracks().forEach(t => t.stop());
  }
  sampleMediaRecorder = null;
  if (sampleNewlyUploaded) {
    refreshVoices();
  }
}

async function renderSampleList() {
  try {
    const samples = await nativeEngine.listVoiceSamples();
    sampleList.innerHTML = '';
    if (samples.length === 0) {
      sampleList.innerHTML = '<div class="sample-list-empty">No voice samples saved yet.</div>';
      return;
    }
    for (const sample of samples) {
      const item = document.createElement('div');
      item.className = 'sample-item';

      const nameSpan = document.createElement('span');
      nameSpan.className = 'sample-item-name';
      nameSpan.textContent = sample.name;

      const sizeSpan = document.createElement('span');
      sizeSpan.className = 'sample-item-size';
      sizeSpan.textContent = formatBytes(sample.size_bytes);

      const useBtn = document.createElement('button');
      useBtn.className = 'sample-item-use';
      useBtn.textContent = 'Use';
      useBtn.title = 'Select this sample with the chosen cloning engine';
      useBtn.addEventListener('click', () => {
        const engine = cloneEngineSelect.value;
        const voiceId = `${engine}:${sample.name}`;
        const voice = voices.find(v => v.id === voiceId);
        if (voice) {
          selectVoice(voiceId);
          closeSampleModal();
          log(`Selected cloned voice: ${voice.name}`, 'success');
        } else {
          sampleStatus.textContent = `Voice "${voiceId}" not found. Is the ${engine} server running?`;
        }
      });

      const deleteBtn = document.createElement('button');
      deleteBtn.className = 'sample-item-delete';
      deleteBtn.textContent = 'Delete';
      deleteBtn.addEventListener('click', () => deleteSample(sample.name));

      item.appendChild(nameSpan);
      item.appendChild(sizeSpan);
      item.appendChild(useBtn);
      item.appendChild(deleteBtn);
      sampleList.appendChild(item);
    }
  } catch (err) {
    sampleList.innerHTML = `<div class="sample-list-empty">Failed to load samples: ${err instanceof Error ? err.message : err}</div>`;
  }
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    sampleRecordedChunks = [];
    sampleRecordedBlob = null;
    samplePreviewSection.hidden = true;

    sampleMediaRecorder = new MediaRecorder(stream, {
      mimeType: MediaRecorder.isTypeSupported('audio/webm;codecs=opus')
        ? 'audio/webm;codecs=opus'
        : 'audio/webm',
    });

    sampleMediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) sampleRecordedChunks.push(e.data);
    };

    sampleMediaRecorder.onstop = async () => {
      stream.getTracks().forEach(t => t.stop());
      sampleRecordedBlob = new Blob(sampleRecordedChunks, { type: sampleMediaRecorder!.mimeType });
      sampleRecordBtn.textContent = 'Record';
      sampleRecordBtn.classList.remove('recording');
      sampleStopBtn.disabled = true;
      sampleRecordStatus.textContent = `Recorded ${(sampleRecordedBlob.size / 1024).toFixed(1)} KB`;

      // Convert to WAV for preview and upload
      const wavBlob = await convertToWav(sampleRecordedBlob);
      sampleRecordedBlob = wavBlob;
      samplePreviewPlayer.src = URL.createObjectURL(wavBlob);
      samplePreviewSection.hidden = false;
      sampleRecordStatus.textContent += ' — preview and save below';
    };

    sampleMediaRecorder.start();
    sampleRecordBtn.textContent = 'Recording...';
    sampleRecordBtn.classList.add('recording');
    sampleStopBtn.disabled = false;
    sampleRecordStatus.textContent = 'Recording... speak clearly into your microphone.';
    log('Recording voice sample...', 'info');
  } catch (err) {
    sampleRecordStatus.textContent = `Microphone access denied: ${err instanceof Error ? err.message : err}`;
    log(`Microphone error: ${err instanceof Error ? err.message : err}`, 'error');
  }
}

function stopRecording() {
  if (sampleMediaRecorder && sampleMediaRecorder.state !== 'inactive') {
    sampleMediaRecorder.stop();
  }
}

async function convertToWav(blob: Blob): Promise<Blob> {
  const arrayBuffer = await blob.arrayBuffer();
  const audioCtx = new AudioContext();
  const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
  await audioCtx.close();

  // Resample to mono 24kHz (Chatterbox native rate)
  const targetRate = 24000;
  const offlineCtx = new OfflineAudioContext(1, Math.ceil(audioBuffer.duration * targetRate), targetRate);
  const source = offlineCtx.createBufferSource();
  source.buffer = audioBuffer;
  source.connect(offlineCtx.destination);
  source.start();
  const rendered = await offlineCtx.startRendering();
  const pcm = rendered.getChannelData(0);

  return encodeWav(pcm, targetRate, 1);
}

async function saveSample() {
  if (!sampleRecordedBlob) return;

  const name = sampleNameInput.value.trim().replace(/[^a-zA-Z0-9_-]/g, '-') || 'my-voice';
  sampleSaveBtn.textContent = 'Saving...';
  sampleSaveBtn.disabled = true;

  try {
    const arrayBuffer = await sampleRecordedBlob.arrayBuffer();
    const base64 = arrayBufferToBase64(arrayBuffer);
    const result = await nativeEngine.uploadVoiceSample(name, base64);
    if (result.success) {
      log(`Voice sample "${name}" saved`, 'success');
      sampleNewlyUploaded = true;
      samplePreviewSection.hidden = true;
      sampleRecordStatus.textContent = `Sample "${name}" saved successfully.`;
      await renderSampleList();
    } else {
      log(`Failed to save sample: ${result.error}`, 'error');
      sampleRecordStatus.textContent = `Save failed: ${result.error}`;
    }
  } catch (err) {
    log(`Save failed: ${err instanceof Error ? err.message : err}`, 'error');
    sampleRecordStatus.textContent = `Save failed: ${err instanceof Error ? err.message : err}`;
  } finally {
    sampleSaveBtn.textContent = 'Save Sample';
    sampleSaveBtn.disabled = false;
  }
}

async function uploadSampleFile() {
  const file = sampleFileInput.files?.[0];
  if (!file) return;

  const name = file.name.replace(/\.[^.]+$/, '').replace(/[^a-zA-Z0-9_-]/g, '-') || 'uploaded';
  sampleUploadBtn.textContent = 'Uploading...';
  sampleUploadBtn.disabled = true;

  try {
    // Read and convert to WAV
    const arrayBuffer = await file.arrayBuffer();
    let wavBlob: Blob;

    if (file.type === 'audio/wav' || file.name.endsWith('.wav')) {
      wavBlob = new Blob([arrayBuffer], { type: 'audio/wav' });
    } else {
      // Convert other formats to WAV
      const audioCtx = new AudioContext();
      const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
      await audioCtx.close();

      const targetRate = 24000;
      const offlineCtx = new OfflineAudioContext(1, Math.ceil(audioBuffer.duration * targetRate), targetRate);
      const source = offlineCtx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(offlineCtx.destination);
      source.start();
      const rendered = await offlineCtx.startRendering();
      wavBlob = encodeWav(rendered.getChannelData(0), targetRate, 1);
    }

    const wavBuffer = await wavBlob.arrayBuffer();
    const base64 = arrayBufferToBase64(wavBuffer);
    const result = await nativeEngine.uploadVoiceSample(name, base64);

    if (result.success) {
      log(`Voice sample "${name}" uploaded`, 'success');
      sampleNewlyUploaded = true;
      sampleStatus.textContent = `"${name}" uploaded successfully.`;
      await renderSampleList();
    } else {
      log(`Upload failed: ${result.error}`, 'error');
      sampleStatus.textContent = `Upload failed: ${result.error}`;
    }
  } catch (err) {
    log(`Upload failed: ${err instanceof Error ? err.message : err}`, 'error');
    sampleStatus.textContent = `Upload failed: ${err instanceof Error ? err.message : err}`;
  } finally {
    sampleUploadBtn.textContent = 'Upload';
    sampleUploadBtn.disabled = !sampleFileInput.files?.length;
  }
}

async function deleteSample(name: string) {
  try {
    const result = await nativeEngine.deleteVoiceSample(name);
    if (result.success) {
      log(`Voice sample "${name}" deleted`, 'success');
      sampleNewlyUploaded = true;
      await renderSampleList();
    } else {
      log(`Delete failed: ${result.error}`, 'error');
    }
  } catch (err) {
    log(`Delete failed: ${err instanceof Error ? err.message : err}`, 'error');
  }
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = '';
  for (let i = 0; i < bytes.byteLength; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

// Voice sample modal events
voiceSampleBtn.addEventListener('click', openSampleModal);
sampleModalClose.addEventListener('click', closeSampleModal);
sampleModal.addEventListener('click', (e) => {
  if (e.target === sampleModal) closeSampleModal();
});
sampleRecordBtn.addEventListener('click', () => {
  if (sampleMediaRecorder && sampleMediaRecorder.state === 'recording') {
    stopRecording();
  } else {
    startRecording();
  }
});
sampleStopBtn.addEventListener('click', stopRecording);
sampleSaveBtn.addEventListener('click', saveSample);
sampleFileInput.addEventListener('change', () => {
  sampleUploadBtn.disabled = !sampleFileInput.files?.length;
});
sampleUploadBtn.addEventListener('click', uploadSampleFile);

// ── Server Dashboard ──────────────────────────────────────

let dashboardRefreshTimer = 0;
let lastServerStats: ServerProcessStats[] = [];
const expandedLogs = new Set<string>();

function formatUptime(secs: number): string {
  if (secs === 0) return '—';
  if (secs < 60) return `${secs}s`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ${secs % 60}s`;
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  return `${h}h ${m}m`;
}

function drawSparkline(canvas: HTMLCanvasElement, data: number[], maxVal: number, color: string) {
  const ctx = canvas.getContext('2d');
  if (!ctx || data.length < 2) return;

  const w = canvas.width;
  const h = canvas.height;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = w * dpr;
  canvas.height = h * dpr;
  ctx.scale(dpr, dpr);
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;

  ctx.clearRect(0, 0, w, h);

  // Fill area
  ctx.beginPath();
  const step = w / (data.length - 1);
  ctx.moveTo(0, h);
  for (let i = 0; i < data.length; i++) {
    const y = h - (Math.min(data[i], maxVal) / maxVal) * h;
    ctx.lineTo(i * step, y);
  }
  ctx.lineTo(w, h);
  ctx.closePath();
  ctx.fillStyle = color.replace(')', ', 0.15)').replace('rgb', 'rgba');
  ctx.fill();

  // Line
  ctx.beginPath();
  for (let i = 0; i < data.length; i++) {
    const y = h - (Math.min(data[i], maxVal) / maxVal) * h;
    if (i === 0) ctx.moveTo(i * step, y);
    else ctx.lineTo(i * step, y);
  }
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

async function fetchServerStats(): Promise<ServerProcessStats[]> {
  try {
    const stats = await nativeEngine.getServerStats();
    lastServerStats = stats;
    return stats;
  } catch {
    return lastServerStats;
  }
}

async function manageServer(engine: string, action: 'start' | 'stop' | 'restart') {
  log(`${action} server: ${engine}...`, 'info');
  try {
    const result = await nativeEngine.manageServer(engine, action);
    if (result.success) {
      log(`Server ${engine} ${action} successful`, 'success');
    } else {
      log(`Server ${engine} ${action} failed: ${result.error}`, 'error');
    }
  } catch (err) {
    log(`Server management error: ${err instanceof Error ? err.message : err}`, 'error');
  }
  // Refresh dashboard after action
  await refreshServerDashboard();
}

function renderServerDashboard(stats: ServerProcessStats[]) {
  serverDashboardBody.innerHTML = '';
  let onlineCount = 0;

  for (const srv of stats) {
    if (srv.online) onlineCount++;

    const card = document.createElement('div');
    card.className = `server-card ${srv.online ? 'server-online' : 'server-offline'}`;

    // Header row
    const header = document.createElement('div');
    header.className = 'server-card-header';

    const dot = document.createElement('div');
    dot.className = `server-status-dot ${srv.online ? 'online' : 'offline'}`;

    const name = document.createElement('span');
    name.className = 'server-card-name';
    name.textContent = srv.name;

    const typeBadge = document.createElement('span');
    typeBadge.className = `server-card-type ${srv.engine === 'ws-server' ? 'server-type-ws' : 'server-type-python'}`;
    typeBadge.textContent = srv.engine === 'ws-server' ? 'Rust' : 'Python';

    const port = document.createElement('span');
    port.className = 'server-card-port';
    port.textContent = `:${srv.port}`;

    header.appendChild(dot);
    header.appendChild(name);
    header.appendChild(typeBadge);
    header.appendChild(port);
    card.appendChild(header);

    // Details grid
    const details = document.createElement('div');
    details.className = 'server-card-details';

    const addDetail = (label: string, value: string) => {
      const row = document.createElement('div');
      row.className = 'server-detail';
      row.innerHTML = `<span class="server-detail-label">${label}:</span><span class="server-detail-value">${value}</span>`;
      details.appendChild(row);
    };

    addDetail('Status', srv.online ? 'Online' : 'Offline');
    if (srv.pid) addDetail('PID', String(srv.pid));
    if (srv.online) {
      addDetail('CPU', `${srv.cpu_percent.toFixed(1)}%`);
      addDetail('Memory', `${srv.memory_mb.toFixed(1)} MB`);
      if (srv.uptime_secs > 0) addDetail('Uptime', formatUptime(srv.uptime_secs));
      if (srv.managed) addDetail('Managed', 'Yes');
    }

    card.appendChild(details);

    // Sparkline charts (CPU + Memory)
    if (srv.cpu_history.length > 1 || srv.memory_history.length > 1) {
      const charts = document.createElement('div');
      charts.className = 'server-card-charts';

      // CPU sparkline
      const cpuChart = document.createElement('div');
      cpuChart.className = 'server-sparkline-group';
      const cpuLabel = document.createElement('span');
      cpuLabel.className = 'sparkline-label';
      cpuLabel.textContent = 'CPU';
      const cpuCanvas = document.createElement('canvas');
      cpuCanvas.className = 'sparkline-canvas';
      cpuCanvas.width = 120;
      cpuCanvas.height = 28;
      cpuChart.appendChild(cpuLabel);
      cpuChart.appendChild(cpuCanvas);

      // Memory sparkline
      const memChart = document.createElement('div');
      memChart.className = 'server-sparkline-group';
      const memLabel = document.createElement('span');
      memLabel.className = 'sparkline-label';
      memLabel.textContent = 'MEM';
      const memCanvas = document.createElement('canvas');
      memCanvas.className = 'sparkline-canvas';
      memCanvas.width = 120;
      memCanvas.height = 28;
      memChart.appendChild(memLabel);
      memChart.appendChild(memCanvas);

      charts.appendChild(cpuChart);
      charts.appendChild(memChart);
      card.appendChild(charts);

      // Draw after DOM insert
      requestAnimationFrame(() => {
        const maxCpu = Math.max(100, ...srv.cpu_history);
        const maxMem = Math.max(100, ...srv.memory_history);
        drawSparkline(cpuCanvas, srv.cpu_history, maxCpu, 'rgb(108, 99, 255)');
        drawSparkline(memCanvas, srv.memory_history, maxMem, 'rgb(76, 175, 80)');
      });
    }

    // Actions row
    const actions = document.createElement('div');
    actions.className = 'server-card-actions';

    if (srv.engine !== 'ws-server') {
      if (srv.online) {
        const restartBtn = document.createElement('button');
        restartBtn.className = 'server-action-btn server-btn-restart';
        restartBtn.textContent = 'Restart';
        restartBtn.addEventListener('click', () => {
          restartBtn.disabled = true;
          restartBtn.textContent = 'Restarting...';
          manageServer(srv.engine, 'restart');
        });

        const stopBtn = document.createElement('button');
        stopBtn.className = 'server-action-btn server-btn-stop';
        stopBtn.textContent = 'Stop';
        stopBtn.addEventListener('click', () => {
          stopBtn.disabled = true;
          stopBtn.textContent = 'Stopping...';
          manageServer(srv.engine, 'stop');
        });

        actions.appendChild(restartBtn);
        actions.appendChild(stopBtn);
      } else {
        const startBtn = document.createElement('button');
        startBtn.className = 'server-action-btn server-btn-start';
        startBtn.textContent = 'Start';
        startBtn.addEventListener('click', () => {
          startBtn.disabled = true;
          startBtn.textContent = 'Starting...';
          manageServer(srv.engine, 'start');
        });
        actions.appendChild(startBtn);
      }
    }

    // Usage log toggle button
    if (srv.usage_log && srv.usage_log.length > 0) {
      const logToggle = document.createElement('button');
      logToggle.className = 'server-log-toggle';
      const isExpanded = expandedLogs.has(srv.engine);
      logToggle.textContent = `Log (${srv.usage_log.length})`;
      if (isExpanded) logToggle.classList.add('active');
      logToggle.addEventListener('click', () => {
        if (expandedLogs.has(srv.engine)) {
          expandedLogs.delete(srv.engine);
        } else {
          expandedLogs.add(srv.engine);
        }
        // Re-render just the log visibility
        const logEl = card.querySelector('.server-usage-log') as HTMLElement;
        if (logEl) logEl.hidden = !expandedLogs.has(srv.engine);
        logToggle.classList.toggle('active', expandedLogs.has(srv.engine));
      });
      actions.appendChild(logToggle);
    }

    card.appendChild(actions);

    // Usage log table (collapsible)
    if (srv.usage_log && srv.usage_log.length > 0) {
      const logContainer = document.createElement('div');
      logContainer.className = 'server-usage-log';
      logContainer.hidden = !expandedLogs.has(srv.engine);

      const table = document.createElement('table');
      table.innerHTML = '<thead><tr><th>Time</th><th>Status</th><th>CPU %</th><th>Memory</th></tr></thead>';
      const tbody = document.createElement('tbody');

      // Show most recent entries first
      const entries = [...srv.usage_log].reverse();
      for (const entry of entries) {
        const tr = document.createElement('tr');
        if (!entry.online) tr.className = 'offline';

        const timeStr = new Date(entry.timestamp * 1000).toLocaleTimeString('en-US', { hour12: false });
        const cpuClass = entry.cpu_percent > 80 ? ' class="log-cpu-high"' : '';
        const memClass = entry.memory_mb > 4000 ? ' class="log-mem-high"' : '';

        tr.innerHTML = `<td>${timeStr}</td><td>${entry.online ? 'Online' : 'Offline'}</td><td${cpuClass}>${entry.cpu_percent.toFixed(1)}%</td><td${memClass}>${entry.memory_mb.toFixed(1)} MB</td>`;
        tbody.appendChild(tr);
      }

      table.appendChild(tbody);
      logContainer.appendChild(table);
      card.appendChild(logContainer);
    }

    serverDashboardBody.appendChild(card);
  }

  // Summary bar
  const totalCpu = stats.reduce((s, srv) => s + srv.cpu_percent, 0);
  const totalMem = stats.reduce((s, srv) => s + srv.memory_mb, 0);
  serverDashboardStatus.textContent = `${onlineCount}/${stats.length} online | CPU: ${totalCpu.toFixed(1)}% | RAM: ${totalMem.toFixed(0)} MB`;
}

async function openServerDashboard() {
  serverDashboard.hidden = false;
  serverDashboardBody.innerHTML = '<div class="server-dashboard-loading">Probing servers...</div>';
  serverDashboardStatus.textContent = '';

  const stats = await fetchServerStats();
  renderServerDashboard(stats);

  // Auto-refresh every 5 seconds
  dashboardRefreshTimer = window.setInterval(async () => {
    if (serverDashboard.hidden) return;
    const s = await fetchServerStats();
    renderServerDashboard(s);
  }, 5000);
}

function closeServerDashboard() {
  serverDashboard.hidden = true;
  clearInterval(dashboardRefreshTimer);
}

async function refreshServerDashboard() {
  serverDashboardRefresh.disabled = true;
  serverDashboardRefresh.textContent = 'Refreshing...';
  const stats = await fetchServerStats();
  renderServerDashboard(stats);
  serverDashboardRefresh.disabled = false;
  serverDashboardRefresh.textContent = 'Refresh';
}

serverDashboardBtn.addEventListener('click', openServerDashboard);
serverDashboardClose.addEventListener('click', closeServerDashboard);
serverDashboardRefresh.addEventListener('click', refreshServerDashboard);
serverDashboard.addEventListener('click', (e) => {
  if (e.target === serverDashboard) closeServerDashboard();
});


// ── Stack Status Bar ──────────────────────────────────────

interface StackStatus {
  ws: boolean;
  alignment: boolean;
  quality: boolean;
  docAnalyzer: boolean;
}

async function checkStackStatus(): Promise<StackStatus> {
  const results: StackStatus = { ws: false, alignment: false, quality: false, docAnalyzer: false };

  // Use the server stats from the WS server (avoids CORS issues)
  try {
    if (!nativeEngine) return results;
    results.ws = true;
    const stats = await nativeEngine.getServerStats();
    for (const srv of stats) {
      if (srv.engine === 'alignment' && srv.online) results.alignment = true;
      if (srv.engine === 'quality' && srv.online) results.quality = true;
      if (srv.engine === 'document-analyzer' && srv.online) results.docAnalyzer = true;
    }
  } catch { /* WS server down */ }

  return results;
}

function renderStackStatus(s: StackStatus) {
  const setDot = (el: HTMLSpanElement, up: boolean) => {
    el.className = `stack-dot ${up ? 'up' : 'down'}`;
  };
  setDot(stackDotWs, s.ws);
  setDot(stackDotAlignment, s.alignment);
  setDot(stackDotQuality, s.quality);
  setDot(stackDotDocAnalyzer, s.docAnalyzer);

  const count = [s.ws, s.alignment, s.quality, s.docAnalyzer].filter(Boolean).length;
  stackSummary.textContent = `${count}/4 services up`;
  stackSummary.style.color = count === 4 ? 'var(--success)' : count > 0 ? 'var(--warn)' : 'var(--error)';
}

async function refreshStackStatus() {
  [stackDotWs, stackDotAlignment, stackDotQuality, stackDotDocAnalyzer].forEach(d => d.className = 'stack-dot checking');
  stackSummary.textContent = 'Checking...';
  const s = await checkStackStatus();
  renderStackStatus(s);
  return s;
}

// Poll stack status periodically
let stackPollTimer = 0;
function startStackPoll() {
  refreshStackStatus();
  stackPollTimer = window.setInterval(() => refreshStackStatus(), 15000);
}

// Close dialogs on Escape
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    if (!serverDashboard.hidden) closeServerDashboard();
    if (!craftingModal.hidden) closeCraftingModal();
    if (!sampleModal.hidden) closeSampleModal();
    if (!piperModal.hidden) closePiperModal();
    if (!contextMenu.hidden) hideContextMenu();
    if (!errorDialog.hidden) hideErrorDialog();
  }
});

// ── Voice Crafting Studio ──────────────────────────────────

const craftingModal = document.getElementById('crafting-modal') as HTMLDivElement;
const craftingProgress = document.getElementById('crafting-progress') as HTMLDivElement;
const craftingLoading = document.getElementById('crafting-loading') as HTMLDivElement;
const craftingLoadingLabel = document.getElementById('crafting-loading-label') as HTMLSpanElement;
const craftingLoadingPercent = document.getElementById('crafting-loading-percent') as HTMLSpanElement;
const craftingLoadingFill = document.getElementById('crafting-loading-fill') as HTMLDivElement;
const craftingLoadingSteps = document.getElementById('crafting-loading-steps') as HTMLDivElement;
const craftingModeSelect = document.getElementById('crafting-mode-select') as HTMLDivElement;
const craftingArchetypeGrid = document.getElementById('crafting-archetype-grid') as HTMLDivElement;
const craftingArchetypes = document.getElementById('crafting-archetypes') as HTMLDivElement;
const craftingFreeform = document.getElementById('crafting-freeform') as HTMLDivElement;
const craftingFreeformInput = document.getElementById('crafting-freeform-input') as HTMLTextAreaElement;
const craftingFreeformStart = document.getElementById('crafting-freeform-start') as HTMLButtonElement;
const craftingAxisStep = document.getElementById('crafting-axis-step') as HTMLDivElement;
const craftingAxisCounter = document.getElementById('crafting-axis-counter') as HTMLSpanElement;
const craftingAxisLabel = document.getElementById('crafting-axis-label') as HTMLHeadingElement;
const craftingAxisDesc = document.getElementById('crafting-axis-desc') as HTMLParagraphElement;
const craftingSamplesRow = document.getElementById('crafting-samples-row') as HTMLDivElement;
const craftingBackBtn = document.getElementById('crafting-back-btn') as HTMLButtonElement;
const craftingSkipBtn = document.getElementById('crafting-skip-btn') as HTMLButtonElement;
const craftingRegenBtn = document.getElementById('crafting-regen-btn') as HTMLButtonElement;
const craftingCumulative = document.getElementById('crafting-cumulative') as HTMLDivElement;
const craftingCumulativeText = document.getElementById('crafting-cumulative-text') as HTMLSpanElement;
const craftingSummary = document.getElementById('crafting-summary') as HTMLDivElement;
const craftingTraitsList = document.getElementById('crafting-traits-list') as HTMLDivElement;
const craftingFinalDesc = document.getElementById('crafting-final-desc') as HTMLParagraphElement;
const craftingSaveName = document.getElementById('crafting-save-name') as HTMLInputElement;
const craftingSaveBtn = document.getElementById('crafting-save-btn') as HTMLButtonElement;
const craftingStatus = document.getElementById('crafting-status') as HTMLSpanElement;
const craftingApiCounter = document.getElementById('crafting-api-counter') as HTMLSpanElement;
const craftingModalClose = document.getElementById('crafting-modal-close') as HTMLButtonElement;
const voiceCraftingBtn = document.getElementById('voice-crafting-btn') as HTMLButtonElement;

interface CraftingSessionState {
  session_id: string;
  mode: string;
  current_axis_index: number;
  axes_order: string[];
  selections: Record<string, unknown>;
  cumulative_prompt: string;
  api_call_count: number;
  status: string;
  user_intent?: string;
  parsed_freeform?: Record<string, string>;
  operation?: CraftingOperationState;
  current_axis: { id: string; label: string; description: string; category: string } | null;
  total_axes: number;
  progress: Array<{ axis_id: string; label: string; category: string; state: string }>;
}

interface CraftingOperationState {
  kind: string;
  active: boolean;
  message: string;
  current_step: number;
  total_steps: number;
  percent: number;
  stage: string;
  steps: Array<{ label: string; state: string }>;
  error?: string | null;
}

interface CraftingSample {
  index: number;
  label: string;
  archetype_id: string;
  archetype_label: string;
  audio_base64: string | null;
  sample_rate: number;
  generated_voice_id: string | null;
}

let craftingSession: CraftingSessionState | null = null;
let craftingCurrentAudio: HTMLAudioElement | null = null;
let craftingBusy = false;
let craftingLoadingTimer = 0;

async function craftingRequest(endpoint: string, body: Record<string, unknown> = {}): Promise<unknown> {
  const resp = await fetch(`${DESIGNER_URL}${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await resp.json();
  if (!resp.ok) {
    throw new Error((data && data.error) || `Request failed: ${resp.status}`);
  }
  return data;
}

async function craftingGetSession(sessionId: string): Promise<CraftingSessionState | null> {
  try {
    const resp = await fetch(`${DESIGNER_URL}/crafting/session/${sessionId}`);
    const data = await resp.json();
    if (!resp.ok || !data.success) return null;
    return data.session as CraftingSessionState;
  } catch {
    return null;
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function craftingSetBusy(busy: boolean) {
  craftingBusy = busy;
  craftingModeSelect.querySelectorAll('.crafting-mode-card').forEach((card) => {
    card.classList.toggle('busy', busy);
  });
  craftingFreeformStart.disabled = busy;
  craftingBackBtn.disabled = busy || (!craftingSession || craftingSession.current_axis_index === 0);
  craftingSkipBtn.disabled = busy;
  craftingRegenBtn.disabled = busy;
  craftingSaveBtn.disabled = busy;
}

function craftingRenderLoading(
  label: string,
  percent: number,
  steps: Array<{ label: string; state: string }>,
  visible = true,
) {
  window.clearTimeout(craftingLoadingTimer);
  craftingLoading.hidden = !visible;
  if (!visible) return;
  const safePercent = Math.max(0, Math.min(100, Math.round(percent)));
  craftingLoadingLabel.textContent = label;
  craftingLoadingPercent.textContent = `${safePercent}%`;
  craftingLoadingFill.style.width = `${safePercent}%`;
  craftingLoadingSteps.innerHTML = steps.map((step) =>
    `<div class="phase-loading-step" data-state="${step.state}">${step.label}</div>`
  ).join('');
}

function craftingHideLoading() {
  window.clearTimeout(craftingLoadingTimer);
  craftingLoading.hidden = true;
  craftingLoadingFill.style.width = '0%';
  craftingLoadingPercent.textContent = '0%';
  craftingLoadingSteps.innerHTML = '';
}

function craftingScheduleHideLoading(delay = 600) {
  window.clearTimeout(craftingLoadingTimer);
  craftingLoadingTimer = window.setTimeout(() => craftingHideLoading(), delay);
}

function craftingRenderLoadingError(message: string) {
  craftingRenderLoading(message, 100, [
    { label: message, state: 'error' },
  ]);
  craftingScheduleHideLoading(1200);
}

async function craftingTrackSessionOperation<T>(
  sessionId: string,
  request: Promise<T>,
  fallback: { label: string; percent: number; steps: Array<{ label: string; state: string }> },
): Promise<T> {
  let active = true;
  const poller = (async () => {
    craftingRenderLoading(fallback.label, fallback.percent, fallback.steps);
    while (active) {
      const snapshot = await craftingGetSession(sessionId);
      if (snapshot?.operation) {
        const op = snapshot.operation;
        craftingRenderLoading(
          op.message || fallback.label,
          op.percent || fallback.percent,
          op.steps || fallback.steps,
          true,
        );
      }
      await sleep(250);
    }
  })();

  try {
    return await request;
  } finally {
    active = false;
    await poller;
  }
}

function craftingShowStep(step: 'mode' | 'archetype' | 'freeform' | 'axis' | 'summary') {
  craftingModeSelect.hidden = step !== 'mode';
  craftingArchetypeGrid.hidden = step !== 'archetype';
  craftingFreeform.hidden = step !== 'freeform';
  craftingAxisStep.hidden = step !== 'axis';
  craftingSummary.hidden = step !== 'summary';
}

function craftingUpdateProgress() {
  if (!craftingSession) {
    craftingProgress.innerHTML = '';
    return;
  }
  craftingProgress.innerHTML = craftingSession.progress.map(p =>
    `<div class="crafting-progress-dot" data-state="${p.state}" data-category="${p.category}" title="${p.label}"></div>`
  ).join('');
  craftingApiCounter.textContent = `API calls: ${craftingSession.api_call_count}`;
}

function craftingUpdateCumulative() {
  if (!craftingSession || !craftingSession.cumulative_prompt) {
    craftingCumulative.hidden = true;
    return;
  }
  craftingCumulative.hidden = false;
  craftingCumulativeText.textContent = craftingSession.cumulative_prompt;
}

function craftingStopAudio() {
  if (craftingCurrentAudio) {
    craftingCurrentAudio.pause();
    craftingCurrentAudio = null;
  }
  craftingSamplesRow.querySelectorAll('.crafting-sample-card').forEach(c => c.classList.remove('playing'));
}

function craftingPlaySample(audioB64: string | null, sampleRate: number, cardEl: HTMLElement) {
  craftingStopAudio();
  if (!audioB64) return;

  const pcmBytes = Uint8Array.from(atob(audioB64), c => c.charCodeAt(0));
  const pcmFloat32 = new Float32Array(pcmBytes.buffer);
  const wavBlob = pcmToWavBlob(pcmFloat32, sampleRate);
  const audio = new Audio(URL.createObjectURL(wavBlob));
  craftingCurrentAudio = audio;
  cardEl.classList.add('playing');
  audio.onended = () => {
    cardEl.classList.remove('playing');
    craftingCurrentAudio = null;
  };
  audio.play();
}

function craftingRenderSamples(samples: CraftingSample[]) {
  craftingSamplesRow.innerHTML = samples.map((s, i) => `
    <div class="crafting-sample-card" data-index="${i}" data-archetype="${s.archetype_id}">
      <div class="sample-card-label">${s.label}</div>
      <div class="sample-card-archetype">${s.archetype_label}</div>
      ${s.audio_base64 ? `<div class="sample-card-actions">
        <button type="button" class="sample-play-btn" data-index="${i}" ${craftingBusy ? 'disabled' : ''}>Play</button>
        <button type="button" class="sample-select-btn" data-index="${i}" data-archetype="${s.archetype_id}" ${craftingBusy ? 'disabled' : ''}>Select</button>
      </div>` : '<div class="sample-no-audio">No audio generated</div>'}
    </div>
  `).join('');

  // Wire play buttons
  craftingSamplesRow.querySelectorAll('.sample-play-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const idx = parseInt((btn as HTMLElement).dataset.index || '0');
      const sample = samples[idx];
      const card = (btn as HTMLElement).closest('.crafting-sample-card') as HTMLElement;
      craftingPlaySample(sample.audio_base64, sample.sample_rate, card);
    });
  });

  // Wire select buttons
  craftingSamplesRow.querySelectorAll('.sample-select-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
      if (craftingBusy) return;
      const archId = (btn as HTMLElement).dataset.archetype || '';
      const idx = parseInt((btn as HTMLElement).dataset.index || '0');
      if (!craftingSession) return;
      const axisId = craftingSession.current_axis?.id;
      if (!axisId) return;

      craftingStopAudio();
      craftingStatus.textContent = 'Selecting...';
      craftingSetBusy(true);
      craftingRenderLoading('Saving your choice...', 50, [
        { label: 'Apply selected voice direction', state: 'active' },
        { label: 'Advance to the next comparison', state: 'pending' },
      ]);
      try {
        const result = await craftingRequest('/crafting/select', {
          session_id: craftingSession.session_id,
          axis_id: axisId,
          archetype_id: archId,
          preview_index: idx,
        }) as { success: boolean; session: CraftingSessionState; is_complete: boolean };

        if (result.success) {
          craftingSession = result.session;
          craftingUpdateProgress();
          craftingUpdateCumulative();
          craftingRenderLoading('Selection saved', 100, [
            { label: 'Apply selected voice direction', state: 'done' },
            { label: 'Advance to the next comparison', state: 'done' },
          ]);
          craftingScheduleHideLoading(350);
          craftingSetBusy(false);
          if (result.is_complete) {
            await craftingShowSummary();
          } else {
            await craftingExploreCurrentAxis();
          }
          return;
        }
      } catch (err) {
        craftingStatus.textContent = `Error: ${err}`;
        craftingRenderLoadingError('Could not save this selection');
      }
      craftingSetBusy(false);
    });
  });
}

async function craftingExploreCurrentAxis() {
  if (!craftingSession || craftingBusy) return;
  craftingShowStep('axis');

  const ax = craftingSession.current_axis;
  if (!ax) {
    await craftingShowSummary();
    return;
  }

  craftingAxisCounter.textContent = `Step ${craftingSession.current_axis_index + 1} of ${craftingSession.total_axes}`;
  craftingAxisLabel.textContent = ax.label;
  craftingAxisDesc.textContent = ax.description;
  craftingBackBtn.disabled = craftingSession.current_axis_index === 0;

  // Show loading state
  craftingSamplesRow.innerHTML = '<div class="crafting-sample-card loading"></div><div class="crafting-sample-card loading"></div><div class="crafting-sample-card loading"></div>';
  craftingStatus.textContent = `Generating ${ax.label} samples...`;
  craftingSetBusy(true);

  try {
    const result = await craftingTrackSessionOperation(
      craftingSession.session_id,
      craftingRequest('/crafting/explore', {
        session_id: craftingSession.session_id,
        axis_id: ax.id,
      }) as Promise<{ success: boolean; samples: CraftingSample[]; session: CraftingSessionState }>,
      {
        label: `Generating ${ax.label} samples...`,
        percent: 5,
        steps: [
          { label: 'Prepare prompts', state: 'active' },
          { label: 'Generate option A', state: 'pending' },
          { label: 'Generate option B', state: 'pending' },
          { label: 'Generate option C', state: 'pending' },
        ],
      },
    );

    if (result.success) {
      craftingSession = result.session;
      craftingUpdateProgress();
      craftingUpdateCumulative();
      craftingRenderLoading(`Finished ${ax.label} comparisons`, 100, (craftingSession.operation?.steps || []).map((step) => ({
        label: step.label,
        state: step.state === 'active' ? 'done' : step.state,
      })));
      craftingRenderSamples(result.samples);
      craftingStatus.textContent = `${result.samples.length} samples ready`;
      craftingScheduleHideLoading(600);
    } else {
      craftingStatus.textContent = 'Failed to generate samples';
      craftingSamplesRow.innerHTML = '<div class="sample-no-audio">Generation failed — try Regenerate</div>';
      craftingRenderLoadingError(`Could not generate ${ax.label} samples`);
    }
  } catch (err) {
    craftingStatus.textContent = `Error: ${err}`;
    craftingSamplesRow.innerHTML = '<div class="sample-no-audio">Generation failed — try Regenerate</div>';
    craftingRenderLoadingError(`Could not generate ${ax.label} samples`);
  } finally {
    craftingSetBusy(false);
  }
}

async function craftingShowSummary() {
  if (!craftingSession || craftingBusy) return;

  craftingStatus.textContent = 'Finalizing...';
  craftingSetBusy(true);
  try {
    const result = await craftingTrackSessionOperation(
      craftingSession.session_id,
      craftingRequest('/crafting/finish', {
        session_id: craftingSession.session_id,
      }) as Promise<{ success: boolean; polished_description: string; selections: Record<string, { archetype_id: string; prompt_fragment: string }> }>,
      {
        label: 'Finalizing your crafted voice...',
        percent: 10,
        steps: [
          { label: 'Compile selected traits', state: 'active' },
          { label: 'Polish final prompt', state: 'pending' },
        ],
      },
    );

    if (result.success) {
      craftingShowStep('summary');
      craftingFinalDesc.textContent = result.polished_description || '';

      const traitsHtml: string[] = [];
      const progress = craftingSession.progress || [];
      for (const p of progress) {
        const sel = result.selections[p.axis_id] as { archetype_id: string; prompt_fragment: string } | undefined;
        if (!sel || sel.archetype_id === '__skipped__') continue;
        traitsHtml.push(`
          <div class="crafting-trait-item">
            <span class="trait-axis-label">${p.label}</span>
            <span class="trait-value">${sel.prompt_fragment || sel.archetype_id}</span>
          </div>
        `);
      }
      craftingTraitsList.innerHTML = traitsHtml.join('');
      craftingRenderLoading('Voice summary ready', 100, [
        { label: 'Compile selected traits', state: 'done' },
        { label: 'Polish final prompt', state: 'done' },
      ]);
      craftingStatus.textContent = 'Summary ready';
      craftingScheduleHideLoading(600);
    } else {
      craftingStatus.textContent = 'Failed to finalize';
      craftingRenderLoadingError('Could not build the final summary');
    }
  } catch (err) {
    craftingStatus.textContent = `Error: ${err}`;
    craftingRenderLoadingError('Could not build the final summary');
  } finally {
    craftingSetBusy(false);
  }
}

async function openCraftingModal() {
  craftingModal.hidden = false;
  craftingSession = null;
  craftingStopAudio();
  craftingSetBusy(false);
  craftingShowStep('mode');
  craftingProgress.innerHTML = '';
  craftingApiCounter.textContent = '';
  craftingStatus.textContent = '';
  craftingHideLoading();
}

function closeCraftingModal() {
  if (craftingBusy) return;
  craftingModal.hidden = true;
  craftingStopAudio();
  craftingHideLoading();
}

// Mode card clicks
craftingModeSelect.querySelectorAll('.crafting-mode-card').forEach(card => {
  card.addEventListener('click', async () => {
    if (craftingBusy) return;
    const mode = (card as HTMLElement).dataset.mode;
    if (mode === 'guided') {
      craftingStatus.textContent = 'Starting session...';
      craftingSetBusy(true);
      craftingRenderLoading('Starting guided voice crafting...', 20, [
        { label: 'Create session', state: 'active' },
        { label: 'Open first comparison', state: 'pending' },
      ]);
      try {
        const result = await craftingRequest('/crafting/start', { mode: 'guided' }) as { success: boolean; session: CraftingSessionState };
        if (result.success) {
          craftingSession = result.session;
          craftingUpdateProgress();
          craftingRenderLoading('Guided session ready', 100, [
            { label: 'Create session', state: 'done' },
            { label: 'Open first comparison', state: 'done' },
          ]);
          craftingScheduleHideLoading(400);
          craftingSetBusy(false);
          await craftingExploreCurrentAxis();
          return;
        }
      } catch (err) {
        craftingStatus.textContent = `Error: ${err}`;
        craftingRenderLoadingError('Could not start guided crafting');
      }
      craftingSetBusy(false);
    } else if (mode === 'archetype') {
      await craftingLoadArchetypes();
      craftingShowStep('archetype');
    } else if (mode === 'freeform') {
      craftingShowStep('freeform');
    }
  });
});

async function craftingLoadArchetypes() {
  if (craftingBusy) return;
  craftingSetBusy(true);
  craftingRenderLoading('Loading archetypes...', 20, [
    { label: 'Request archetype catalog', state: 'active' },
    { label: 'Render starting points', state: 'pending' },
  ]);
  try {
    const resp = await fetch(`${DESIGNER_URL}/crafting/archetypes`);
    const data = await resp.json();
    const archetypes = data.archetypes || [];
    craftingArchetypes.innerHTML = archetypes.map((a: { id: string; label: string; description: string }) => `
      <div class="crafting-archetype-card" data-id="${a.id}">
        <div class="archetype-card-label">${a.label}</div>
        <div class="archetype-card-desc">${a.description}</div>
      </div>
    `).join('');

    craftingArchetypes.querySelectorAll('.crafting-archetype-card').forEach(card => {
      card.addEventListener('click', async () => {
        if (craftingBusy) return;
        const archId = (card as HTMLElement).dataset.id || '';
        craftingStatus.textContent = 'Starting from archetype...';
        craftingSetBusy(true);
        craftingRenderLoading('Starting from archetype...', 30, [
          { label: 'Create session from archetype', state: 'active' },
          { label: 'Open first comparison', state: 'pending' },
        ]);
        try {
          const result = await craftingRequest('/crafting/start', {
            mode: 'archetype',
            archetype_id: archId,
          }) as { success: boolean; session: CraftingSessionState };
          if (result.success) {
            craftingSession = result.session;
            craftingUpdateProgress();
            craftingRenderLoading('Archetype session ready', 100, [
              { label: 'Create session from archetype', state: 'done' },
              { label: 'Open first comparison', state: 'done' },
            ]);
            craftingScheduleHideLoading(400);
            craftingSetBusy(false);
            await craftingExploreCurrentAxis();
            return;
          }
        } catch (err) {
          craftingStatus.textContent = `Error: ${err}`;
          craftingRenderLoadingError('Could not start from that archetype');
        }
        craftingSetBusy(false);
      });
    });
    craftingRenderLoading('Archetypes ready', 100, [
      { label: 'Request archetype catalog', state: 'done' },
      { label: 'Render starting points', state: 'done' },
    ]);
    craftingScheduleHideLoading(400);
  } catch {
    craftingArchetypes.innerHTML = '<div class="sample-no-audio">Failed to load archetypes</div>';
    craftingStatus.textContent = 'Failed to load archetypes';
    craftingRenderLoadingError('Could not load archetypes');
  } finally {
    craftingSetBusy(false);
  }
}

// Freeform start
craftingFreeformStart.addEventListener('click', async () => {
  if (craftingBusy) return;
  const text = craftingFreeformInput.value.trim();
  if (!text) return;
  craftingStatus.textContent = 'Interpreting description...';
  craftingSetBusy(true);
  craftingRenderLoading('Interpreting your description...', 20, [
    { label: 'Send freeform description', state: 'active' },
    { label: 'Map voice traits to axes', state: 'pending' },
    { label: 'Open first unresolved comparison', state: 'pending' },
  ]);
  try {
    const result = await craftingRequest('/crafting/start', {
      mode: 'freeform',
      freeform_text: text,
    }) as { success: boolean; session: CraftingSessionState };
    if (result.success) {
      craftingSession = result.session;
      craftingUpdateProgress();
      craftingUpdateCumulative();
      craftingRenderLoading('Description mapped to crafting axes', 100, [
        { label: 'Send freeform description', state: 'done' },
        { label: 'Map voice traits to axes', state: 'done' },
        { label: 'Open first unresolved comparison', state: 'done' },
      ]);
      craftingScheduleHideLoading(400);
      craftingSetBusy(false);
      await craftingExploreCurrentAxis();
      return;
    }
  } catch (err) {
    craftingStatus.textContent = `Error: ${err}`;
    craftingRenderLoadingError('Could not interpret that description');
  }
  craftingSetBusy(false);
});

// Axis action buttons
craftingBackBtn.addEventListener('click', async () => {
  if (!craftingSession || craftingBusy) return;
  craftingStopAudio();
  craftingStatus.textContent = 'Going back...';
  craftingSetBusy(true);
  craftingRenderLoading('Returning to the previous voice axis...', 50, [
    { label: 'Restore previous axis state', state: 'active' },
    { label: 'Open updated comparison', state: 'pending' },
  ]);
  try {
    const result = await craftingRequest('/crafting/back', {
      session_id: craftingSession.session_id,
    }) as { success: boolean; session: CraftingSessionState };
    if (result.success) {
      craftingSession = result.session;
      craftingUpdateProgress();
      craftingUpdateCumulative();
      craftingRenderLoading('Previous axis restored', 100, [
        { label: 'Restore previous axis state', state: 'done' },
        { label: 'Open updated comparison', state: 'done' },
      ]);
      craftingScheduleHideLoading(350);
      craftingSetBusy(false);
      await craftingExploreCurrentAxis();
      return;
    }
  } catch (err) {
    craftingStatus.textContent = `Error: ${err}`;
    craftingRenderLoadingError('Could not return to the previous axis');
  }
  craftingSetBusy(false);
});

craftingSkipBtn.addEventListener('click', async () => {
  if (!craftingSession || craftingBusy) return;
  craftingStopAudio();
  craftingStatus.textContent = 'Skipping...';
  craftingSetBusy(true);
  craftingRenderLoading('Skipping this axis...', 50, [
    { label: 'Mark axis as skipped', state: 'active' },
    { label: 'Advance to the next step', state: 'pending' },
  ]);
  try {
    const result = await craftingRequest('/crafting/skip', {
      session_id: craftingSession.session_id,
    }) as { success: boolean; session: CraftingSessionState; is_complete: boolean };
    if (result.success) {
      craftingSession = result.session;
      craftingUpdateProgress();
      craftingUpdateCumulative();
      craftingRenderLoading('Axis skipped', 100, [
        { label: 'Mark axis as skipped', state: 'done' },
        { label: 'Advance to the next step', state: 'done' },
      ]);
      craftingScheduleHideLoading(350);
      craftingSetBusy(false);
      if (result.is_complete) {
        await craftingShowSummary();
      } else {
        await craftingExploreCurrentAxis();
      }
      return;
    }
  } catch (err) {
    craftingStatus.textContent = `Error: ${err}`;
    craftingRenderLoadingError('Could not skip this axis');
  }
  craftingSetBusy(false);
});

craftingRegenBtn.addEventListener('click', async () => {
  if (!craftingSession || craftingBusy) return;
  craftingStopAudio();
  craftingStatus.textContent = 'Regenerating this comparison...';
  craftingSetBusy(true);
  try {
    const ax = craftingSession.current_axis;
    if (!ax) return;
    craftingSamplesRow.innerHTML = '<div class="crafting-sample-card loading"></div><div class="crafting-sample-card loading"></div><div class="crafting-sample-card loading"></div>';
    const result = await craftingTrackSessionOperation(
      craftingSession.session_id,
      craftingRequest('/crafting/regenerate', {
        session_id: craftingSession.session_id,
      }) as Promise<{ success: boolean; samples: CraftingSample[]; session: CraftingSessionState }>,
      {
        label: `Regenerating ${ax.label} samples...`,
        percent: 5,
        steps: [
          { label: 'Clear previous samples', state: 'done' },
          { label: 'Generate refreshed options', state: 'active' },
        ],
      },
    );
    if (result.success) {
      craftingSession = result.session;
      craftingUpdateProgress();
      craftingUpdateCumulative();
      craftingRenderSamples(result.samples);
      craftingRenderLoading(`Finished regenerating ${ax.label}`, 100, [
        { label: 'Clear previous samples', state: 'done' },
        { label: 'Generate refreshed options', state: 'done' },
      ]);
      craftingStatus.textContent = `${result.samples.length} refreshed samples ready`;
      craftingScheduleHideLoading(600);
    }
  } catch (err) {
    craftingStatus.textContent = `Error: ${err}`;
    craftingRenderLoadingError('Could not regenerate the samples');
  } finally {
    craftingSetBusy(false);
  }
});

// Save button
craftingSaveBtn.addEventListener('click', async () => {
  if (!craftingSession || craftingBusy) return;
  const name = craftingSaveName.value.trim();
  if (!name) {
    craftingStatus.textContent = 'Please enter a name';
    return;
  }
  craftingStatus.textContent = 'Saving...';
  craftingSetBusy(true);
  try {
    const result = await craftingTrackSessionOperation(
      craftingSession.session_id,
      craftingRequest('/crafting/finish', {
        session_id: craftingSession.session_id,
        profile_name: name,
      }) as Promise<{ success: boolean; profile_id?: string }>,
      {
        label: `Saving ${name}...`,
        percent: 10,
        steps: [
          { label: 'Compile selected traits', state: 'active' },
          { label: 'Polish final prompt', state: 'pending' },
          { label: 'Save final voice', state: 'pending' },
        ],
      },
    );
    if (result.success) {
      craftingRenderLoading(`Saved ${name}`, 100, [
        { label: 'Compile selected traits', state: 'done' },
        { label: 'Polish final prompt', state: 'done' },
        { label: 'Save final voice', state: 'done' },
      ]);
      craftingStatus.textContent = `Saved as profile ${result.profile_id || name}`;
      craftingScheduleHideLoading(800);
    } else {
      craftingStatus.textContent = 'Save failed';
      craftingRenderLoadingError(`Could not save ${name}`);
    }
  } catch (err) {
    craftingStatus.textContent = `Error: ${err}`;
    craftingRenderLoadingError(`Could not save ${name}`);
  } finally {
    craftingSetBusy(false);
  }
});

// Open/close
voiceCraftingBtn.addEventListener('click', openCraftingModal);
craftingModalClose.addEventListener('click', closeCraftingModal);
craftingModal.addEventListener('click', (e) => {
  if (e.target === craftingModal) closeCraftingModal();
});

// ── Phase 3: Document Mode ────────────────────────────────

const docModeCheck = document.getElementById('doc-mode-check') as HTMLInputElement;
const docControls = document.getElementById('doc-controls') as HTMLDivElement;
const docFormatSelect = document.getElementById('doc-format-select') as HTMLSelectElement;
const docAnalyzeBtn = document.getElementById('doc-analyze-btn') as HTMLButtonElement;
const docSampleBtn = document.getElementById('doc-sample-btn') as HTMLButtonElement;
const docResultsSection = document.getElementById('doc-results-section') as HTMLElement;
const docStatsBar = document.getElementById('doc-stats-bar') as HTMLDivElement;
const docTabElements = document.getElementById('doc-tab-elements') as HTMLDivElement;
const docTabHighlight = document.getElementById('doc-tab-highlight') as HTMLDivElement;
const docTabScheme = document.getElementById('doc-tab-scheme') as HTMLDivElement;
const docSamplesDropdown = document.getElementById('doc-samples-dropdown') as HTMLDivElement;

let lastDocAnalysis: DocumentAnalysisResult | null = null;

// Toggle document mode
docModeCheck.addEventListener('change', () => {
  docControls.hidden = !docModeCheck.checked;
  if (!docModeCheck.checked) {
    docResultsSection.hidden = true;
    lastDocAnalysis = null;
  }
});

// Sample texts
const DOC_SAMPLES: Record<string, { text: string; format: string }> = {
  novel: {
    format: 'plain',
    text: `Chapter 1: The Arrival

The train pulled into the station with a long, mournful whistle. Sarah pressed her face against the cold glass, watching the unfamiliar town materialize through the fog.

"Is this it?" she whispered.

"Millfield," the conductor announced, his voice echoing through the nearly empty car. "Last stop."

She gathered her single suitcase and stepped onto the platform. The air smelled of rain and pine needles. A figure waited beneath the station's only lamppost—tall, wrapped in a dark coat, face hidden in shadow.

"You must be Sarah," the figure said. The voice was warm, unexpectedly kind. "I'm James. Your grandfather sent me."

Sarah hesitated. She hadn't seen her grandfather in fifteen years. Not since the funeral.

"He's waiting," James added softly. "He has a great deal to tell you."`,
  },
  markdown: {
    format: 'markdown',
    text: `# Getting Started with WebVox

WebVox is a **powerful** text-to-speech platform that supports multiple engines.

## Installation

First, clone the repository:

\`\`\`bash
git clone https://github.com/example/webvox.git
cd webvox
npm install
\`\`\`

## Features

- Multiple TTS engine support
- Real-time word highlighting
- Voice cloning capabilities
- *Quality analysis* with AI models

## Configuration

The main config file is \`device_config.json\`. Edit this to set up your GPU/CPU preferences.

> **Note:** For best results, use a CUDA-compatible GPU with at least 8GB VRAM.

See the [documentation](https://docs.webvox.dev) for more details.`,
  },
  html: {
    format: 'html',
    text: `<h1>Breaking News: AI Revolution</h1>
<p>Scientists at the <strong>Global Research Institute</strong> announced today a breakthrough in artificial intelligence that could transform how we interact with technology.</p>
<h2>Key Findings</h2>
<p>The research team, led by <em>Dr. Elena Martinez</em>, demonstrated a system capable of understanding natural language with unprecedented accuracy.</p>
<blockquote>This represents a paradigm shift in human-computer interaction. We are witnessing the dawn of truly intelligent machines.</blockquote>
<p>The technology uses a novel approach combining:</p>
<ul>
<li>Neural network architectures</li>
<li>Reinforcement learning</li>
<li>Knowledge graph integration</li>
</ul>
<p>For more information, visit the <a href="https://example.com">official website</a>.</p>`,
  },
  dialogue: {
    format: 'plain',
    text: `The courtroom fell silent as the judge entered.

"All rise," the bailiff called.

Judge Morrison took her seat and surveyed the room. "Be seated. Counselor, you may proceed."

"Thank you, Your Honor." Attorney Chen straightened his tie and approached the witness stand. "Mr. Davis, can you tell the court what you saw on the night of March 15th?"

Davis shifted uncomfortably. "I was walking home from the store. Around nine, nine-thirty maybe."

"And what did you observe?"

"I heard shouting first," Davis said, his voice barely above a whisper. "Then I saw two people near the alley."

"Objection!" the defense attorney stood abruptly. "Leading the witness."

"Overruled," Judge Morrison said firmly. "Continue, Mr. Chen."`,
  },
  technical: {
    format: 'markdown',
    text: `# WebSocket Protocol Reference

## Message Types

The protocol defines two categories of messages:

### Client Messages

\`\`\`typescript
interface ClientMessage {
  type: 'synthesize' | 'cancel' | 'list_voices';
  id?: string;
  text?: string;
  voice_id?: string;
}
\`\`\`

### Host Messages

Host messages include \`audio_chunk\`, \`word_boundary\`, and \`synthesis_complete\`.

## Connection Flow

1. Client connects via WebSocket to \`ws://localhost:21740\`
2. Server sends initial \`system_info\` message
3. Client sends \`list_voices\` to get available engines
4. Client sends \`synthesize\` with text and voice selection

> **Important:** Always handle the \`error\` message type for graceful degradation.

The default sample rate is \`22050 Hz\` for most engines.`,
  },
};

// Samples dropdown
docSampleBtn.addEventListener('click', (e) => {
  e.stopPropagation();
  if (!docSamplesDropdown.hidden) {
    docSamplesDropdown.hidden = true;
    return;
  }
  const rect = docSampleBtn.getBoundingClientRect();
  docSamplesDropdown.style.top = `${rect.bottom + 4}px`;
  docSamplesDropdown.style.left = `${rect.left}px`;
  docSamplesDropdown.hidden = false;
});

document.addEventListener('click', () => {
  docSamplesDropdown.hidden = true;
});

docSamplesDropdown.addEventListener('click', (e) => {
  const item = (e.target as HTMLElement).closest('.doc-sample-item') as HTMLElement;
  if (!item) return;
  const key = item.dataset.sample;
  if (!key || !DOC_SAMPLES[key]) return;
  const sample = DOC_SAMPLES[key];
  textInput.value = sample.text;
  docFormatSelect.value = sample.format;
  docSamplesDropdown.hidden = true;
  generateBtn.disabled = !selectedVoiceId;
  log(`Loaded sample: ${key}`, 'info');
});

// Analyze button
docAnalyzeBtn.addEventListener('click', async () => {
  const text = textInput.value.trim();
  if (!text) {
    log('No text to analyze', 'warn');
    return;
  }

  docAnalyzeBtn.disabled = true;
  docAnalyzeBtn.classList.add('analyzing');
  docAnalyzeBtn.textContent = 'Analyzing...';
  log('Analyzing document structure...');

  try {
    const format = docFormatSelect.value;
    const result = await nativeEngine.analyzeDocument(text, format, false);
    lastDocAnalysis = result;

    if (!result.success) {
      log(`Document analysis failed: ${result.error}`, 'error');
      return;
    }

    log(`Document analyzed: ${result.elements.length} elements, format=${result.format}`, 'success');
    renderDocResults(result);
    docResultsSection.hidden = false;
  } catch (err) {
    log(`Document analysis error: ${err instanceof Error ? err.message : err}`, 'error');
  } finally {
    docAnalyzeBtn.disabled = false;
    docAnalyzeBtn.classList.remove('analyzing');
    docAnalyzeBtn.textContent = 'Analyze Structure';
  }
});

// Tab switching
document.querySelectorAll('.doc-tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.doc-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    const target = (tab as HTMLElement).dataset.tab;
    docTabElements.hidden = target !== 'elements';
    docTabHighlight.hidden = target !== 'highlight';
    docTabScheme.hidden = target !== 'scheme';
  });
});

function renderDocResults(result: DocumentAnalysisResult) {
  // Stats bar
  if (result.stats) {
    const s = result.stats;
    docStatsBar.innerHTML = '';
    const addStat = (label: string, value: string | number) => {
      const span = document.createElement('span');
      span.className = 'doc-stat';
      span.innerHTML = `<span class="doc-stat-label">${label}:</span> ${value}`;
      docStatsBar.appendChild(span);
    };
    addStat('Format', result.format ?? 'unknown');
    addStat('Elements', s.totalElements);
    addStat('Words', s.totalWords);
    addStat('Chars', s.totalChars);
    addStat('Time', `${s.analysisTimeMs.toFixed(0)}ms`);
    if (s.aiEnhanced) addStat('AI', 'enhanced');
  }

  // Elements tab
  docTabElements.innerHTML = '';
  for (const el of result.elements) {
    const row = document.createElement('div');
    row.className = 'doc-element';

    const badge = document.createElement('span');
    badge.className = 'doc-el-badge';
    badge.dataset.type = el.type;
    badge.textContent = el.type.replace('_', ' ');
    row.appendChild(badge);

    const text = document.createElement('span');
    text.className = 'doc-el-text';
    const preview = el.text.length > 120 ? el.text.slice(0, 120) + '...' : el.text;
    text.textContent = preview;
    row.appendChild(text);

    if (el.voice) {
      const voiceDiv = document.createElement('span');
      voiceDiv.className = 'doc-el-voice';
      if (el.voice.rate !== 1.0) {
        const tag = document.createElement('span');
        tag.className = 'doc-voice-tag';
        tag.textContent = `${el.voice.rate.toFixed(1)}x`;
        voiceDiv.appendChild(tag);
      }
      if (el.voice.pitch !== 1.0) {
        const tag = document.createElement('span');
        tag.className = 'doc-voice-tag';
        tag.textContent = `P${el.voice.pitch.toFixed(1)}`;
        voiceDiv.appendChild(tag);
      }
      if (el.voice.voiceHint) {
        const tag = document.createElement('span');
        tag.className = 'doc-voice-tag';
        tag.textContent = el.voice.voiceHint;
        voiceDiv.appendChild(tag);
      }
      row.appendChild(voiceDiv);
    }

    docTabElements.appendChild(row);
  }

  // Highlight tab
  docTabHighlight.innerHTML = '';
  const hlDiv = document.createElement('div');
  hlDiv.className = 'doc-highlight-preview';
  for (const el of result.elements) {
    const span = document.createElement('span');
    span.className = `doc-hl-${el.type}`;
    span.textContent = el.text;
    hlDiv.appendChild(span);
  }
  docTabHighlight.appendChild(hlDiv);

  // Voice scheme tab
  docTabScheme.innerHTML = '';
  const uniqueTypes = new Map<string, DocumentElement>();
  for (const el of result.elements) {
    if (el.voice && !uniqueTypes.has(el.type)) {
      uniqueTypes.set(el.type, el);
    }
  }

  if (uniqueTypes.size === 0) {
    docTabScheme.textContent = 'No voice scheme data available.';
    return;
  }

  const table = document.createElement('table');
  table.className = 'doc-scheme-table';
  table.innerHTML = `<thead><tr>
    <th>Element</th><th>Rate</th><th>Pitch</th><th>Volume</th><th>Pause</th><th>Voice Hint</th>
  </tr></thead>`;
  const tbody = document.createElement('tbody');

  for (const [type, el] of uniqueTypes) {
    const v = el.voice!;
    const tr = document.createElement('tr');

    const tdType = document.createElement('td');
    const typeBadge = document.createElement('span');
    typeBadge.className = 'doc-el-badge';
    typeBadge.dataset.type = type;
    typeBadge.textContent = type.replace('_', ' ');
    tdType.appendChild(typeBadge);
    tr.appendChild(tdType);

    // Rate bar
    const tdRate = document.createElement('td');
    tdRate.innerHTML = `<div class="doc-scheme-bar"><div class="doc-scheme-bar-fill rate" style="width:${Math.min(v.rate / 2 * 100, 100)}%"></div></div> ${v.rate.toFixed(1)}x`;
    tr.appendChild(tdRate);

    // Pitch bar
    const tdPitch = document.createElement('td');
    tdPitch.innerHTML = `<div class="doc-scheme-bar"><div class="doc-scheme-bar-fill pitch" style="width:${Math.min(v.pitch / 2 * 100, 100)}%"></div></div> ${v.pitch.toFixed(1)}`;
    tr.appendChild(tdPitch);

    // Volume bar
    const tdVol = document.createElement('td');
    tdVol.innerHTML = `<div class="doc-scheme-bar"><div class="doc-scheme-bar-fill volume" style="width:${Math.min(v.volume / 1.5 * 100, 100)}%"></div></div> ${v.volume.toFixed(1)}`;
    tr.appendChild(tdVol);

    // Pause
    const tdPause = document.createElement('td');
    tdPause.textContent = `${v.pauseBeforeMs}/${v.pauseAfterMs}ms`;
    tdPause.style.fontSize = '0.75rem';
    tdPause.style.color = 'var(--text-dim)';
    tr.appendChild(tdPause);

    // Voice hint
    const tdHint = document.createElement('td');
    tdHint.textContent = v.voiceHint ?? '—';
    tdHint.style.fontSize = '0.75rem';
    tdHint.style.color = 'var(--text-dim)';
    tr.appendChild(tdHint);

    tbody.appendChild(tr);
  }

  table.appendChild(tbody);
  docTabScheme.appendChild(table);
}

// ── Boot ──────────────────────────────────────────────────
init().then(() => {
  startStackPoll();
}).catch((err) => log(`Init failed: ${err}`, 'error'));
