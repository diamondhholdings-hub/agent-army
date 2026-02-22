/**
 * HeyGen LiveKit Avatar Session in browser.
 *
 * Uses livekit-client Room to connect to HeyGen's LiveKit room
 * for WebRTC-based avatar video streaming. The avatar appears as
 * the bot's camera feed in the meeting.
 *
 * Per CONTEXT.md LOCKED decisions:
 * - Fully animated with natural movements (lip-sync, head nods, eye contact)
 * - Context-aware idle reactions (nod, interested, thinking)
 * - Always visible like other participants
 *
 * Architecture:
 * - LiveKit Room receives video track from HeyGen avatar
 * - Video track attached to #avatar-video element
 * - speak() sends text to HeyGen streaming.task API for lip-synced delivery
 * - sendReaction() sends idle behavior cues
 */

// Import livekit-client for WebRTC room management
// This is the only npm dependency per RESEARCH Pitfall 2
// Static import for esbuild bundling (top-level await not supported in es2020 target)
import { Room, RoomEvent } from 'livekit-client';

// HeyGen Streaming API endpoint
const HEYGEN_API_BASE = 'https://api.heygen.com/v1';

export class HeyGenSession {
  /**
   * @param {HTMLVideoElement} videoElement - Video element for avatar rendering
   */
  constructor(videoElement) {
    this._videoEl = videoElement;
    this._room = null;
    this._sessionId = null;
    this._apiToken = null;
    this._isConnected = false;
  }

  /**
   * Connect to HeyGen's LiveKit room for avatar video streaming.
   *
   * @param {string} url - LiveKit room URL from HeyGen session
   * @param {string} accessToken - LiveKit access token from HeyGen session
   * @returns {Promise<void>}
   */
  async connect(url, accessToken) {
    if (!Room) {
      throw new Error('livekit-client not available');
    }

    this._room = new Room();

    // Handle track subscribed -- attach video to element
    this._room.on(RoomEvent.TrackSubscribed, (track, publication, participant) => {
      if (track.kind === 'video') {
        console.log('[heygen-session] Video track subscribed');
        track.attach(this._videoEl);
      }
    });

    // Handle track unsubscribed -- detach
    this._room.on(RoomEvent.TrackUnsubscribed, (track) => {
      if (track.kind === 'video') {
        console.log('[heygen-session] Video track unsubscribed');
        track.detach(this._videoEl);
      }
    });

    // Handle disconnection
    this._room.on(RoomEvent.Disconnected, () => {
      console.log('[heygen-session] Room disconnected');
      this._isConnected = false;
    });

    // Connect to LiveKit room
    await this._room.connect(url, accessToken);
    this._isConnected = true;
    console.log('[heygen-session] Connected to LiveKit room');
  }

  /**
   * Make the avatar speak with lip-sync.
   *
   * POST to HeyGen streaming.task with task_type "repeat" for
   * exact text reproduction. Per CONTEXT.md: fully animated with
   * natural movements, lip-sync critical.
   *
   * @param {string} text - Text for the avatar to speak
   * @returns {Promise<void>}
   */
  async speak(text) {
    if (!this._sessionId) {
      console.warn('[heygen-session] No session ID -- cannot speak');
      return;
    }

    const response = await fetch(`${HEYGEN_API_BASE}/streaming.task`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this._apiToken}`,
      },
      body: JSON.stringify({
        session_id: this._sessionId,
        text: text,
        task_type: 'repeat',
      }),
    });

    if (!response.ok) {
      throw new Error(`HeyGen speak failed: ${response.status} ${response.statusText}`);
    }

    console.debug('[heygen-session] Speak:', text.substring(0, 50));
  }

  /**
   * Send idle reaction for context-aware avatar behavior.
   *
   * Per CONTEXT.md: avatar reacts to meeting content with nods,
   * interested looks, etc., even when not speaking.
   *
   * @param {string} reaction - Reaction type: "nod", "interested", "thinking"
   * @returns {Promise<void>}
   */
  async sendReaction(reaction) {
    if (!this._sessionId) {
      console.warn('[heygen-session] No session ID -- cannot react');
      return;
    }

    // Map reactions to avatar text cues (matching backend HeyGenAvatar)
    const reactionCues = {
      nod: 'I see.',
      interested: "That's interesting.",
      thinking: 'Let me think about that.',
    };
    const cueText = reactionCues[reaction] || 'I see.';

    const response = await fetch(`${HEYGEN_API_BASE}/streaming.task`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this._apiToken}`,
      },
      body: JSON.stringify({
        session_id: this._sessionId,
        text: cueText,
        task_type: 'talk',
      }),
    });

    if (!response.ok) {
      throw new Error(`HeyGen reaction failed: ${response.status}`);
    }

    console.debug('[heygen-session] Reaction:', reaction);
  }

  /**
   * Set HeyGen session details for API calls.
   *
   * Called after backend creates the HeyGen session and provides
   * session_id and api_token.
   *
   * @param {string} sessionId - HeyGen streaming session ID
   * @param {string} apiToken - HeyGen API token
   */
  setSession(sessionId, apiToken) {
    this._sessionId = sessionId;
    this._apiToken = apiToken;
    console.log('[heygen-session] Session configured:', sessionId);
  }

  /**
   * Disconnect from LiveKit room and clean up.
   */
  disconnect() {
    if (this._room) {
      try {
        this._room.disconnect();
      } catch (err) {
        console.warn('[heygen-session] Disconnect error:', err);
      }
      this._room = null;
    }
    this._isConnected = false;
    this._sessionId = null;
    this._apiToken = null;
  }

  /**
   * Check if connected to LiveKit room.
   * @returns {boolean}
   */
  get isConnected() {
    return this._isConnected;
  }
}
