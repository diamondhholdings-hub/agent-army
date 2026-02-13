/**
 * Browser-side Deepgram STT WebSocket client.
 *
 * Connects to Deepgram's WebSocket API for real-time speech-to-text
 * transcription with speaker diarization and endpointing.
 *
 * Configuration matches backend DeepgramSTT:
 * - model: nova-3 (best accuracy + streaming latency ~250ms)
 * - endpointing: 300ms (fast-paced conversation)
 * - utterance_end_ms: 1000ms (clear turn detection)
 * - encoding: linear16 at 16000Hz (matches Recall.ai audio format)
 * - diarize: true (multi-participant speaker identification)
 */

const DEEPGRAM_WS_URL = 'wss://api.deepgram.com/v1/listen';

export class DeepgramSTTClient {
  /**
   * @param {string} apiKey - Deepgram API key
   */
  constructor(apiKey) {
    this._apiKey = apiKey;
    this._ws = null;
    this._onTranscriptCb = null;
    this._onUtteranceEndCb = null;
  }

  /**
   * Register transcript callback.
   * @param {function(string, boolean, string|null): void} callback
   *   (transcript, isFinal, speakerId)
   */
  onTranscript(callback) {
    this._onTranscriptCb = callback;
  }

  /**
   * Register utterance end callback.
   * @param {function(): void} callback
   */
  onUtteranceEnd(callback) {
    this._onUtteranceEndCb = callback;
  }

  /**
   * Connect to Deepgram WebSocket with configured options.
   * @returns {Promise<void>}
   */
  async connect() {
    const params = new URLSearchParams({
      model: 'nova-3',
      language: 'en-US',
      smart_format: 'true',
      interim_results: 'true',
      endpointing: '300',
      utterance_end_ms: '1000',
      vad_events: 'true',
      diarize: 'true',
      encoding: 'linear16',
      sample_rate: '16000',
      channels: '1',
    });

    const url = `${DEEPGRAM_WS_URL}?${params.toString()}`;

    return new Promise((resolve, reject) => {
      this._ws = new WebSocket(url, ['token', this._apiKey]);

      this._ws.onopen = () => {
        console.log('[deepgram-stt] Connected');
        resolve();
      };

      this._ws.onerror = (err) => {
        console.error('[deepgram-stt] WebSocket error:', err);
        reject(err);
      };

      this._ws.onclose = (event) => {
        console.log('[deepgram-stt] Disconnected:', event.code, event.reason);
      };

      this._ws.onmessage = (event) => {
        this._handleMessage(event);
      };
    });
  }

  /**
   * Send raw audio data to Deepgram WebSocket.
   * @param {ArrayBuffer|Uint8Array} audioData - Raw PCM audio frames
   */
  send(audioData) {
    if (this._ws && this._ws.readyState === WebSocket.OPEN) {
      this._ws.send(audioData);
    }
  }

  /**
   * Close WebSocket connection.
   */
  close() {
    if (this._ws) {
      try {
        // Send close frame to Deepgram
        this._ws.send(JSON.stringify({ type: 'CloseStream' }));
        this._ws.close();
      } catch (err) {
        console.warn('[deepgram-stt] Close error:', err);
      }
      this._ws = null;
    }
  }

  /**
   * Handle incoming WebSocket messages from Deepgram.
   * @param {MessageEvent} event
   * @private
   */
  _handleMessage(event) {
    try {
      const data = JSON.parse(event.data);

      // Utterance end event
      if (data.type === 'UtteranceEnd') {
        if (this._onUtteranceEndCb) {
          this._onUtteranceEndCb();
        }
        return;
      }

      // Transcript result
      if (data.type === 'Results' && data.channel) {
        const alt = data.channel.alternatives && data.channel.alternatives[0];
        if (!alt || !alt.transcript) return;

        const transcript = alt.transcript;
        const isFinal = data.is_final || false;

        // Extract speaker ID from diarization
        let speakerId = null;
        if (alt.words && alt.words.length > 0 && alt.words[0].speaker !== undefined) {
          speakerId = String(alt.words[0].speaker);
        }

        if (this._onTranscriptCb) {
          this._onTranscriptCb(transcript, isFinal, speakerId);
        }
      }
    } catch (err) {
      console.warn('[deepgram-stt] Message parse error:', err);
    }
  }
}
