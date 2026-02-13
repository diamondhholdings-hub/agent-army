"""MinutesGenerator -- structured meeting minutes extraction from transcripts.

Uses the instructor + litellm pattern (Phase 4: QualificationExtractor,
Phase 5: OpportunityDetector) for structured LLM extraction. Handles long
transcripts via map-reduce: chunk at speaker boundaries, summarize each
chunk, then synthesize final minutes.

Minutes include all 4 content types per CONTEXT.md locked decisions:
1. Verbatim transcript (full_text from Transcript schema)
2. Executive summary (2-3 paragraphs)
3. Action items with owners
4. Decisions and commitments

Uses model='reasoning' (quality model) since minutes generation is not
latency-sensitive (RESEARCH.md recommendation).

Exports:
    MinutesGenerator: Main minutes generation service.
    ExtractedActionItem: Pydantic model for instructor action item extraction.
    ExtractedDecision: Pydantic model for instructor decision extraction.
    ExtractedMinutes: Pydantic model for instructor full minutes extraction.
    ChunkSummary: Pydantic model for instructor chunk summarization.
"""

from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

import structlog
from pydantic import BaseModel, Field

from src.app.meetings.repository import MeetingRepository
from src.app.meetings.schemas import (
    MeetingMinutes,
    MeetingStatus,
    Participant,
    Transcript,
)

logger = structlog.get_logger(__name__)


# ── Constants ────────────────────────────────────────────────────────────────

MAX_TOKENS_PER_CHUNK = 12_000  # ~15 minutes of conversation
MODEL_REASONING = "anthropic/claude-sonnet-4-20250514"  # Quality model for minutes
CHARS_PER_TOKEN = 4.0  # Per 03-02 decision for token estimation


# ── Pydantic Response Models for Instructor ──────────────────────────────────


class ExtractedActionItem(BaseModel):
    """Action item extracted from meeting transcript by LLM."""

    owner: str = Field(description="Person responsible for this action")
    action: str = Field(description="What needs to be done")
    due_date: str | None = Field(None, description="When it's due, if mentioned")
    context: str = Field(description="Brief context from the meeting")


class ExtractedDecision(BaseModel):
    """Decision or commitment extracted from meeting transcript by LLM."""

    decision: str = Field(description="What was decided")
    participants: list[str] = Field(description="Who agreed to this")
    context: str = Field(description="Discussion context leading to decision")


class ExtractedMinutes(BaseModel):
    """Full structured minutes extracted from transcript by LLM."""

    executive_summary: str = Field(
        description="2-3 paragraph high-level summary of the meeting"
    )
    key_topics: list[str] = Field(description="Main topics discussed")
    action_items: list[ExtractedActionItem] = Field(
        description="All action items with owners"
    )
    decisions: list[ExtractedDecision] = Field(
        description="Decisions and commitments made"
    )
    follow_up_date: str | None = Field(
        None, description="Next meeting date if mentioned"
    )


class ChunkSummary(BaseModel):
    """Summary of a single transcript chunk for map-reduce processing."""

    summary: str = Field(description="Summary of this transcript segment")
    action_items: list[ExtractedActionItem] = Field(
        default_factory=list,
        description="Action items found in this segment",
    )
    decisions: list[ExtractedDecision] = Field(
        default_factory=list,
        description="Decisions found in this segment",
    )


# ── System Prompts ───────────────────────────────────────────────────────────

SINGLE_PASS_SYSTEM_PROMPT = (
    "You are analyzing a sales meeting transcript to generate structured "
    "meeting minutes. Extract:\n"
    "1) Executive summary (2-3 paragraphs)\n"
    "2) Key topics discussed\n"
    "3) Action items with specific owners and due dates\n"
    "4) Decisions and commitments made\n\n"
    "Note absence of items rather than making assumptions. "
    "Be precise about who said what and who committed to what."
)

CHUNK_SUMMARY_SYSTEM_PROMPT = (
    "You are summarizing a segment of a sales meeting transcript. "
    "Extract a concise summary, any action items with owners, "
    "and any decisions or commitments made in this segment. "
    "Be precise about attribution -- who said what and who committed to what."
)

REDUCE_SYSTEM_PROMPT = (
    "You are synthesizing multiple segment summaries from a long sales "
    "meeting into final structured meeting minutes. Combine and deduplicate "
    "information across segments. Extract:\n"
    "1) Executive summary (2-3 paragraphs covering the full meeting)\n"
    "2) Key topics discussed across all segments\n"
    "3) All action items with owners (deduplicated)\n"
    "4) All decisions and commitments (deduplicated)\n\n"
    "Note absence of items rather than making assumptions. "
    "Merge overlapping information from adjacent segments."
)


# ── MinutesGenerator ─────────────────────────────────────────────────────────


class MinutesGenerator:
    """Generates structured meeting minutes from transcripts.

    Uses instructor + litellm for structured LLM extraction (Phase 4 pattern).
    Handles long transcripts via map-reduce: chunk at speaker boundaries,
    summarize each chunk, then synthesize final minutes.

    Args:
        repository: MeetingRepository for persisting generated minutes.
        llm_service: Optional LLM service (used for model routing if available).
    """

    def __init__(
        self,
        repository: MeetingRepository,
        llm_service: object | None = None,
    ) -> None:
        self._repository = repository
        self._llm_service = llm_service

    async def generate(
        self,
        transcript: Transcript,
        attendees: list[Participant],
        meeting_metadata: dict,
        tenant_id: str,
    ) -> MeetingMinutes:
        """Generate structured minutes from a meeting transcript.

        If the transcript token count is below MAX_TOKENS_PER_CHUNK, uses
        single-pass extraction. Otherwise uses map-reduce: chunk at speaker
        boundaries, summarize each chunk, then synthesize final minutes.

        Args:
            transcript: Full meeting transcript with entries and full_text.
            attendees: List of meeting participants.
            meeting_metadata: Dict with 'title', 'date', etc.
            tenant_id: Tenant UUID string for persistence.

        Returns:
            MeetingMinutes with all 4 content types populated.
        """
        transcript_text = transcript.full_text

        try:
            if _estimate_tokens(transcript_text) < MAX_TOKENS_PER_CHUNK:
                extracted = await self._extract_minutes_single_pass(
                    transcript_text, attendees, meeting_metadata
                )
            else:
                extracted = await self._extract_map_reduce(
                    transcript_text, attendees, meeting_metadata
                )
        except Exception:
            logger.warning(
                "minutes_extraction_failed_falling_back",
                meeting_title=meeting_metadata.get("title", "Unknown"),
                exc_info=True,
            )
            # Graceful fallback: return minutes with transcript only
            extracted = ExtractedMinutes(
                executive_summary="",
                key_topics=[],
                action_items=[],
                decisions=[],
                follow_up_date=None,
            )

        # Build MeetingMinutes schema from extracted data
        now = datetime.now(timezone.utc)
        minutes = MeetingMinutes(
            id=uuid.uuid4(),
            meeting_id=transcript.meeting_id,
            executive_summary=extracted.executive_summary,
            key_topics=extracted.key_topics,
            action_items=[
                _to_schema_action_item(ai) for ai in extracted.action_items
            ],
            decisions=[_to_schema_decision(d) for d in extracted.decisions],
            follow_up_date=extracted.follow_up_date,
            generated_at=now,
        )

        # Save to repository
        saved_minutes = await self._repository.save_minutes(tenant_id, minutes)

        # Update meeting status to MINUTES_GENERATED
        await self._repository.update_meeting_status(
            tenant_id,
            str(transcript.meeting_id),
            MeetingStatus.MINUTES_GENERATED,
        )

        logger.info(
            "minutes_generated",
            meeting_id=str(transcript.meeting_id),
            action_items=len(minutes.action_items),
            decisions=len(minutes.decisions),
            key_topics=len(minutes.key_topics),
        )

        return saved_minutes

    async def _extract_minutes_single_pass(
        self,
        transcript_text: str,
        attendees: list[Participant],
        metadata: dict,
    ) -> ExtractedMinutes:
        """Extract structured minutes in a single LLM call.

        Uses instructor.from_litellm(litellm.acompletion) pattern.

        Args:
            transcript_text: Full transcript text.
            attendees: Meeting participants.
            metadata: Meeting metadata (title, date, etc.).

        Returns:
            ExtractedMinutes with all fields populated.
        """
        import instructor
        import litellm

        client = instructor.from_litellm(litellm.acompletion)

        model = self._resolve_model()
        attendee_names = ", ".join(a.name for a in attendees)

        return await client.chat.completions.create(
            model=model,
            response_model=ExtractedMinutes,
            messages=[
                {"role": "system", "content": SINGLE_PASS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Meeting: {metadata.get('title', 'Sales Meeting')}\n"
                        f"Date: {metadata.get('date', 'Unknown')}\n"
                        f"Attendees: {attendee_names}\n\n"
                        f"Transcript:\n{transcript_text}"
                    ),
                },
            ],
            max_tokens=4096,
            temperature=0.1,
        )

    async def _summarize_chunk(self, chunk_text: str) -> ChunkSummary:
        """Extract summary, action items, and decisions from a single chunk.

        Args:
            chunk_text: A segment of the full transcript.

        Returns:
            ChunkSummary with summary and extracted items.
        """
        import instructor
        import litellm

        client = instructor.from_litellm(litellm.acompletion)
        model = self._resolve_model()

        return await client.chat.completions.create(
            model=model,
            response_model=ChunkSummary,
            messages=[
                {"role": "system", "content": CHUNK_SUMMARY_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Transcript segment:\n{chunk_text}",
                },
            ],
            max_tokens=2048,
            temperature=0.1,
        )

    async def _extract_map_reduce(
        self,
        transcript_text: str,
        attendees: list[Participant],
        metadata: dict,
    ) -> ExtractedMinutes:
        """Map-reduce extraction for long transcripts.

        MAP: Chunk transcript at speaker boundaries, summarize each chunk.
        REDUCE: Synthesize all chunk summaries into final minutes.

        Args:
            transcript_text: Full (long) transcript text.
            attendees: Meeting participants.
            metadata: Meeting metadata.

        Returns:
            ExtractedMinutes synthesized from all chunks.
        """
        import instructor
        import litellm

        # MAP phase: chunk and summarize
        chunks = _chunk_transcript(transcript_text)
        summaries: list[ChunkSummary] = []
        for chunk in chunks:
            summary = await self._summarize_chunk(chunk)
            summaries.append(summary)

        # REDUCE phase: synthesize all summaries into final minutes
        combined_text = "\n\n---\n\n".join(
            f"Segment {i + 1}:\n{s.summary}\n"
            f"Action items: {len(s.action_items)}\n"
            f"Decisions: {len(s.decisions)}"
            for i, s in enumerate(summaries)
        )

        client = instructor.from_litellm(litellm.acompletion)
        model = self._resolve_model()
        attendee_names = ", ".join(a.name for a in attendees)

        return await client.chat.completions.create(
            model=model,
            response_model=ExtractedMinutes,
            messages=[
                {"role": "system", "content": REDUCE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"Meeting: {metadata.get('title', 'Sales Meeting')}\n"
                        f"Date: {metadata.get('date', 'Unknown')}\n"
                        f"Attendees: {attendee_names}\n\n"
                        f"Segment Summaries:\n{combined_text}"
                    ),
                },
            ],
            max_tokens=4096,
            temperature=0.1,
        )

    def _resolve_model(self) -> str:
        """Resolve the LLM model to use for minutes extraction.

        Prefers model from router config if available, falls back to
        MODEL_REASONING constant.

        Returns:
            Model identifier string for litellm.
        """
        if hasattr(self._llm_service, "router") and self._llm_service.router:
            for m in self._llm_service.router.model_list:
                if m.get("model_name") == "reasoning":
                    return m["litellm_params"]["model"]
        return MODEL_REASONING


# ── Module-Level Helpers ─────────────────────────────────────────────────────


def _estimate_tokens(text: str) -> int:
    """Estimate token count from text length.

    Uses the simple chars / CHARS_PER_TOKEN ratio matching the 03-02
    decision for token estimation.

    Args:
        text: Input text to estimate tokens for.

    Returns:
        Estimated token count.
    """
    return int(len(text) / CHARS_PER_TOKEN)


def _chunk_transcript(transcript_text: str) -> list[str]:
    """Split transcript at speaker change boundaries near token limit.

    Prefers splitting at speaker turns (lines matching 'Speaker: text'
    pattern) rather than mid-sentence. Includes last 2 speaker turns
    from previous chunk as overlap for context continuity.

    Args:
        transcript_text: Full transcript text with speaker attributions.

    Returns:
        List of transcript chunks, each under MAX_TOKENS_PER_CHUNK tokens.
    """
    if not transcript_text.strip():
        return []

    lines = transcript_text.split("\n")
    max_chars = int(MAX_TOKENS_PER_CHUNK * CHARS_PER_TOKEN)

    # Identify speaker turn boundaries (lines matching "Name: text" pattern)
    speaker_pattern = re.compile(r"^[A-Za-z][A-Za-z\s'.,-]+:\s")
    turn_starts: list[int] = []
    for i, line in enumerate(lines):
        if speaker_pattern.match(line):
            turn_starts.append(i)

    # If no speaker turns detected, fall back to line-based chunking
    if not turn_starts:
        return _chunk_by_chars(transcript_text, max_chars)

    chunks: list[str] = []
    current_start = 0
    overlap_turns: list[int] = []  # Track last 2 turn indices for overlap

    for idx, turn_idx in enumerate(turn_starts):
        # Calculate text from current_start to this turn
        segment = "\n".join(lines[current_start : turn_idx + 1])
        segment_to_end = "\n".join(lines[current_start:turn_idx])

        if len(segment_to_end) >= max_chars and turn_idx > current_start:
            # Current chunk is at or over limit -- split here
            chunk_text = "\n".join(lines[current_start:turn_idx])
            if chunk_text.strip():
                chunks.append(chunk_text)

            # Set next chunk start with overlap (last 2 speaker turns)
            if len(overlap_turns) >= 2:
                current_start = overlap_turns[-2]
            elif overlap_turns:
                current_start = overlap_turns[-1]
            else:
                current_start = turn_idx

        # Track this turn for overlap
        overlap_turns.append(turn_idx)
        if len(overlap_turns) > 2:
            overlap_turns.pop(0)

    # Add remaining text as final chunk
    remaining = "\n".join(lines[current_start:])
    if remaining.strip():
        chunks.append(remaining)

    return chunks if chunks else [transcript_text]


def _chunk_by_chars(text: str, max_chars: int) -> list[str]:
    """Fallback chunking by character count when no speaker turns detected.

    Args:
        text: Full text to chunk.
        max_chars: Maximum characters per chunk.

    Returns:
        List of text chunks.
    """
    chunks: list[str] = []
    lines = text.split("\n")
    current_chunk: list[str] = []
    current_len = 0

    for line in lines:
        line_len = len(line) + 1  # +1 for newline
        if current_len + line_len > max_chars and current_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
            current_len = 0
        current_chunk.append(line)
        current_len += line_len

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    return chunks


def _to_schema_action_item(extracted: ExtractedActionItem):
    """Convert extracted action item to schema ActionItem."""
    from src.app.meetings.schemas import ActionItem

    return ActionItem(
        owner=extracted.owner,
        action=extracted.action,
        due_date=extracted.due_date,
        context=extracted.context,
    )


def _to_schema_decision(extracted: ExtractedDecision):
    """Convert extracted decision to schema Decision."""
    from src.app.meetings.schemas import Decision

    return Decision(
        decision=extracted.decision,
        participants=extracted.participants,
        context=extracted.context,
    )
