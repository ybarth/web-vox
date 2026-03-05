/**
 * Background service worker — handles native messaging and ttsEngine registration.
 * Phase 3 implementation stub.
 */

const NATIVE_HOST_NAME = 'com.webvox.native_host';

console.log('[web-vox] Background service worker loaded');

// Register as TTS engine (Chrome only)
if (typeof chrome !== 'undefined' && chrome.ttsEngine) {
  chrome.ttsEngine.onSpeak.addListener((utterance, _options, sendTtsEvent) => {
    console.log('[web-vox] ttsEngine.onSpeak:', utterance);
    sendTtsEvent({ type: 'start', charIndex: 0 });
    // Phase 3: Forward to native host via native messaging
    sendTtsEvent({ type: 'end', charIndex: utterance.length });
  });

  chrome.ttsEngine.onStop.addListener(() => {
    console.log('[web-vox] ttsEngine.onStop');
  });
}
