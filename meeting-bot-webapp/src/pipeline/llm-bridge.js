/**
 * LLM Bridge -- WebSocket connection to backend for LLM reasoning.
 *
 * Routes transcripts from the browser to the backend real-time pipeline
 * and receives LLM responses for avatar delivery.
 *
 * Protocol:
 * - Send: { type: "transcript", text: "...", is_final: true, speaker_id: "0" }
 * - Receive: { type: "speak", text: "...", confidence: 0.85 }
 * - Receive: { type: "silence" }
 * - Receive: { type: "reaction", reaction: "nod" }
 *
 * Reconnection: auto-reconnect on disconnect with exponential backoff (1s, 2s, 4s).
 */

const INITIAL_RECONNECT_DELAY_MS = 1000;
const MAX_RECONNECT_DELAY_MS = 4000;
const RECONNECT_BACKOFF_FACTOR = 2;

export class LLMBridge {
  /**
   * @param {string} backendWsUrl - Backend WebSocket host (e.g., "localhost:8000")
   * @param {string} meetingId - Meeting UUID for WebSocket path
   */
  constructor(backendWsUrl, meetingId) {
    this._url = `ws://${backendWsUrl}/ws/meeting/${meetingId}`;
    this._ws = null;
    this._onResponseCb = null;
    this._reconnectDelay = INITIAL_RECONNECT_DELAY_MS;
    this._shouldReconnect = true;
    this._reconnectTimer = null;
  }

  /**
   * Register response callback.
   * @param {function({type: string, text?: string, confidence?: number, reaction?: string}): void} callback
   */
  onResponse(callback) {
    this._onResponseCb = callback;
  }

  /**
   * Connect to the backend WebSocket.
   */
  connect() {
    this._shouldReconnect = true;
    this._createConnection();
  }

  /**
   * Send transcript to backend for LLM processing.
   * @param {string} transcript - Transcript text
   * @param {boolean} isFinal - Whether this is a final transcript
   * @param {string|null} speakerId - Speaker identifier from diarization
   */
  sendTranscript(transcript, isFinal, speakerId) {
    if (!this._ws || this._ws.readyState !== WebSocket.OPEN) {
      console.warn('[llm-bridge] Cannot send -- not connected');
      return;
    }

    const message = JSON.stringify({
      type: 'transcript',
      text: transcript,
      is_final: isFinal,
      speaker_id: speakerId || 'unknown',
    });

    this._ws.send(message);
  }

  /**
   * Disconnect and stop reconnection attempts.
   */
  disconnect() {
    this._shouldReconnect = false;
    if (this._reconnectTimer) {
      clearTimeout(this._reconnectTimer);
      this._reconnectTimer = null;
    }
    if (this._ws) {
      try {
        this._ws.close();
      } catch (err) {
        console.warn('[llm-bridge] Close error:', err);
      }
      this._ws = null;
    }
  }

  /**
   * Create WebSocket connection with event handlers.
   * @private
   */
  _createConnection() {
    try {
      this._ws = new WebSocket(this._url);

      this._ws.onopen = () => {
        console.log('[llm-bridge] Connected to', this._url);
        this._reconnectDelay = INITIAL_RECONNECT_DELAY_MS;
      };

      this._ws.onerror = (err) => {
        console.error('[llm-bridge] WebSocket error:', err);
      };

      this._ws.onclose = (event) => {
        console.log('[llm-bridge] Disconnected:', event.code, event.reason);
        this._scheduleReconnect();
      };

      this._ws.onmessage = (event) => {
        this._handleMessage(event);
      };
    } catch (err) {
      console.error('[llm-bridge] Connection failed:', err);
      this._scheduleReconnect();
    }
  }

  /**
   * Schedule reconnection with exponential backoff.
   * @private
   */
  _scheduleReconnect() {
    if (!this._shouldReconnect) return;

    console.log(`[llm-bridge] Reconnecting in ${this._reconnectDelay}ms...`);
    this._reconnectTimer = setTimeout(() => {
      this._createConnection();
    }, this._reconnectDelay);

    // Exponential backoff: 1s -> 2s -> 4s (capped)
    this._reconnectDelay = Math.min(
      this._reconnectDelay * RECONNECT_BACKOFF_FACTOR,
      MAX_RECONNECT_DELAY_MS
    );
  }

  /**
   * Handle incoming WebSocket messages from backend.
   * @param {MessageEvent} event
   * @private
   */
  _handleMessage(event) {
    try {
      const data = JSON.parse(event.data);

      if (this._onResponseCb) {
        this._onResponseCb(data);
      }
    } catch (err) {
      console.warn('[llm-bridge] Message parse error:', err);
    }
  }
}
