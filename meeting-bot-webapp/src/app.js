/**
 * Output Media Webapp -- Main Orchestrator
 *
 * This page renders inside Recall.ai's headless browser as the bot's
 * camera and audio source. It coordinates:
 *
 * 1. Audio capture: getUserMedia -> virtual microphone from Recall.ai
 * 2. STT: Raw audio frames -> Deepgram WebSocket for transcription
 * 3. LLM Bridge: Transcripts -> backend WebSocket for LLM reasoning
 * 4. Avatar: LLM responses -> HeyGen LiveKit avatar for lip-synced delivery
 *
 * Per RESEARCH Pitfall 2: Keep this MINIMAL. Vanilla JS, no framework.
 */

import { DeepgramSTTClient } from './pipeline/deepgram-stt.js';
import { LLMBridge } from './pipeline/llm-bridge.js';
import { HeyGenSession } from './avatar/heygen-session.js';
import { AudioCaptureProcessor } from './utils/audio-processor.js';

// ── Configuration from URL query parameters ──────────────────────────────

function getConfig() {
  const params = new URLSearchParams(window.location.search);
  return {
    meetingId: params.get('meeting_id') || '',
    tenantId: params.get('tenant_id') || '',
    backendWsUrl: params.get('backend_ws_url') || window.location.host,
    heygenToken: params.get('heygen_token') || '',
    deepgramKey: params.get('deepgram_key') || '',
    heygenUrl: params.get('heygen_url') || '',
    heygenAccessToken: params.get('heygen_access_token') || '',
  };
}

// ── Status Display ───────────────────────────────────────────────────────

const statusEl = document.getElementById('status');

function updateStatus(component, state, message) {
  if (!statusEl) return;
  const cls = state === 'ok' ? 'ok' : state === 'error' ? 'err' : 'pending';
  // Find or create status line for this component
  let line = statusEl.querySelector(`[data-component="${component}"]`);
  if (!line) {
    line = document.createElement('div');
    line.setAttribute('data-component', component);
    statusEl.appendChild(line);
  }
  line.className = cls;
  line.textContent = `${component}: ${message}`;
}

// ── Main Initialization ──────────────────────────────────────────────────

let audioProcessor = null;
let deepgramClient = null;
let llmBridge = null;
let heygenSession = null;

async function init() {
  const config = getConfig();

  updateStatus('system', 'pending', 'Starting...');

  // Step 1: Initialize audio capture from Recall.ai virtual microphone
  let audioStream = null;
  try {
    audioStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    updateStatus('audio', 'ok', 'Capturing');
  } catch (err) {
    console.error('[app] Audio capture failed:', err);
    updateStatus('audio', 'error', err.message);
  }

  // Step 2: Initialize Deepgram STT WebSocket
  try {
    deepgramClient = new DeepgramSTTClient(config.deepgramKey);
    deepgramClient.onTranscript((transcript, isFinal, speakerId) => {
      // Route transcripts to LLM Bridge
      if (llmBridge) {
        llmBridge.sendTranscript(transcript, isFinal, speakerId);
      }
    });
    deepgramClient.onUtteranceEnd(() => {
      console.debug('[app] Utterance end detected');
    });
    await deepgramClient.connect();
    updateStatus('stt', 'ok', 'Connected');
  } catch (err) {
    console.error('[app] Deepgram STT init failed:', err);
    updateStatus('stt', 'error', err.message);
  }

  // Step 3: Initialize LLM Bridge WebSocket to backend
  try {
    llmBridge = new LLMBridge(config.backendWsUrl, config.meetingId);
    llmBridge.onResponse((response) => {
      // Route LLM responses to HeyGen avatar
      if (response.type === 'speak' && heygenSession) {
        heygenSession.speak(response.text).catch((err) => {
          console.error('[app] Avatar speak failed:', err);
        });
      } else if (response.type === 'reaction' && heygenSession) {
        heygenSession.sendReaction(response.reaction).catch((err) => {
          console.error('[app] Avatar reaction failed:', err);
        });
      }
      // type === 'silence' -- do nothing (agent stays silent)
    });
    llmBridge.connect();
    updateStatus('llm', 'ok', 'Connected');
  } catch (err) {
    console.error('[app] LLM Bridge init failed:', err);
    updateStatus('llm', 'error', err.message);
  }

  // Step 4: Initialize HeyGen avatar session (LiveKit room)
  try {
    const videoEl = document.getElementById('avatar-video');
    heygenSession = new HeyGenSession(videoEl);

    if (config.heygenUrl && config.heygenAccessToken) {
      await heygenSession.connect(config.heygenUrl, config.heygenAccessToken);
      updateStatus('avatar', 'ok', 'Connected');
    } else {
      updateStatus('avatar', 'pending', 'Awaiting session info');
    }
  } catch (err) {
    console.error('[app] HeyGen avatar init failed:', err);
    updateStatus('avatar', 'error', err.message);
  }

  // Step 5: Start audio processing pipeline
  if (audioStream && deepgramClient) {
    try {
      audioProcessor = new AudioCaptureProcessor(audioStream);
      audioProcessor.start((pcmBytes) => {
        deepgramClient.send(pcmBytes);
      });
      updateStatus('pipeline', 'ok', 'Audio flowing');
    } catch (err) {
      console.error('[app] Audio processor start failed:', err);
      updateStatus('pipeline', 'error', err.message);
    }
  }

  updateStatus('system', 'ok', 'Running');
}

// ── Cleanup ──────────────────────────────────────────────────────────────

function cleanup() {
  if (audioProcessor) {
    audioProcessor.stop();
    audioProcessor = null;
  }
  if (deepgramClient) {
    deepgramClient.close();
    deepgramClient = null;
  }
  if (llmBridge) {
    llmBridge.disconnect();
    llmBridge = null;
  }
  if (heygenSession) {
    heygenSession.disconnect();
    heygenSession = null;
  }
}

window.addEventListener('beforeunload', cleanup);

// ── Start ────────────────────────────────────────────────────────────────

init().catch((err) => {
  console.error('[app] Initialization failed:', err);
  updateStatus('system', 'error', `Init failed: ${err.message}`);
});
