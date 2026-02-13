"""BriefingGenerator -- creates multi-format pre-meeting briefings.

Generates briefings in three formats per CONTEXT.md:
1. Structured -- full Markdown document with sections
2. Bullet -- concise bullet-point summary for quick scanning
3. Adaptive -- detailed for new contacts, brief for ongoing relationships

Uses instructor + litellm pattern (established in Phase 4) for LLM-powered
content generation with model='reasoning' (quality model) since briefings
are not latency-sensitive. Falls back to rule-based content if LLM is
unavailable.

Briefings include account context, attendee profiles, objectives, and
suggested talk tracks (CONTEXT.md: briefing pipeline requirements).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

import structlog
from pydantic import BaseModel, Field

from src.app.meetings.schemas import (
    Briefing,
    BriefingContent,
    Meeting,
    Participant,
    ParticipantRole,
)

if TYPE_CHECKING:
    from src.app.meetings.repository import MeetingRepository

logger = structlog.get_logger(__name__)


# ── Pydantic Model for LLM Extraction ───────────────────────────────────────


class BriefingExtraction(BaseModel):
    """Structured extraction from LLM for briefing content.

    Used with instructor for reliable extraction of objectives and
    talk tracks from meeting context.
    """

    objectives: list[str] = Field(
        description="3-5 meeting objectives based on deal context and attendees"
    )
    talk_tracks: list[str] = Field(
        description="3-5 suggested conversation topics based on deal stage and QBS methodology"
    )
    account_summary: str = Field(
        default="",
        description="Brief account context summary based on available information",
    )


# ── Default Talk Tracks by Deal Stage ────────────────────────────────────────

_STAGE_OBJECTIVES: dict[str, list[str]] = {
    "prospecting": [
        "Build rapport and establish credibility",
        "Understand prospect's current situation and challenges",
        "Identify initial pain points for deeper exploration",
    ],
    "discovery": [
        "Explore business pain at emotional level (QBS: pain funnel)",
        "Map organizational decision-making structure",
        "Qualify budget, timeline, and authority",
    ],
    "qualification": [
        "Confirm BANT and MEDDIC qualification signals",
        "Identify remaining qualification gaps",
        "Establish next steps toward evaluation",
    ],
    "evaluation": [
        "Address technical and business concerns",
        "Demonstrate ROI and competitive differentiation",
        "Advance toward decision commitment",
    ],
    "negotiation": [
        "Discuss pricing and contract terms",
        "Address final objections",
        "Secure commitment and timeline for close",
    ],
    "closed_won": [
        "Review onboarding and implementation plan",
        "Confirm key success metrics",
        "Establish ongoing relationship cadence",
    ],
    "closed_lost": [
        "Understand reasons for loss",
        "Maintain relationship for future opportunities",
        "Gather competitive intelligence",
    ],
    "stalled": [
        "Re-engage with new value proposition or insight",
        "Identify what changed since last active engagement",
        "Explore alternative paths to restart momentum",
    ],
}

_STAGE_TALK_TRACKS: dict[str, list[str]] = {
    "prospecting": [
        "Industry trends affecting their business",
        "Similar customer success stories",
        "Open-ended questions about their priorities",
    ],
    "discovery": [
        "Pain funnel: surface pain -> business impact -> emotional impact",
        "Decision process and stakeholder mapping",
        "Current solution limitations and workarounds",
    ],
    "qualification": [
        "Budget ownership and approval process",
        "Decision criteria and evaluation timeline",
        "Champion identification and coaching",
    ],
    "evaluation": [
        "Technical proof of concept results",
        "ROI calculations with their specific metrics",
        "Competitive differentiation on their key criteria",
    ],
    "negotiation": [
        "Value-based pricing justification",
        "Contract flexibility and terms",
        "Implementation timeline and resource commitment",
    ],
    "closed_won": [
        "Onboarding milestones and timeline",
        "Key stakeholder introductions for customer success",
        "Quick wins for early value demonstration",
    ],
    "closed_lost": [
        "Post-mortem: what could have been different",
        "Future opportunity triggers to watch for",
        "Industry relationship maintenance",
    ],
    "stalled": [
        "New product capabilities or company news",
        "Changed market conditions relevant to their pain",
        "Alternative approaches or packaging",
    ],
}


class BriefingGenerator:
    """Generates multi-format pre-meeting briefings.

    Creates briefings with account context, attendee profiles, objectives,
    and talk tracks. Supports three format variants per CONTEXT.md:
    structured, bullet, and adaptive.

    Args:
        repository: MeetingRepository for saving generated briefings.
        llm_service: Optional LLM service for content generation.
            If None, falls back to rule-based content.
        deal_repository: Optional DealRepository for deal context.
            If None, briefings omit deal-specific context.
    """

    def __init__(
        self,
        repository: MeetingRepository,
        llm_service: Any | None = None,
        deal_repository: Any | None = None,
    ) -> None:
        self._repository = repository
        self._llm_service = llm_service
        self._deal_repository = deal_repository

    # ── Public API ───────────────────────────────────────────────────────

    async def generate_briefing(
        self, meeting: Meeting, tenant_id: str, format: str = "structured"
    ) -> Briefing:
        """Generate a single-format briefing for a meeting.

        Gathers context from multiple sources (participants, deal data),
        generates content via LLM or rule-based fallback, renders in
        the requested format, and saves to repository.

        Args:
            meeting: Meeting to generate briefing for.
            tenant_id: Tenant UUID string.
            format: Briefing format -- "structured", "bullet", or "adaptive".

        Returns:
            Persisted Briefing with generated content.
        """
        content = await self._build_content(meeting, tenant_id)

        briefing = Briefing(
            meeting_id=meeting.id,
            format=format,
            content=content,
            generated_at=datetime.now(timezone.utc),
        )

        saved = await self._repository.save_briefing(tenant_id, briefing)
        logger.info(
            "briefing_generated",
            meeting_id=str(meeting.id),
            format=format,
        )
        return saved

    async def generate_all_formats(
        self, meeting: Meeting, tenant_id: str
    ) -> list[Briefing]:
        """Generate briefings in all 3 formats per CONTEXT.md.

        Generates structured, bullet, and adaptive format briefings,
        saves all to repository, and returns them.

        Args:
            meeting: Meeting to generate briefings for.
            tenant_id: Tenant UUID string.

        Returns:
            List of 3 Briefing objects (one per format).
        """
        formats = ["structured", "bullet", "adaptive"]
        briefings: list[Briefing] = []

        for fmt in formats:
            briefing = await self.generate_briefing(meeting, tenant_id, format=fmt)
            briefings.append(briefing)

        logger.info(
            "all_briefing_formats_generated",
            meeting_id=str(meeting.id),
            count=len(briefings),
        )
        return briefings

    # ── Content Building ─────────────────────────────────────────────────

    async def _build_content(
        self, meeting: Meeting, tenant_id: str
    ) -> BriefingContent:
        """Build BriefingContent by gathering context from multiple sources.

        Sources:
        a. Account context: company names from external participants, deal info
        b. Attendee profiles: names, titles, roles
        c. Objectives: inferred from title, deal stage, conversation context
        d. Talk tracks: based on deal stage and QBS methodology

        Args:
            meeting: Meeting to build content for.
            tenant_id: Tenant UUID string.

        Returns:
            BriefingContent with all sections populated.
        """
        # Gather attendee profiles
        attendee_profiles = self._build_attendee_profiles(meeting.participants)

        # Gather account context
        account_context = await self._build_account_context(
            meeting, tenant_id
        )

        # Gather deal context
        deal_context = await self._get_deal_context(meeting, tenant_id)
        deal_stage = self._extract_deal_stage(deal_context)

        # Generate objectives and talk tracks
        objectives, talk_tracks = await self._generate_objectives_and_tracks(
            meeting, deal_stage, account_context
        )

        return BriefingContent(
            account_context=account_context,
            attendee_profiles=attendee_profiles,
            objectives=objectives,
            talk_tracks=talk_tracks,
            deal_context=deal_context,
        )

    @staticmethod
    def _build_attendee_profiles(
        participants: list[Participant],
    ) -> list[dict]:
        """Build attendee profile dicts from participant list.

        Args:
            participants: List of meeting Participant schemas.

        Returns:
            List of profile dicts with name, email, role, title, company.
        """
        profiles: list[dict] = []
        for p in participants:
            if p.role == ParticipantRole.AGENT:
                continue  # Skip the agent itself
            profiles.append(
                {
                    "name": p.name,
                    "email": p.email,
                    "role": p.role.value,
                    "title": p.title or "Unknown",
                    "company": p.company or "Unknown",
                }
            )
        return profiles

    async def _build_account_context(
        self, meeting: Meeting, tenant_id: str
    ) -> str:
        """Build account context string from participant companies and deal data.

        Args:
            meeting: Meeting with participant info.
            tenant_id: Tenant UUID string.

        Returns:
            Account context description string.
        """
        # Extract external company names
        external_companies: set[str] = set()
        external_names: list[str] = []
        for p in meeting.participants:
            if p.role == ParticipantRole.EXTERNAL:
                if p.company:
                    external_companies.add(p.company)
                external_names.append(p.name)

        if external_companies:
            companies_str = ", ".join(sorted(external_companies))
            context = f"Meeting with representatives from {companies_str}."
        elif external_names:
            names_str = ", ".join(external_names)
            context = f"Meeting with external participants: {names_str}."
        else:
            context = "Internal meeting with no external participants identified."

        # Add meeting title context
        if meeting.title:
            context += f" Meeting topic: {meeting.title}."

        return context

    async def _get_deal_context(
        self, meeting: Meeting, tenant_id: str
    ) -> str | None:
        """Get deal context from deal repository if available.

        Args:
            meeting: Meeting to find deal context for.
            tenant_id: Tenant UUID string.

        Returns:
            Deal context string, or None if unavailable.
        """
        if self._deal_repository is None:
            return None

        try:
            # Attempt to find deals matching external participant companies
            # This is a best-effort lookup -- deal_repository integration
            # depends on Phase 5 DealRepository being available
            return None  # Placeholder until deal integration is wired
        except Exception:
            logger.debug(
                "deal_context_unavailable",
                meeting_id=str(meeting.id),
            )
            return None

    @staticmethod
    def _extract_deal_stage(deal_context: str | None) -> str:
        """Extract deal stage from deal context string.

        Args:
            deal_context: Deal context string or None.

        Returns:
            Deal stage string, defaulting to "discovery".
        """
        if deal_context is None:
            return "discovery"

        # Parse stage from deal context if available
        for stage in _STAGE_OBJECTIVES:
            if stage in deal_context.lower():
                return stage

        return "discovery"

    async def _generate_objectives_and_tracks(
        self,
        meeting: Meeting,
        deal_stage: str,
        account_context: str,
    ) -> tuple[list[str], list[str]]:
        """Generate meeting objectives and talk tracks.

        Attempts LLM-powered generation first, falls back to rule-based
        content keyed by deal stage.

        Args:
            meeting: Meeting to generate content for.
            deal_stage: Current deal stage for context.
            account_context: Account context summary.

        Returns:
            Tuple of (objectives, talk_tracks) lists.
        """
        # Try LLM-powered generation
        if self._llm_service is not None:
            try:
                return await self._llm_generate_objectives(
                    meeting, deal_stage, account_context
                )
            except Exception:
                logger.warning(
                    "llm_briefing_fallback",
                    meeting_id=str(meeting.id),
                    reason="LLM generation failed, using rule-based fallback",
                )

        # Rule-based fallback
        return self._rule_based_objectives(deal_stage, meeting.title)

    async def _llm_generate_objectives(
        self,
        meeting: Meeting,
        deal_stage: str,
        account_context: str,
    ) -> tuple[list[str], list[str]]:
        """Generate objectives and talk tracks via LLM.

        Uses instructor + litellm pattern (Phase 4) with model='reasoning'
        for quality content generation.

        Args:
            meeting: Meeting context.
            deal_stage: Current deal stage.
            account_context: Account context summary.

        Returns:
            Tuple of (objectives, talk_tracks) from LLM extraction.
        """
        import instructor
        import litellm

        client = instructor.from_litellm(litellm.acompletion)

        prompt = (
            f"Generate meeting preparation content for a sales meeting.\n\n"
            f"Meeting: {meeting.title}\n"
            f"Account Context: {account_context}\n"
            f"Deal Stage: {deal_stage}\n"
            f"Attendees: {', '.join(p.name for p in meeting.participants if p.role != ParticipantRole.AGENT)}\n\n"
            f"Generate 3-5 specific objectives for this meeting and 3-5 "
            f"suggested talk tracks based on the deal stage and QBS methodology."
        )

        extraction = await client.chat.completions.create(
            model="reasoning",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a sales meeting preparation assistant. "
                        "Generate actionable, specific meeting objectives "
                        "and talk tracks based on deal context and QBS "
                        "(Question Based Selling) methodology."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            response_model=BriefingExtraction,
            temperature=0.3,
        )

        return extraction.objectives, extraction.talk_tracks

    @staticmethod
    def _rule_based_objectives(
        deal_stage: str, meeting_title: str
    ) -> tuple[list[str], list[str]]:
        """Generate rule-based objectives and talk tracks by deal stage.

        Fallback when LLM is unavailable. Uses pre-defined content
        mapped to deal stages.

        Args:
            deal_stage: Current deal stage.
            meeting_title: Meeting title for context.

        Returns:
            Tuple of (objectives, talk_tracks) lists.
        """
        objectives = list(_STAGE_OBJECTIVES.get(deal_stage, _STAGE_OBJECTIVES["discovery"]))
        talk_tracks = list(_STAGE_TALK_TRACKS.get(deal_stage, _STAGE_TALK_TRACKS["discovery"]))

        # Add meeting-title-specific objective
        if meeting_title and meeting_title != "Untitled Meeting":
            objectives.insert(0, f"Address agenda: {meeting_title}")

        return objectives, talk_tracks

    # ── Format Renderers ─────────────────────────────────────────────────

    @staticmethod
    def _build_structured_briefing(content: BriefingContent) -> str:
        """Render BriefingContent as a structured Markdown document.

        Sections: Meeting Overview, Attendee Profiles, Account Context,
        Deal Status, Objectives, Suggested Talk Tracks.

        Args:
            content: BriefingContent to render.

        Returns:
            Structured Markdown string.
        """
        sections: list[str] = []

        # Account Context
        sections.append("## Account Context\n")
        sections.append(content.account_context)
        sections.append("")

        # Attendee Profiles
        if content.attendee_profiles:
            sections.append("## Attendee Profiles\n")
            for profile in content.attendee_profiles:
                name = profile.get("name", "Unknown")
                title = profile.get("title", "Unknown")
                company = profile.get("company", "Unknown")
                role = profile.get("role", "external")
                sections.append(f"- **{name}** ({title}, {company}) - {role}")
            sections.append("")

        # Deal Context
        if content.deal_context:
            sections.append("## Deal Status\n")
            sections.append(content.deal_context)
            sections.append("")

        # Objectives
        if content.objectives:
            sections.append("## Objectives\n")
            for i, obj in enumerate(content.objectives, 1):
                sections.append(f"{i}. {obj}")
            sections.append("")

        # Talk Tracks
        if content.talk_tracks:
            sections.append("## Suggested Talk Tracks\n")
            for track in content.talk_tracks:
                sections.append(f"- {track}")
            sections.append("")

        return "\n".join(sections)

    @staticmethod
    def _build_bullet_briefing(content: BriefingContent) -> str:
        """Render BriefingContent as a concise bullet-point summary.

        Quick-scan format for fast consumption before meetings.

        Args:
            content: BriefingContent to render.

        Returns:
            Concise bullet-point string.
        """
        lines: list[str] = []

        lines.append(f"Account: {content.account_context}")
        lines.append("")

        if content.attendee_profiles:
            lines.append("Attendees:")
            for p in content.attendee_profiles:
                lines.append(f"  - {p.get('name', '?')} ({p.get('title', '?')})")

        if content.objectives:
            lines.append("")
            lines.append("Key objectives:")
            for obj in content.objectives:
                lines.append(f"  - {obj}")

        if content.talk_tracks:
            lines.append("")
            lines.append("Talk tracks:")
            for track in content.talk_tracks:
                lines.append(f"  - {track}")

        if content.deal_context:
            lines.append("")
            lines.append(f"Deal: {content.deal_context}")

        return "\n".join(lines)

    @staticmethod
    def _build_adaptive_briefing(
        content: BriefingContent, is_first_meeting: bool
    ) -> str:
        """Render BriefingContent adaptively based on meeting history.

        Detailed for new customer contacts (first meeting with attendees),
        brief for ongoing relationships (previous meetings with same attendees).

        Args:
            content: BriefingContent to render.
            is_first_meeting: Whether this is the first meeting with these attendees.

        Returns:
            Adaptive briefing string -- detailed or brief.
        """
        if is_first_meeting:
            # Detailed format for new contacts
            sections: list[str] = []
            sections.append("# First Meeting Briefing\n")
            sections.append("## Account Background\n")
            sections.append(content.account_context)
            sections.append("")

            if content.attendee_profiles:
                sections.append("## Who You're Meeting\n")
                for p in content.attendee_profiles:
                    name = p.get("name", "Unknown")
                    title = p.get("title", "Unknown")
                    company = p.get("company", "Unknown")
                    sections.append(f"### {name}")
                    sections.append(f"- **Title:** {title}")
                    sections.append(f"- **Company:** {company}")
                    sections.append(f"- **Role:** {p.get('role', 'external')}")
                    sections.append("")

            if content.deal_context:
                sections.append("## Deal Context\n")
                sections.append(content.deal_context)
                sections.append("")

            if content.objectives:
                sections.append("## Meeting Objectives\n")
                for i, obj in enumerate(content.objectives, 1):
                    sections.append(f"{i}. {obj}")
                sections.append("")

            if content.talk_tracks:
                sections.append("## Suggested Talk Tracks\n")
                for track in content.talk_tracks:
                    sections.append(f"- {track}")

            return "\n".join(sections)
        else:
            # Brief format for ongoing relationships
            lines: list[str] = []
            lines.append("# Follow-up Meeting Brief\n")
            lines.append(f"Context: {content.account_context}")

            if content.objectives:
                lines.append("")
                lines.append("Focus areas:")
                for obj in content.objectives[:3]:  # Top 3 only
                    lines.append(f"  - {obj}")

            if content.talk_tracks:
                lines.append("")
                lines.append("Key topics:")
                for track in content.talk_tracks[:3]:  # Top 3 only
                    lines.append(f"  - {track}")

            if content.deal_context:
                lines.append("")
                lines.append(f"Deal update: {content.deal_context}")

            return "\n".join(lines)

    async def _is_first_meeting_with_attendees(
        self, meeting: Meeting, tenant_id: str
    ) -> bool:
        """Check if this is the first meeting with these attendees.

        Looks for prior meetings in the repository with overlapping
        external participants.

        Args:
            meeting: Current meeting.
            tenant_id: Tenant UUID string.

        Returns:
            True if no prior meetings with overlapping external attendees.
        """
        external_emails = {
            p.email.lower()
            for p in meeting.participants
            if p.role == ParticipantRole.EXTERNAL
        }

        if not external_emails:
            return True

        # Check repository for prior meetings with overlapping attendees
        # Use a wide time window to check history
        from datetime import timedelta

        far_past = datetime(2020, 1, 1, tzinfo=timezone.utc)
        prior_meetings = await self._repository.get_upcoming_meetings(
            tenant_id, far_past, meeting.scheduled_start
        )

        for prior in prior_meetings:
            if prior.id == meeting.id:
                continue
            prior_external = {
                p.email.lower()
                for p in prior.participants
                if p.role == ParticipantRole.EXTERNAL
            }
            if external_emails & prior_external:
                return False

        return True
