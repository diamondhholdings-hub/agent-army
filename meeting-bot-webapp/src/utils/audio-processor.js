/**
 * Audio Capture Processor for meeting audio.
 *
 * Takes a MediaStream from getUserMedia (Recall.ai's virtual microphone)
 * and processes raw audio frames into Int16Array (linear16 PCM) format
 * for sending to Deepgram STT.
 *
 * Uses MediaStreamTrackProcessor API for efficient frame-level access
 * to audio data without AudioWorklet overhead.
 *
 * Audio format: 16-bit PCM, 16kHz, mono (matching Deepgram config).
 */

const TARGET_SAMPLE_RATE = 16000;

export class AudioCaptureProcessor {
  /**
   * @param {MediaStream} stream - Audio MediaStream from getUserMedia
   */
  constructor(stream) {
    this._stream = stream;
    this._reader = null;
    this._isRunning = false;
    this._audioContext = null;
  }

  /**
   * Start processing audio frames.
   *
   * Reads raw audio from the MediaStream and converts to Int16Array
   * (linear16 PCM) suitable for Deepgram. Calls the callback with
   * PCM bytes on each frame.
   *
   * Uses MediaStreamTrackProcessor if available (Chrome 94+),
   * falls back to ScriptProcessorNode for older browsers.
   *
   * @param {function(ArrayBuffer): void} callback - Called with PCM audio bytes
   */
  start(callback) {
    if (this._isRunning) return;
    this._isRunning = true;

    const audioTrack = this._stream.getAudioTracks()[0];
    if (!audioTrack) {
      console.error('[audio-processor] No audio track in stream');
      return;
    }

    // Try MediaStreamTrackProcessor (modern API)
    if (typeof MediaStreamTrackProcessor !== 'undefined') {
      this._startWithTrackProcessor(audioTrack, callback);
    } else {
      // Fallback: ScriptProcessorNode (deprecated but widely supported)
      this._startWithScriptProcessor(callback);
    }
  }

  /**
   * Stop processing audio frames.
   */
  stop() {
    this._isRunning = false;

    if (this._reader) {
      try {
        this._reader.cancel();
      } catch (err) {
        console.warn('[audio-processor] Reader cancel error:', err);
      }
      this._reader = null;
    }

    if (this._audioContext) {
      try {
        this._audioContext.close();
      } catch (err) {
        console.warn('[audio-processor] AudioContext close error:', err);
      }
      this._audioContext = null;
    }

    // Stop all tracks
    this._stream.getTracks().forEach((track) => track.stop());
  }

  /**
   * Modern path: MediaStreamTrackProcessor for frame-level access.
   * @param {MediaStreamTrack} track
   * @param {function(ArrayBuffer): void} callback
   * @private
   */
  async _startWithTrackProcessor(track, callback) {
    try {
      const processor = new MediaStreamTrackProcessor({ track });
      this._reader = processor.readable.getReader();

      while (this._isRunning) {
        const { value: audioData, done } = await this._reader.read();
        if (done || !this._isRunning) break;

        // Convert AudioData to Int16Array PCM
        const pcmBytes = this._audioDataToInt16(audioData);
        audioData.close();

        if (pcmBytes && pcmBytes.byteLength > 0) {
          callback(pcmBytes.buffer);
        }
      }
    } catch (err) {
      if (this._isRunning) {
        console.error('[audio-processor] TrackProcessor error:', err);
      }
    }
  }

  /**
   * Fallback path: ScriptProcessorNode for audio processing.
   * @param {function(ArrayBuffer): void} callback
   * @private
   */
  _startWithScriptProcessor(callback) {
    this._audioContext = new (window.AudioContext || window.webkitAudioContext)({
      sampleRate: TARGET_SAMPLE_RATE,
    });

    const source = this._audioContext.createMediaStreamSource(this._stream);
    // Buffer size 4096 at 16kHz = ~256ms chunks
    const scriptNode = this._audioContext.createScriptProcessor(4096, 1, 1);

    scriptNode.onaudioprocess = (event) => {
      if (!this._isRunning) return;

      const inputData = event.inputBuffer.getChannelData(0);
      const pcmBytes = this._float32ToInt16(inputData);
      callback(pcmBytes.buffer);
    };

    source.connect(scriptNode);
    scriptNode.connect(this._audioContext.destination);

    console.log('[audio-processor] Using ScriptProcessorNode fallback');
  }

  /**
   * Convert AudioData frame to Int16Array PCM.
   * @param {AudioData} audioData
   * @returns {Int16Array}
   * @private
   */
  _audioDataToInt16(audioData) {
    const numFrames = audioData.numberOfFrames;
    const float32 = new Float32Array(numFrames);

    // Copy first channel data
    audioData.copyTo(float32, { planeIndex: 0 });

    return this._float32ToInt16(float32);
  }

  /**
   * Convert Float32Array audio to Int16Array PCM.
   * @param {Float32Array} float32
   * @returns {Int16Array}
   * @private
   */
  _float32ToInt16(float32) {
    const int16 = new Int16Array(float32.length);
    for (let i = 0; i < float32.length; i++) {
      // Clamp to [-1, 1] and scale to Int16 range
      const s = Math.max(-1, Math.min(1, float32[i]));
      int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return int16;
  }
}
