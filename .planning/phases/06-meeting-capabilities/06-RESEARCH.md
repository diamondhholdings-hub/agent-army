# Phase 6: Meeting Capabilities - Research

**Researched:** 2026-02-13
**Domain:** Real-time meeting participation -- meeting bot infrastructure (Recall.ai), animated avatar rendering (HeyGen LiveAvatar/LiveKit), streaming speech-to-text (Deepgram), streaming text-to-speech (ElevenLabs), sub-1s audio pipeline orchestration, Google Calendar integration, and LLM-powered meeting minutes generation
**Confidence:** MEDIUM-HIGH

## Summary

Phase 6 is the most technically complex phase in the roadmap. It introduces real-time audio/video processing -- a fundamentally different engineering domain from the text-based agent built in Phases 1-5. The core challenge is achieving sub-1-second end-to-end latency across a chained pipeline: speech-to-text (STT) -> LLM reasoning -> text-to-speech (TTS) -> avatar rendering, all while the bot participates as a visible, animated avatar in Google Meet.

The standard approach uses a three-layer architecture: (1) Recall.ai as the meeting bot infrastructure layer (joins Google Meet, captures per-participant audio, provides Output Media API for streaming a webpage as the bot's camera and audio), (2) a real-time audio pipeline server (webpage rendered by Recall.ai) that coordinates Deepgram for streaming STT, the existing LiteLLM/Claude pipeline for reasoning, and ElevenLabs for streaming TTS, and (3) HeyGen LiveAvatar via LiveKit for rendering the animated avatar that appears as the bot's camera. The briefing and minutes subsystems are relatively straightforward -- scheduled LLM jobs using existing patterns from Phase 4/5.

The genuinely novel engineering challenges are: (a) the Output Media webpage architecture where a frontend webapp rendered by Recall.ai orchestrates the entire real-time pipeline, (b) achieving the <1s latency target which requires streaming at every stage and aggressive optimization, and (c) integrating HeyGen LiveAvatar so the avatar appears as the Recall.ai bot's camera feed with lip-sync driven by TTS audio. The briefing/minutes subsystems reuse existing patterns (Google Calendar API already partially in stack, LLM structured extraction via instructor).

**Primary recommendation:** Build three subsystems: (1) a MeetingScheduler service that monitors Google Calendar for agent invites and triggers briefing generation 2 hours before meetings, (2) a Recall.ai bot manager that creates/monitors meeting bots with Output Media configured to render a real-time audio pipeline webpage embedding a HeyGen LiveAvatar, and (3) a post-meeting MinutesGenerator that processes the full transcript into structured minutes. The real-time pipeline webpage is the critical path -- it must coordinate STT, LLM, TTS, and avatar with sub-1s total latency.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| recall-ai (API) | v1 REST API | Meeting bot infrastructure -- joins Google Meet, captures audio, Output Media for avatar/voice | Only production-grade universal meeting bot API; supports Google Meet, provides per-participant audio, Output Media for rendering webpages as bot camera/audio |
| deepgram-sdk | >=3.7.0 (Python) | Streaming speech-to-text with sub-300ms latency | Nova-3 model: ~250ms streaming latency, endpointing support, speaker diarization, 16kHz PCM input matches Recall.ai audio format |
| elevenlabs | >=1.15.0 (Python) | Streaming text-to-speech with sub-100ms TTFB | Flash v2.5 model: ~75ms TTFB, streaming output, 32 languages, 50% lower cost than multilingual v2 |
| heygen (API) | Streaming API v2 | Animated avatar with lip-sync, head nods, eye contact | LiveKit-based streaming, WebRTC delivery, custom avatar support, task-based text-to-speech with lip-sync |
| livekit-client | >=2.0.0 (JS) | WebRTC room management for HeyGen avatar stream | Required for HeyGen Streaming API v2 integration; manages video/audio tracks from avatar session |
| google-api-python-client | >=2.0.0 (already installed) | Google Calendar API for meeting detection | Already in stack from Phase 4; extends with Calendar API scopes |
| google-auth | >=2.0.0 (already installed) | OAuth/service account for Calendar access | Already in stack; adds Calendar scopes to domain-wide delegation |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| litellm | >=1.60.0 (already installed) | LLM abstraction for meeting reasoning + minutes generation | Real-time meeting responses and post-meeting minutes extraction |
| instructor | >=1.7.0 (already installed) | Structured LLM extraction for minutes (action items, decisions) | Post-meeting minutes generation with structured output |
| httpx | >=0.27.0 (already installed) | Async HTTP for Recall.ai and HeyGen REST API calls | Bot creation, session management, task submission |
| tenacity | >=9.0.0 (already installed) | Retry logic for external API calls | Recall.ai, HeyGen, Deepgram API resilience |
| structlog | >=24.0.0 (already installed) | Structured logging with latency tracking | Pipeline stage timing, error reporting |
| pydantic | >=2.0.0 (already installed) | Schemas for meeting state, transcript, minutes | All data models |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Deepgram Nova-3 (STT) | AssemblyAI Universal-Streaming | AssemblyAI has ~300ms immutable transcripts and intelligent endpointing optimized for voice agents; Deepgram has broader Python SDK support and is HeyGen's default STT provider. Deepgram recommended for tighter ecosystem fit. |
| ElevenLabs Flash v2.5 (TTS) | Cartesia Sonic | Cartesia claims faster TTFB (~34% better median latency); ElevenLabs has richer voice customization and proven HeyGen integration. ElevenLabs recommended for avatar voice quality. |
| Recall.ai Output Media (bot) | Building custom Google Meet bot | Recall.ai handles all platform complexity (joining, permissions, audio capture, video rendering). Custom build would take weeks and have ongoing maintenance. |
| HeyGen LiveAvatar (avatar) | D-ID, Synthesia | HeyGen has dedicated LiveKit streaming API for real-time use, built-in lip-sync from text/audio, and Recall.ai already documents this integration pattern. |
| Chained STT->LLM->TTS pipeline | OpenAI Realtime API (speech-to-speech) | Speech-to-speech achieves 200-300ms but costs ~10x more, loses component flexibility, and doesn't support custom avatars. Chained pipeline recommended for cost control and HeyGen integration. |

**Installation:**
```bash
# Python packages (backend meeting services)
pip install deepgram-sdk elevenlabs

# Note: recall-ai and heygen are REST API services, not pip packages
# livekit-client is a JS package for the Output Media webpage
# npm install livekit-client  (inside the Output Media webapp)
```

## Architecture Patterns

### Recommended Project Structure
```
src/
  app/
    meetings/                           # NEW: Meeting capabilities module
      __init__.py
      schemas.py                        # Meeting, Briefing, Minutes, Participant schemas
      models.py                         # SQLAlchemy models: Meeting, Transcript, Minutes, Briefing
      repository.py                     # MeetingRepository: CRUD for all meeting entities
      calendar/
        __init__.py
        monitor.py                      # CalendarMonitor: watches for agent invites, triggers briefings
        briefing.py                     # BriefingGenerator: pre-meeting briefing in multiple formats
      bot/
        __init__.py
        manager.py                      # BotManager: creates/monitors Recall.ai bots, handles lifecycle
        recall_client.py                # RecallClient: async wrapper for Recall.ai REST API
      realtime/
        __init__.py
        pipeline.py                     # AudioPipeline: orchestrates STT -> LLM -> TTS -> Avatar flow
        stt.py                          # DeepgramSTT: streaming speech-to-text with endpointing
        tts.py                          # ElevenLabsTTS: streaming text-to-speech with Flash v2.5
        avatar.py                       # HeyGenAvatar: avatar session management via LiveKit
        turn_detector.py                # TurnDetector: distinguishes thinking pauses from end-of-turn
        silence_checker.py              # SilenceChecker: implements strategic silence rules
      minutes/
        __init__.py
        generator.py                    # MinutesGenerator: transcript -> structured minutes
        distributor.py                  # MinutesDistributor: internal notification, manual share
    services/gsuite/
      calendar.py                       # NEW: Google Calendar service (extends auth.py pattern)
    api/v1/
      meetings.py                       # NEW: Meeting API endpoints (briefings, minutes, bot status)
    models/
      meetings.py                       # NEW: SQLAlchemy model definitions

# Output Media Webapp (rendered by Recall.ai as bot's camera)
meeting-bot-webapp/                     # NEW: Separate frontend project
  package.json
  src/
    index.html                          # Entry point rendered by Recall.ai
    app.js                              # Main orchestrator: audio capture -> pipeline -> avatar
    pipeline/
      deepgram-stt.js                   # WebSocket STT client
      llm-bridge.js                     # WebSocket to backend for LLM reasoning
      elevenlabs-tts.js                 # Streaming TTS client
    avatar/
      heygen-session.js                 # HeyGen LiveKit session management
      avatar-renderer.js               # Avatar video rendering in DOM
    utils/
      audio-processor.js                # AudioWorklet for processing meeting audio
      turn-detection.js                 # Client-side pause/turn detection
```

### Pattern 1: Recall.ai Output Media Architecture
**What:** Recall.ai joins the meeting as a bot participant. The bot renders a developer-controlled webpage as its camera feed and streams the webpage's audio as its microphone output. The webpage receives the meeting's mixed audio via `navigator.mediaDevices.getUserMedia({ audio: true })`. This creates a bidirectional audio/video channel between the meeting and the developer's webapp.
**When to use:** This is THE integration pattern for making the bot an active participant with avatar and voice.
**Example:**
```python
# Source: Recall.ai docs - https://docs.recall.ai/docs/stream-media
# Backend: Create bot with Output Media (Python)
import httpx

async def create_meeting_bot(
    meeting_url: str,
    bot_name: str,
    webapp_url: str,  # URL of your Output Media webpage
    recall_api_key: str,
    recall_region: str = "us-west-2",
) -> dict:
    """Create a Recall.ai bot with Output Media for avatar + voice."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://{recall_region}.recall.ai/api/v1/bot/",
            headers={"Authorization": f"Token {recall_api_key}"},
            json={
                "meeting_url": meeting_url,
                "bot_name": bot_name,
                "output_media": {
                    "camera": {
                        "kind": "webpage",
                        "config": {
                            "url": webapp_url,  # Your webapp renders HeyGen avatar here
                        },
                    },
                },
                # Enable automatic audio output (required for output_audio endpoint)
                "automatic_audio_output": {
                    "in_call_recording": {
                        "data": {
                            "kind": "mp3",
                            "b64_data": "SUQzBAA...",  # Silent MP3 placeholder
                        },
                    },
                },
                # Enable real-time transcription
                "transcription": {
                    "provider": "deepgram",
                    "language": "en",
                },
                # Configure real-time events via webhook
                "real_time_endpoints": [
                    {
                        "type": "webhook",
                        "url": "https://your-backend.com/api/v1/meetings/webhook",
                        "events": [
                            "transcript.data",
                            "transcript.partial_data",
                        ],
                    },
                ],
                # Auto-leave when all external participants leave
                "automatic_leave": {
                    "everyone_left_timeout": {
                        "timeout": 30,  # 30 seconds after last participant
                        "exclude_bot": True,
                    },
                },
            },
        )
        response.raise_for_status()
        return response.json()
```

```javascript
// Source: Recall.ai docs - https://docs.recall.ai/docs/stream-media
// Output Media Webapp: Captures meeting audio, renders avatar
// This webpage is rendered BY Recall.ai as the bot's camera feed

// 1. Capture meeting audio from bot's virtual microphone
const mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
const meetingAudioTrack = mediaStream.getAudioTracks()[0];

// 2. Process audio chunks for STT
const trackProcessor = new MediaStreamTrackProcessor({ track: meetingAudioTrack });
const trackReader = trackProcessor.readable.getReader();

while (true) {
  const { value: audioData, done } = await trackReader.read();
  if (done) break;
  // Send audio chunks to Deepgram STT WebSocket
  deepgramSocket.send(audioData);
}

// 3. Also connect to real-time transcript WebSocket
const transcriptWs = new WebSocket('wss://meeting-data.bot.recall.ai/api/v1/transcript');
transcriptWs.onmessage = (event) => {
  const transcript = JSON.parse(event.data);
  // Use Recall.ai's built-in transcription as backup/comparison
};
```

### Pattern 2: Streaming Audio Pipeline (STT -> LLM -> TTS)
**What:** A chained streaming pipeline where each stage begins processing before the previous stage completes. STT streams interim results; LLM begins generating response tokens from partial transcript; TTS begins synthesizing from initial LLM tokens. This parallelism is critical for sub-1s latency.
**When to use:** Every real-time meeting response.
**Example:**
```python
# Source: Voice AI architecture best practices
# (Cresta blog, AssemblyAI blog, Softcery research)
import asyncio
from dataclasses import dataclass
from datetime import datetime

@dataclass
class PipelineMetrics:
    """Track latency at each pipeline stage."""
    speech_end_time: float = 0.0
    stt_final_time: float = 0.0
    llm_first_token_time: float = 0.0
    tts_first_byte_time: float = 0.0
    audio_play_time: float = 0.0

    @property
    def total_latency_ms(self) -> float:
        return (self.audio_play_time - self.speech_end_time) * 1000

    @property
    def stt_latency_ms(self) -> float:
        return (self.stt_final_time - self.speech_end_time) * 1000

    @property
    def llm_latency_ms(self) -> float:
        return (self.llm_first_token_time - self.stt_final_time) * 1000

    @property
    def tts_latency_ms(self) -> float:
        return (self.tts_first_byte_time - self.llm_first_token_time) * 1000


class RealtimePipeline:
    """Orchestrates streaming STT -> LLM -> TTS pipeline.

    Latency budget (target <1000ms total):
    - STT finalization: ~250ms (Deepgram Nova-3 streaming)
    - LLM first token: ~300-500ms (Claude Haiku/fast model)
    - TTS first byte: ~75ms (ElevenLabs Flash v2.5)
    - Network/processing: ~100ms overhead
    - Total target: ~725-925ms
    """

    LATENCY_BUDGET_MS = 1000
    STT_BUDGET_MS = 300
    LLM_BUDGET_MS = 500
    TTS_BUDGET_MS = 100

    def __init__(
        self,
        stt_client,        # DeepgramSTT
        llm_client,        # LiteLLM async
        tts_client,        # ElevenLabsTTS
        avatar_client,     # HeyGenAvatar
        silence_checker,   # SilenceChecker
    ):
        self._stt = stt_client
        self._llm = llm_client
        self._tts = tts_client
        self._avatar = avatar_client
        self._silence = silence_checker
        self._metrics = PipelineMetrics()

    async def process_speech_turn(
        self,
        final_transcript: str,
        speaker_id: str,
        meeting_context: dict,
    ) -> None:
        """Process a completed speech turn through the pipeline.

        Called when STT detects end-of-utterance (via endpointing).
        """
        self._metrics.speech_end_time = asyncio.get_event_loop().time()

        # 1. Check strategic silence rules before responding
        should_speak = await self._silence.should_respond(
            transcript=final_transcript,
            speaker_id=speaker_id,
            meeting_context=meeting_context,
        )
        if not should_speak:
            return

        # 2. Stream LLM response
        response_tokens = []
        async for token in self._llm.stream_response(
            transcript=final_transcript,
            context=meeting_context,
        ):
            if not response_tokens:
                self._metrics.llm_first_token_time = asyncio.get_event_loop().time()
            response_tokens.append(token)

            # 3. Stream tokens to TTS as they arrive
            # Buffer to sentence boundaries for better TTS quality
            accumulated = "".join(response_tokens)
            if self._is_sentence_boundary(accumulated):
                await self._tts.synthesize_chunk(accumulated)
                response_tokens.clear()

        # Flush remaining tokens
        if response_tokens:
            await self._tts.synthesize_chunk("".join(response_tokens))

    def _is_sentence_boundary(self, text: str) -> bool:
        """Check if text ends at a natural sentence boundary."""
        return text.rstrip().endswith((".", "!", "?", ":", ";"))
```

### Pattern 3: HeyGen LiveAvatar via LiveKit in Output Media Webpage
**What:** The Output Media webpage creates a HeyGen streaming session, connects to the LiveKit room, and renders the avatar video stream as the visible content of the webpage. Since Recall.ai renders the webpage as the bot's camera, the avatar becomes the bot's visible representation in the meeting. TTS audio is sent to HeyGen via the `streaming.task` API with `task_type: "repeat"` to get lip-synced delivery.
**When to use:** Avatar rendering for every meeting.
**Example:**
```javascript
// Source: HeyGen Streaming API docs + Recall.ai Output Media docs
// This runs INSIDE the Output Media webpage rendered by Recall.ai

import { Room, RoomEvent } from 'livekit-client';

class AvatarManager {
  constructor(heygenApiKey, avatarId, voiceId) {
    this.apiKey = heygenApiKey;
    this.avatarId = avatarId;
    this.voiceId = voiceId;
    this.sessionId = null;
    this.room = null;
  }

  async startSession() {
    // 1. Create HeyGen streaming session
    const response = await fetch('https://api.heygen.com/v1/streaming.new', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({
        version: 'v2',
        avatar_name: this.avatarId,   // Tenant-specific avatar ID
        voice: {
          voice_id: this.voiceId,     // Tenant-specific voice
          rate: 1.0,
        },
        quality: 'high',
        video_encoding: 'H264',
      }),
    });
    const session = await response.json();
    this.sessionId = session.data.session_id;

    // 2. Connect to LiveKit room
    this.room = new Room();
    await this.room.connect(session.data.url, session.data.access_token);

    // 3. Start the avatar stream
    await fetch('https://api.heygen.com/v1/streaming.start', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({ session_id: this.sessionId }),
    });

    // 4. Subscribe to avatar video/audio tracks
    this.room.on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === 'video') {
        // Attach avatar video to DOM element
        // Recall.ai renders this as the bot's camera
        const videoElement = document.getElementById('avatar-video');
        track.attach(videoElement);
      }
    });
  }

  async speak(text) {
    // Send text for avatar to speak with lip-sync
    // task_type "repeat" = exact text; "talk" = LLM-processed
    await fetch('https://api.heygen.com/v1/streaming.task', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({
        session_id: this.sessionId,
        text: text,
        task_type: 'repeat',  // Repeat exactly (we handle LLM ourselves)
      }),
    });
  }

  async stopSession() {
    await fetch('https://api.heygen.com/v1/streaming.stop', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({ session_id: this.sessionId }),
    });
    this.room?.disconnect();
  }
}
```

### Pattern 4: Strategic Silence Checker
**What:** Before the agent speaks, check three conditions: (1) customer is not still thinking/pausing, (2) internal rep is not currently speaking, (3) response confidence exceeds threshold. This prevents low-quality or inappropriate contributions.
**When to use:** Every potential response before TTS begins.
**Example:**
```python
# Source: CONTEXT.md locked decisions on strategic silence
import asyncio
from enum import Enum

class ParticipantRole(str, Enum):
    INTERNAL = "internal"
    EXTERNAL = "external"
    AGENT = "agent"

class SilenceChecker:
    """Implements strategic silence rules from CONTEXT.md.

    All three conditions must be satisfied before agent speaks:
    1. Customer not thinking/pausing (end-of-turn detected)
    2. Internal rep not speaking (clear hierarchy)
    3. Confidence above threshold (quality gate)
    """

    THINKING_PAUSE_MS = 2000   # 2s = likely still thinking
    END_OF_TURN_MS = 1000      # 1s = likely end of turn
    CONFIDENCE_THRESHOLD = 0.7  # Minimum confidence to speak

    def __init__(self, participant_tracker):
        self._tracker = participant_tracker

    async def should_respond(
        self,
        transcript: str,
        speaker_id: str,
        meeting_context: dict,
    ) -> bool:
        """Check all strategic silence conditions."""

        # 1. Is this an end-of-turn or a thinking pause?
        silence_duration_ms = self._tracker.get_silence_duration_ms(speaker_id)
        if silence_duration_ms < self.END_OF_TURN_MS:
            return False  # Too soon -- speaker may continue

        # 2. Is an internal rep currently speaking?
        active_speakers = self._tracker.get_active_speakers()
        for speaker in active_speakers:
            if speaker.role == ParticipantRole.INTERNAL:
                return False  # Never talk over the human salesperson

        # 3. Is the response confidence high enough?
        # (assessed by LLM in the response generation step)
        # This check is done during LLM generation, not here
        # Kept as architecture documentation

        return True
```

### Pattern 5: Google Calendar Monitor for Meeting Detection
**What:** Periodically polls Google Calendar for events where the agent is explicitly invited. Uses push notifications (webhooks) for real-time change detection with polling as fallback. Triggers briefing generation 2 hours before meeting start.
**When to use:** Continuous background service for meeting detection.
**Example:**
```python
# Source: Google Calendar API push notifications guide
# Extends existing GSuiteAuthManager pattern from Phase 4

CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events.readonly",
]

class CalendarMonitor:
    """Monitors Google Calendar for agent meeting invites.

    Uses webhook push notifications with polling fallback.
    Triggers briefing generation 2 hours before meetings.
    """

    BRIEFING_LEAD_TIME_HOURS = 2
    EARLY_JOIN_MINUTES = 3   # Join 2-3 minutes early
    POLL_INTERVAL_SECONDS = 60  # Fallback polling

    def __init__(self, calendar_service, briefing_generator, bot_manager):
        self._calendar = calendar_service
        self._briefing = briefing_generator
        self._bot_manager = bot_manager

    async def check_upcoming_meetings(self, agent_email: str) -> list:
        """Poll for meetings where agent is an attendee."""
        now = datetime.now(timezone.utc)
        window = now + timedelta(hours=self.BRIEFING_LEAD_TIME_HOURS + 1)

        events = self._calendar.events().list(
            calendarId=agent_email,
            timeMin=now.isoformat(),
            timeMax=window.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        ).execute()

        return [
            event for event in events.get("items", [])
            if self._is_agent_explicitly_invited(event, agent_email)
            and self._has_google_meet_link(event)
        ]

    def _is_agent_explicitly_invited(self, event: dict, agent_email: str) -> bool:
        """Check if agent email is in attendee list (explicit invite only)."""
        attendees = event.get("attendees", [])
        return any(
            a.get("email", "").lower() == agent_email.lower()
            for a in attendees
        )

    def _has_google_meet_link(self, event: dict) -> bool:
        """Check if event has a Google Meet link."""
        conference = event.get("conferenceData", {})
        entry_points = conference.get("entryPoints", [])
        return any(ep.get("entryPointType") == "video" for ep in entry_points)

    async def setup_push_notifications(
        self,
        agent_email: str,
        webhook_url: str,
    ) -> dict:
        """Set up Google Calendar push notifications (webhook).

        Note: Requires verified HTTPS domain. Falls back to polling
        if webhook setup fails.
        """
        import uuid
        channel_id = str(uuid.uuid4())

        body = {
            "id": channel_id,
            "type": "web_hook",
            "address": webhook_url,
            "token": f"agent={agent_email}",
        }

        return self._calendar.events().watch(
            calendarId=agent_email,
            body=body,
        ).execute()
```

### Pattern 6: Meeting Minutes Generation (Map-Reduce for Long Transcripts)
**What:** Process meeting transcript into structured minutes with four sections: verbatim transcript, executive summary, action items with owners, and decisions/commitments. For long meetings, use map-reduce: chunk transcript into 15-minute segments, summarize each, then synthesize a final summary.
**When to use:** Immediately after meeting ends, triggered by bot exit event.
**Example:**
```python
# Source: AssemblyAI blog + existing instructor pattern from Phase 4
import instructor
import litellm
from pydantic import BaseModel, Field

class ActionItem(BaseModel):
    """Extracted action item from meeting transcript."""
    owner: str = Field(description="Person responsible for this action")
    action: str = Field(description="What needs to be done")
    due_date: str | None = Field(None, description="When it's due, if mentioned")
    context: str = Field(description="Brief context from the meeting")

class Decision(BaseModel):
    """Decision or commitment made during the meeting."""
    decision: str = Field(description="What was decided")
    participants: list[str] = Field(description="Who agreed to this")
    context: str = Field(description="Discussion context leading to decision")

class MeetingMinutes(BaseModel):
    """Structured meeting minutes extracted from transcript."""
    executive_summary: str = Field(description="2-3 paragraph high-level summary")
    key_topics: list[str] = Field(description="Main topics discussed")
    action_items: list[ActionItem] = Field(description="All action items with owners")
    decisions: list[Decision] = Field(description="Decisions and commitments made")
    follow_up_date: str | None = Field(None, description="Next meeting date if mentioned")

class MinutesGenerator:
    """Generates structured meeting minutes from transcript.

    Uses map-reduce for transcripts exceeding token limits:
    1. Chunk transcript into ~15-minute segments
    2. Summarize each segment individually
    3. Synthesize final minutes from segment summaries
    """

    MAX_TOKENS_PER_CHUNK = 12000  # ~15 minutes of conversation
    MODEL_REASONING = "anthropic/claude-sonnet-4-20250514"  # Quality model for minutes

    async def generate(
        self,
        transcript: str,
        attendees: list[dict],
        meeting_metadata: dict,
    ) -> MeetingMinutes:
        """Generate structured minutes from full transcript."""
        client = instructor.from_litellm(litellm.acompletion)

        # For short meetings, single-pass extraction
        if self._token_count(transcript) < self.MAX_TOKENS_PER_CHUNK:
            return await self._extract_minutes(client, transcript, attendees, meeting_metadata)

        # For long meetings, map-reduce
        chunks = self._chunk_transcript(transcript)
        summaries = []
        for chunk in chunks:
            summary = await self._summarize_chunk(client, chunk)
            summaries.append(summary)

        combined = "\n\n---\n\n".join(summaries)
        return await self._extract_minutes(client, combined, attendees, meeting_metadata)

    async def _extract_minutes(self, client, text, attendees, metadata) -> MeetingMinutes:
        """Single-pass structured extraction."""
        return await client.chat.completions.create(
            model=self.MODEL_REASONING,
            response_model=MeetingMinutes,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are analyzing a sales meeting transcript to generate "
                        "structured meeting minutes. Extract:\n"
                        "1. Executive summary (2-3 paragraphs)\n"
                        "2. Key topics discussed\n"
                        "3. Action items with specific owners and due dates\n"
                        "4. Decisions and commitments made\n\n"
                        "Note absence of items rather than making assumptions.\n"
                        "Be precise about who said what and who committed to what."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Meeting: {metadata.get('title', 'Sales Meeting')}\n"
                        f"Date: {metadata.get('date', 'Unknown')}\n"
                        f"Attendees: {', '.join(a['name'] for a in attendees)}\n\n"
                        f"Transcript:\n{text}"
                    ),
                },
            ],
            max_tokens=4096,
            temperature=0.1,
        )
```

### Anti-Patterns to Avoid
- **Sequential (non-streaming) pipeline:** Do NOT wait for full STT transcript before starting LLM, or full LLM response before starting TTS. Each stage must stream into the next. Sequential processing adds 2-3 seconds of latency.
- **Using reasoning/large models for real-time responses:** Do NOT use Claude Sonnet or GPT-4 for real-time meeting responses. Use the fastest available model (Claude Haiku, GPT-4o-mini, or similar) with aggressive token limits. Reserve quality models for minutes generation only.
- **Running the real-time pipeline on the backend server:** Do NOT try to route meeting audio through your Python backend for STT. Use the Output Media webpage architecture -- the webpage runs inside Recall.ai's infrastructure with direct access to meeting audio. Backend handles LLM reasoning via WebSocket.
- **Sending full conversation history to LLM on every turn:** Do NOT include the entire meeting transcript in each LLM call. Use a sliding window of recent context (last 5-10 exchanges) plus the pre-meeting briefing. Full context is for post-meeting minutes only.
- **Blocking on HeyGen avatar response before allowing next pipeline input:** Do NOT wait for avatar lip-sync to complete before processing the next speech turn. The avatar rendering is fire-and-forget; pipeline must continue processing incoming audio.
- **Automatic external minutes distribution:** Do NOT automatically send minutes to external participants. Minutes are internal-only by default. Provide a manual share endpoint for reps to control what goes external.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Meeting bot joining Google Meet | Custom Puppeteer/Selenium bot | Recall.ai Bot API | Handles authentication, permissions, platform quirks, audio/video streams, scaling. Building custom would take weeks. |
| Real-time transcription | Custom Whisper pipeline | Deepgram Nova-3 streaming | Sub-300ms latency, speaker diarization, endpointing, production reliability. Self-hosted Whisper has 2-10x higher latency. |
| Avatar lip-sync | Custom face animation from audio | HeyGen LiveAvatar API | Real-time lip-sync, natural facial expressions, head movement, WebRTC delivery. Custom would require ML expertise and months of work. |
| Voice synthesis | Self-hosted TTS model | ElevenLabs Flash v2.5 | ~75ms TTFB, natural voice quality, streaming output, voice customization. Self-hosted models have higher latency and lower quality. |
| End-of-turn detection | Simple silence timer | Deepgram endpointing + VAD events | Deepgram's ML-based endpointing distinguishes pauses from turn-ends. Simple timers cause false positives and interruptions. |
| Calendar event monitoring | Custom polling loop | Google Calendar push notifications + polling fallback | Webhooks provide near-real-time notification; polling fallback ensures reliability. |
| Structured minutes extraction | Custom regex/NLP parsing | instructor + litellm (existing pattern) | Already proven in Phase 4 for structured extraction. Pydantic validation ensures output schema compliance. |
| Meeting recording storage | Custom audio/video capture | Recall.ai recording + transcript artifacts | Recall.ai automatically captures and stores recordings with speaker attribution. |

**Key insight:** Phase 6 is an integration phase, not a build-from-scratch phase. Every major component (meeting bot, STT, TTS, avatar, calendar) has a specialized SaaS API. The engineering challenge is orchestrating these APIs into a cohesive, low-latency pipeline -- not building any individual component.

## Common Pitfalls

### Pitfall 1: Latency Budget Overrun in Chained Pipeline
**What goes wrong:** Individual components each take "acceptable" latency (STT: 300ms, LLM: 800ms, TTS: 200ms) but total exceeds 1s target significantly (1300ms+ before network overhead).
**Why it happens:** Each component measured in isolation; network hops, serialization, and buffering between stages add 100-200ms each.
**How to avoid:** (a) Use streaming at every stage -- STT streams interim results, LLM streams tokens, TTS streams audio chunks. (b) Use the fastest model tier: Deepgram Nova-3 for STT, Claude Haiku or equivalent "fast" model for LLM, ElevenLabs Flash v2.5 for TTS. (c) Measure end-to-end latency as primary metric (from last syllable spoken to first audio byte played), not individual component latency. (d) Set hard timeouts: if LLM hasn't produced first token in 500ms, abort and use a canned response.
**Warning signs:** Total latency consistently >1s in testing, LLM responses taking >500ms first-token, TTS buffering adding delay.

### Pitfall 2: Output Media Webpage Complexity
**What goes wrong:** The Output Media webpage that Recall.ai renders as the bot's camera becomes an overly complex SPA with framework overhead, adding rendering latency and initialization time.
**Why it happens:** Developers treat it like a normal web app, adding React/Vue, build tools, and heavy dependencies. But this page renders inside Recall.ai's headless browser and must be fast and lightweight.
**How to avoid:** Keep the webpage minimal -- vanilla JavaScript, no framework, no heavy bundler. The page has one job: render the HeyGen avatar video and coordinate audio. Avoid unnecessary DOM complexity. Use a simple WebSocket for backend communication.
**Warning signs:** Bot camera showing blank for several seconds after joining, avatar rendering delays, JavaScript errors in Recall.ai's webpage console.

### Pitfall 3: Turn-Taking Failures (Interrupting or Being Too Slow)
**What goes wrong:** Agent speaks while customer is still thinking (premature response), or agent waits too long after customer finishes and the conversation feels sluggish.
**Why it happens:** Distinguishing between a "thinking pause" (2-3 seconds of silence while customer formulates thought) and an "end-of-turn" (1 second of silence indicating they're done) is genuinely difficult. Simple silence timers get this wrong frequently.
**How to avoid:** Use Deepgram's ML-based endpointing with configurable threshold (300ms for fast-paced, 1000ms for deliberate conversations). Combine with VAD (Voice Activity Detection) events. Add a secondary check: if the last utterance was a question directed at someone else, suppress response regardless of silence duration. Never interrupt -- if in doubt, stay silent.
**Warning signs:** Meeting participants saying "sorry, go ahead" or "wait, I wasn't done," awkward silences followed by simultaneous speech.

### Pitfall 4: HeyGen Session Limits and Cost
**What goes wrong:** HeyGen streaming sessions have time limits (typically 10-60 minutes depending on plan) and per-minute costs. A long sales meeting exceeds the session limit and the avatar freezes.
**Why it happens:** Not accounting for HeyGen's session duration limits in architecture design.
**How to avoid:** Check `session_duration_limit` from the session creation response. Implement session rotation: before limit is reached, create a new session and seamlessly swap. Budget HeyGen costs per meeting (likely $1-5 per hour of avatar time depending on plan). Set meeting duration limits as a safeguard.
**Warning signs:** Avatar freezing mid-meeting, unexpected HeyGen API bills, session timeout errors in logs.

### Pitfall 5: Google Meet Bot Authentication and Permissions
**What goes wrong:** Recall.ai bot can't join the Google Meet because it lacks proper authentication, gets stuck in waiting room, or is rejected by meeting settings.
**Why it happens:** Google Meet has various security settings: "Only people in your organization," "People who are invited," and meeting hosts can restrict anonymous participants. The bot needs proper authentication.
**How to avoid:** Use Recall.ai's Google Login integration (`google_meet.google_login_group_id` parameter) to authenticate the bot with a Google Workspace account. Ensure the bot's Google account is in the same organization or is explicitly invited to the meeting. Test with various meeting security settings.
**Warning signs:** Bot stuck in "waiting_room" status, "call_ended" status immediately after creation, permission denied errors.

### Pitfall 6: Transcript Quality Degradation with Multiple Speakers
**What goes wrong:** In meetings with 3+ speakers, the mixed audio stream produces noisy transcription with speaker attribution errors.
**Why it happens:** Mixed audio from multiple simultaneous or overlapping speakers degrades STT accuracy. Speaker diarization on mixed audio is imperfect.
**How to avoid:** Use Recall.ai's per-participant separate audio streams where supported (Google Meet supports up to 16 concurrent streams). Enable Deepgram's diarization. Track participant roles (internal vs external) via Recall.ai's participant metadata for speaker identification in the transcript.
**Warning signs:** Transcript showing "Speaker 0" instead of names, misattributed quotes, garbled text during crosstalk periods.

### Pitfall 7: Minutes Distribution Leaking Internal Discussion
**What goes wrong:** Agent automatically shares full meeting minutes with external participants, including internal-only discussion, candid assessments, or competitive positioning notes.
**Why it happens:** Lack of internal/external filtering in the distribution pipeline.
**How to avoid:** Minutes are internal-only by default (CONTEXT.md locked decision). Store minutes in internal database. Provide a manual share API where the rep explicitly selects what to share externally. Consider generating two versions: full internal minutes and a sanitized customer-appropriate summary that the rep can review before sharing.
**Warning signs:** Customer receiving internal strategy notes, competitive information leaking, legal/compliance concerns about shared content.

### Pitfall 8: Briefing Generation Timing Edge Cases
**What goes wrong:** Briefing generates for a meeting that gets rescheduled, or doesn't generate because the meeting was added less than 2 hours before start time.
**Why it happens:** Calendar events change frequently -- rescheduling, cancellation, last-minute additions.
**How to avoid:** (a) Idempotent briefing generation keyed by (meeting_id, scheduled_time) -- if meeting is rescheduled, the key changes and a new briefing generates. (b) For meetings added less than 2 hours before start, generate immediately (degraded lead time is better than no briefing). (c) Cancel briefings for cancelled meetings. (d) Re-generate if attendee list changes significantly.
**Warning signs:** Stale briefings with outdated attendee information, missing briefings for last-minute meetings.

## Code Examples

Verified patterns from official sources:

### Deepgram Streaming STT with Endpointing (Python)
```python
# Source: Deepgram Python SDK docs + developers.deepgram.com
from deepgram import DeepgramClient, LiveOptions, LiveTranscriptionEvents
import asyncio

class DeepgramSTT:
    """Streaming STT with endpointing for turn detection."""

    def __init__(self, api_key: str):
        self._client = DeepgramClient(api_key)
        self._connection = None
        self._on_transcript = None
        self._on_utterance_end = None

    async def connect(
        self,
        on_transcript: callable,
        on_utterance_end: callable,
    ):
        """Establish streaming WebSocket connection."""
        self._on_transcript = on_transcript
        self._on_utterance_end = on_utterance_end

        self._connection = self._client.listen.websocket.v("1")

        self._connection.on(LiveTranscriptionEvents.Transcript, self._handle_transcript)
        self._connection.on(LiveTranscriptionEvents.UtteranceEnd, self._handle_utterance_end)

        options = LiveOptions(
            model="nova-3",
            language="en-US",
            smart_format=True,
            interim_results=True,
            endpointing=300,           # 300ms pause = end of utterance
            utterance_end_ms="1000",   # 1s silence = utterance end event
            vad_events=True,
            diarize=True,
            encoding="linear16",
            channels=1,
            sample_rate=16000,         # Matches Recall.ai audio format
        )

        self._connection.start(options)

    def send_audio(self, audio_bytes: bytes):
        """Send raw audio bytes to Deepgram."""
        if self._connection:
            self._connection.send(audio_bytes)

    def _handle_transcript(self, result, **kwargs):
        """Handle interim and final transcript results."""
        transcript = result.channel.alternatives[0].transcript
        is_final = result.is_final
        if transcript and self._on_transcript:
            self._on_transcript(transcript, is_final)

    def _handle_utterance_end(self, result, **kwargs):
        """Handle utterance end (speaker stopped talking)."""
        if self._on_utterance_end:
            self._on_utterance_end()

    async def close(self):
        if self._connection:
            self._connection.finish()
```

### ElevenLabs Streaming TTS (Python)
```python
# Source: ElevenLabs Python SDK docs
from elevenlabs.client import AsyncElevenLabs
import asyncio

class ElevenLabsTTS:
    """Streaming TTS with Flash v2.5 for minimum latency."""

    MODEL_ID = "eleven_flash_v2_5"  # ~75ms TTFB

    def __init__(self, api_key: str, voice_id: str):
        self._client = AsyncElevenLabs(api_key=api_key)
        self._voice_id = voice_id

    async def synthesize_stream(self, text: str):
        """Stream audio bytes from text.

        Yields audio chunks as they're generated.
        Use output_format pcm_16000 for direct Recall.ai compatibility.
        """
        audio_stream = await self._client.text_to_speech.convert(
            voice_id=self._voice_id,
            text=text,
            model_id=self.MODEL_ID,
            output_format="mp3_22050_32",  # MP3 for Recall.ai output_audio
            optimize_streaming_latency=4,  # Max latency optimization
        )
        return audio_stream
```

### Recall.ai Bot Lifecycle Management (Python)
```python
# Source: Recall.ai docs
import httpx
import structlog

logger = structlog.get_logger(__name__)

class RecallClient:
    """Async client for Recall.ai REST API."""

    def __init__(self, api_key: str, region: str = "us-west-2"):
        self._api_key = api_key
        self._base_url = f"https://{region}.recall.ai/api/v1"
        self._headers = {"Authorization": f"Token {api_key}"}

    async def create_bot(self, config: dict) -> dict:
        """Create a new meeting bot."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/bot/",
                headers=self._headers,
                json=config,
                timeout=30,
            )
            response.raise_for_status()
            return response.json()

    async def get_bot_status(self, bot_id: str) -> dict:
        """Get current bot status."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/bot/{bot_id}/",
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()

    async def send_audio(self, bot_id: str, mp3_b64: str) -> None:
        """Send audio to bot for playback in meeting."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self._base_url}/bot/{bot_id}/output_audio/",
                headers=self._headers,
                json={"kind": "mp3", "b64_data": mp3_b64},
            )
            response.raise_for_status()

    async def get_transcript(self, bot_id: str) -> list:
        """Get full transcript after meeting ends."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/bot/{bot_id}/transcript/",
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()

    async def get_recording(self, bot_id: str) -> dict:
        """Get recording URL after meeting ends."""
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{self._base_url}/bot/{bot_id}/recording/",
                headers=self._headers,
            )
            response.raise_for_status()
            return response.json()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Custom meeting bots via Puppeteer/Selenium | Recall.ai universal meeting bot API | 2023+ | Eliminates months of platform-specific bot engineering |
| Static avatar images in meetings | HeyGen LiveAvatar with real-time lip-sync via LiveKit | 2024+ | Natural-looking animated avatar indistinguishable from video feed |
| Whisper for real-time STT | Deepgram Nova-3 / AssemblyAI streaming with endpointing | 2024-2025 | Sub-300ms latency vs 2-10s for Whisper; ML-based turn detection |
| Pre-rendered TTS (full sentence) | ElevenLabs Flash v2.5 streaming (~75ms TTFB) | 2025 | Sentence-level TTS took 500ms+; streaming enables real-time delivery |
| Sequential STT->LLM->TTS pipeline | Streaming/parallel pipeline with concurrent processing | 2024-2025 | Drops total latency from 3-5s to <1s through parallelism |
| Simple silence timer for turn detection | ML-based endpointing + semantic turn detection | 2025 | Deepgram Flux: model-integrated end-of-turn detection (~260ms) |
| OpenAI Realtime API (speech-to-speech) | Chained pipeline with fast models | 2025-2026 | S2S costs ~10x more with less flexibility; chained pipeline more practical for meeting agents |
| Recall.ai audio-only bots | Output Media API (webpage as camera + audio) | 2024-2025 | Enables avatar + voice + interactive content in bot's meeting presence |

**Deprecated/outdated:**
- **Whisper for real-time transcription:** Too slow (2-10s latency). Use streaming APIs (Deepgram, AssemblyAI) instead.
- **Deepgram Nova-2:** Superseded by Nova-3 with better accuracy at same latency. Use `model="nova-3"`.
- **ElevenLabs Turbo v2.5:** Superseded by Flash v2.5 with lower latency (~75ms vs ~250ms). Use `model_id="eleven_flash_v2_5"`.
- **Recall.ai screen-share-only output:** Output Media now supports camera mode (`"kind": "webpage"` with camera config), making the bot a proper video participant.
- **Manual meeting bot audio via output_audio endpoint only:** Output Media webapp architecture is the recommended approach for real-time voice agents. The output_audio REST endpoint is for short predefined clips only.

## Open Questions

Things that couldn't be fully resolved:

1. **Recall.ai Per-Participant Audio on Google Meet**
   - What we know: Recall.ai documentation states Google Meet supports up to 16 concurrent separate audio streams. This enables per-speaker STT for accurate attribution.
   - What's unclear: Whether per-participant separate audio is available on all Google Meet plan tiers, or only Google Workspace Enterprise. The documentation mentions it may require a feature flag for some platforms.
   - Recommendation: Start with mixed audio + Deepgram diarization. Test per-participant audio during implementation. If available on Google Meet without feature flag, switch to separate streams for better accuracy.

2. **HeyGen Avatar Session Duration Limits**
   - What we know: The `session_duration_limit` is returned in the session creation response. The documentation mentions 600 seconds (10 minutes) in examples.
   - What's unclear: What the actual session limits are for different HeyGen plan tiers (API pricing is not publicly documented with clear limits). Whether seamless session rotation (creating new session while old is active) is possible without visible avatar restart.
   - Recommendation: Design for session rotation from the start. Implement a "warm standby" session that's pre-created and ready to swap in when the active session approaches its limit. Budget for worst-case session costs.

3. **Output Media Webpage Rendering Latency**
   - What we know: Recall.ai renders the webpage in a headless browser. The documentation claims "ultra-low-latency" rendering.
   - What's unclear: The actual rendering latency from DOM update to meeting video frame. Whether HeyGen LiveKit video stream adds compositing latency when rendered inside the Output Media webpage.
   - Recommendation: Build a minimal test to measure end-to-end rendering latency (text change -> avatar speaks -> audio heard in meeting). Profile in staging before committing to latency targets. Have a fallback plan if avatar rendering adds unacceptable latency (TTS-only mode without avatar video).

4. **LLM Response Quality at Fast Model Tier**
   - What we know: Sub-1s latency requires the fastest LLM tier (Haiku-class). The existing project uses Claude Sonnet as primary.
   - What's unclear: Whether a Haiku-class model can produce sales-conversation-quality responses with sufficient context about the deal, account, and methodology. The quality difference between fast and reasoning models is significant.
   - Recommendation: Use Claude Haiku for real-time responses (speed priority). Use a two-phase approach: (1) fast model generates immediate response, (2) quality model validates/enhances response in parallel. If the quality check fails confidence threshold, the agent stays silent rather than speaking poorly. This aligns with the "confidence below threshold" strategic silence rule.

5. **Recall.ai Pricing and Scaling**
   - What we know: Recall.ai is a paid API service (not open source). Pricing depends on usage (bots created, recording time, transcription, Output Media).
   - What's unclear: Per-meeting cost with full Output Media + transcription + recording. Whether there are volume discounts for enterprise usage.
   - Recommendation: Contact Recall.ai for enterprise pricing before production deployment. For development, use their free tier or trial. Design the system to be Recall.ai-agnostic at the bot management layer (RecallClient abstraction) in case an alternative is needed.

6. **Google Calendar Webhook Domain Verification**
   - What we know: Google Calendar push notifications require a verified HTTPS domain. Self-signed certificates are not accepted.
   - What's unclear: Whether the development environment can use ngrok or similar tunneling for webhook testing, or if a real domain is needed even for development.
   - Recommendation: Implement both push notification (webhook) and polling approaches. Default to polling (60-second interval) for development. Use push notifications in production where the domain is verified. The polling fallback ensures the system works regardless of webhook status.

## Sources

### Primary (HIGH confidence)
- [Recall.ai Output Media docs](https://docs.recall.ai/docs/stream-media) -- Bot creation with webpage camera, audio capture, real-time transcription
- [Recall.ai Output Audio docs](https://docs.recall.ai/docs/output-audio-in-meetings) -- MP3 audio output via REST API, automatic and manual modes
- [Recall.ai Separate Audio per Participant](https://docs.recall.ai/docs/how-to-get-separate-audio-per-participant-realtime) -- Per-participant audio streaming, platform support matrix (Google Meet: 16 streams)
- [Recall.ai Real-Time Transcription](https://docs.recall.ai/docs/bot-real-time-transcription) -- Transcription providers, diarization, partial results
- [Deepgram Python SDK](https://github.com/deepgram/deepgram-python-sdk) (Context7: /deepgram/deepgram-python-sdk) -- WebSocket streaming v1/v2, LiveTranscriptionEvents, LiveOptions
- [Deepgram Streaming API](https://developers.deepgram.com) (Context7: /websites/developers_deepgram) -- Nova-3 model, endpointing, interim_results, diarization, VAD events
- [ElevenLabs Python SDK](https://github.com/elevenlabs/elevenlabs-python) (Context7: /elevenlabs/elevenlabs-python) -- Streaming TTS, Flash v2.5 model, async client, optimize_streaming_latency
- [ElevenLabs Models docs](https://elevenlabs.io/docs/overview/models) -- Flash v2.5: model_id `eleven_flash_v2_5`, ~75ms TTFB, 32 languages
- [HeyGen Streaming API](https://docs.heygen.com/docs/streaming-api-integration-with-livekit-v2) (Context7: /websites/heygen) -- LiveKit v2 integration, session lifecycle, streaming.task API
- [HeyGen Streaming Avatar SDK Reference](https://docs.heygen.com/docs/streaming-avatar-sdk-reference) -- startAvatar config, voice settings, STT settings, quality levels
- [Google Calendar Push Notifications](https://developers.google.com/workspace/calendar/api/guides/push) -- Webhook setup, notification format, channel management

### Secondary (MEDIUM confidence)
- [Voice AI Stack 2026 (AssemblyAI blog)](https://www.assemblyai.com/blog/the-voice-ai-stack-for-building-agents) -- STT/LLM/TTS provider recommendations, latency targets, streaming architecture
- [Real-Time vs Turn-Based Architecture (Softcery)](https://softcery.com/lab/ai-voice-agents-real-time-vs-turn-based-tts-stt-architecture) -- Chained vs S2S comparison, cost analysis (S2S ~10x more), component recommendations
- [Engineering Voice Agent Latency (Cresta)](https://cresta.com/blog/engineering-for-real-time-voice-agent-latency) -- ASR 200-300ms, LLM 250ms-1s+, TTS 100-500ms, optimization strategies
- [Meeting Summarization with LLMs (AssemblyAI)](https://www.assemblyai.com/blog/summarize-meetings-llms-python) -- Prompt design, map-reduce for long transcripts, action item extraction
- [Recall.ai YC Launch](https://www.ycombinator.com/launches/M9k-recall-ai-output-media-api-ai-agents-that-talk-in-meetings) -- Output Media architecture confirmation, webpage-to-meeting rendering
- [HeyGen LiveAvatar overview](https://www.heygen.com/interactive-avatar) -- WebRTC streaming, custom LLM connection, real-time lip-sync

### Tertiary (LOW confidence)
- HeyGen session duration limits and pricing -- Not clearly documented in public API docs, varies by plan
- Recall.ai per-meeting pricing with full Output Media -- Enterprise pricing not publicly available
- Deepgram Nova-3 WER benchmark (18.3%) -- From Deepgram's own benchmark; independent verification needed
- Per-participant audio availability on Google Meet without feature flag -- Documentation mentions feature flag for some platforms but lists Google Meet as supported

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- All recommended services have extensive public documentation, verified Context7 entries, and production track records. Core libraries (Recall.ai, Deepgram, ElevenLabs, HeyGen) are well-documented with code examples.
- Architecture: MEDIUM-HIGH -- Output Media webpage + HeyGen LiveKit + streaming pipeline pattern is documented by both Recall.ai and HeyGen independently. However, the full combined integration (Recall.ai -> Output Media -> HeyGen avatar + Deepgram STT + ElevenLabs TTS + LLM) hasn't been verified as a working end-to-end implementation. Individual components are HIGH confidence, integration is MEDIUM.
- Latency targets: MEDIUM -- Individual component latencies are well-documented (~250ms STT, ~300-500ms LLM, ~75ms TTS), total budget appears feasible at 625-825ms. However, real-world integration adds overhead. The <1s target is aggressive but achievable with streaming. If it proves impossible, the LLM is the bottleneck to optimize (faster model, shorter prompts, speculative generation).
- Briefing/Minutes: HIGH -- Uses existing patterns (Google Calendar API already in stack, instructor/litellm for structured extraction). These are straightforward scheduled tasks, not real-time.
- Pitfalls: HIGH -- Rate limits, session limits, turn-taking challenges, and authentication issues are well-documented in vendor docs and community experience.

**Research date:** 2026-02-13
**Valid until:** 2026-03-15 (30 days -- API services evolve rapidly; HeyGen and Recall.ai release features frequently)
