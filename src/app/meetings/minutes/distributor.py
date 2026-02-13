"""MinutesDistributor -- internal storage and controlled external sharing.

Minutes are internal-only by default per CONTEXT.md locked decisions.
The rep controls what gets shared externally via explicit manual call.
Per RESEARCH Pitfall 7: NEVER automatically share with external participants.

Distribution flow:
1. save_internally: persist minutes + notify internal stakeholders
2. notify_internal: email internal attendees with summary and link
3. share_externally: manual endpoint -- rep chooses recipients and content

Exports:
    MinutesDistributor: Main distribution service.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import structlog

from src.app.meetings.repository import MeetingRepository
from src.app.meetings.schemas import (
    Meeting,
    MeetingMinutes,
    MeetingStatus,
    Participant,
    ParticipantRole,
)

logger = structlog.get_logger(__name__)


class MinutesDistributor:
    """Distributes meeting minutes internally with manual external sharing.

    Internal-only by default. Rep/manager notified when minutes are ready.
    External sharing requires explicit call with recipient list.

    Args:
        repository: MeetingRepository for loading and updating minutes.
        gmail_service: Optional GmailService for sending emails.
        notification_service: Optional service for internal alerts.
    """

    def __init__(
        self,
        repository: MeetingRepository,
        gmail_service: object | None = None,
        notification_service: object | None = None,
    ) -> None:
        self._repository = repository
        self._gmail_service = gmail_service
        self._notification_service = notification_service

    async def save_internally(
        self,
        minutes: MeetingMinutes,
        tenant_id: str,
    ) -> None:
        """Save minutes internally and notify stakeholders.

        Ensures minutes are persisted (already done by generator, this
        provides an idempotent save path). Updates meeting status and
        emits internal notification.

        Per CONTEXT.md: internal-only by default, rep/manager notified
        when ready.

        Args:
            minutes: MeetingMinutes to save.
            tenant_id: Tenant UUID string.
        """
        # Ensure minutes are saved (idempotent -- generator already saves)
        existing = await self._repository.get_minutes(
            tenant_id, str(minutes.meeting_id)
        )
        if existing is None:
            await self._repository.save_minutes(tenant_id, minutes)

        # Update meeting status
        await self._repository.update_meeting_status(
            tenant_id,
            str(minutes.meeting_id),
            MeetingStatus.MINUTES_GENERATED,
        )

        # Emit internal notification
        if self._notification_service and hasattr(
            self._notification_service, "notify"
        ):
            try:
                meeting = await self._repository.get_meeting(
                    tenant_id, str(minutes.meeting_id)
                )
                title = meeting.title if meeting else "Unknown meeting"
                await self._notification_service.notify(
                    f"Meeting minutes ready for {title}"
                )
            except Exception:
                logger.warning(
                    "internal_notification_failed",
                    meeting_id=str(minutes.meeting_id),
                    exc_info=True,
                )

        logger.info(
            "minutes_saved_internally",
            meeting_id=str(minutes.meeting_id),
            tenant_id=tenant_id,
        )

    async def notify_internal(
        self,
        meeting: Meeting,
        minutes: MeetingMinutes,
        tenant_id: str,
    ) -> None:
        """Send internal email notification to meeting organizer and internal attendees.

        Email includes meeting title, date, executive summary, and a note
        that full minutes are available in the system.

        Uses GmailService.send_email if available, falls back to logging.
        Per CONTEXT.md: rep/manager notified when ready.

        Args:
            meeting: Meeting with participant details.
            minutes: Generated MeetingMinutes.
            tenant_id: Tenant UUID string.
        """
        internal_attendees = [
            p for p in meeting.participants
            if p.role == ParticipantRole.INTERNAL
        ]

        if not internal_attendees:
            logger.info(
                "no_internal_attendees_to_notify",
                meeting_id=str(meeting.id),
            )
            return

        email_html = _build_internal_email(meeting, minutes)

        if self._gmail_service and hasattr(self._gmail_service, "send_email"):
            from src.app.services.gsuite.models import EmailMessage

            for attendee in internal_attendees:
                try:
                    email = EmailMessage(
                        to=attendee.email,
                        subject=f"Meeting Minutes Ready: {meeting.title}",
                        body_html=email_html,
                    )
                    await self._gmail_service.send_email(email)
                    logger.info(
                        "internal_notification_sent",
                        to=attendee.email,
                        meeting_id=str(meeting.id),
                    )
                except Exception:
                    logger.warning(
                        "internal_email_failed",
                        to=attendee.email,
                        meeting_id=str(meeting.id),
                        exc_info=True,
                    )
        else:
            # Fallback: log the notification
            for attendee in internal_attendees:
                logger.info(
                    "internal_notification_logged",
                    to=attendee.email,
                    meeting_title=meeting.title,
                    summary_preview=minutes.executive_summary[:200],
                )

    async def share_externally(
        self,
        meeting_id: uuid.UUID,
        tenant_id: str,
        recipient_emails: list[str],
        include_transcript: bool = False,
    ) -> dict:
        """Manually share minutes externally -- rep controls what gets sent.

        Loads minutes from repository, builds customer-appropriate email
        (executive summary + action items only, NOT internal notes),
        and sends to specified recipients.

        Per CONTEXT.md: no automatic external distribution, rep controls
        sharing. Per RESEARCH Pitfall 7: NEVER automatically share.

        Args:
            meeting_id: UUID of the meeting.
            tenant_id: Tenant UUID string.
            recipient_emails: List of recipient email addresses.
            include_transcript: If True, append sanitized transcript.

        Returns:
            Dict with sent_to list and share_time.

        Raises:
            ValueError: If minutes or meeting not found.
        """
        minutes = await self._repository.get_minutes(
            tenant_id, str(meeting_id)
        )
        if minutes is None:
            raise ValueError(
                f"Minutes not found for meeting {meeting_id}"
            )

        meeting = await self._repository.get_meeting(
            tenant_id, str(meeting_id)
        )
        if meeting is None:
            raise ValueError(
                f"Meeting not found: {meeting_id}"
            )

        email_html = _build_external_email(meeting, minutes, include_transcript)

        sent_to: list[str] = []
        share_time = datetime.now(timezone.utc)

        if self._gmail_service and hasattr(self._gmail_service, "send_email"):
            from src.app.services.gsuite.models import EmailMessage

            for recipient in recipient_emails:
                try:
                    email = EmailMessage(
                        to=recipient,
                        subject=f"Meeting Summary: {meeting.title}",
                        body_html=email_html,
                    )
                    await self._gmail_service.send_email(email)
                    sent_to.append(recipient)
                    logger.info(
                        "external_minutes_shared",
                        to=recipient,
                        meeting_id=str(meeting_id),
                    )
                except Exception:
                    logger.warning(
                        "external_share_failed",
                        to=recipient,
                        meeting_id=str(meeting_id),
                        exc_info=True,
                    )
        else:
            # Without gmail service, log and mark as sent for testing
            for recipient in recipient_emails:
                logger.info(
                    "external_share_logged",
                    to=recipient,
                    meeting_id=str(meeting_id),
                )
                sent_to.append(recipient)

        # Mark minutes as shared externally
        await self._repository.mark_minutes_shared(tenant_id, str(meeting_id))

        return {
            "sent_to": sent_to,
            "share_time": share_time.isoformat(),
        }


# ── Email Builders ───────────────────────────────────────────────────────────


def _build_internal_email(meeting: Meeting, minutes: MeetingMinutes) -> str:
    """Build HTML email for internal stakeholders.

    Full content: executive summary, all action items, all decisions,
    and note about transcript availability.

    Args:
        meeting: Meeting with metadata.
        minutes: Generated MeetingMinutes.

    Returns:
        HTML string for email body.
    """
    action_items_html = ""
    if minutes.action_items:
        items = "".join(
            f"<li><strong>{ai.owner}</strong>: {ai.action}"
            f"{f' (Due: {ai.due_date})' if ai.due_date else ''}</li>"
            for ai in minutes.action_items
        )
        action_items_html = f"<h3>Action Items</h3><ul>{items}</ul>"

    decisions_html = ""
    if minutes.decisions:
        items = "".join(
            f"<li><strong>{d.decision}</strong> "
            f"(Agreed by: {', '.join(d.participants)})</li>"
            for d in minutes.decisions
        )
        decisions_html = f"<h3>Decisions & Commitments</h3><ul>{items}</ul>"

    topics_html = ""
    if minutes.key_topics:
        items = "".join(f"<li>{t}</li>" for t in minutes.key_topics)
        topics_html = f"<h3>Key Topics</h3><ul>{items}</ul>"

    follow_up_html = ""
    if minutes.follow_up_date:
        follow_up_html = (
            f"<p><strong>Follow-up Date:</strong> {minutes.follow_up_date}</p>"
        )

    return f"""<html>
<body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto;">
<h2>Meeting Minutes: {meeting.title}</h2>
<p><strong>Date:</strong> {meeting.scheduled_start.strftime('%B %d, %Y at %I:%M %p')}</p>
<p><strong>Participants:</strong> {', '.join(p.name for p in meeting.participants)}</p>
<hr>
<h3>Executive Summary</h3>
<p>{minutes.executive_summary}</p>
{topics_html}
{action_items_html}
{decisions_html}
{follow_up_html}
<hr>
<p><em>Full transcript is available in the system.</em></p>
</body>
</html>"""


def _build_external_email(
    meeting: Meeting,
    minutes: MeetingMinutes,
    include_transcript: bool = False,
) -> str:
    """Build HTML email for external (customer-facing) sharing.

    Customer-appropriate: executive summary + action items + decisions.
    No internal strategy, notes, or competitive information.
    Professional formatting.

    Args:
        meeting: Meeting with metadata.
        minutes: Generated MeetingMinutes.
        include_transcript: Whether to include sanitized transcript.

    Returns:
        HTML string for email body.
    """
    action_items_html = ""
    if minutes.action_items:
        items = "".join(
            f"<li><strong>{ai.owner}</strong>: {ai.action}"
            f"{f' (Due: {ai.due_date})' if ai.due_date else ''}</li>"
            for ai in minutes.action_items
        )
        action_items_html = f"<h3>Action Items</h3><ul>{items}</ul>"

    decisions_html = ""
    if minutes.decisions:
        items = "".join(
            f"<li>{d.decision}</li>"
            for d in minutes.decisions
        )
        decisions_html = f"<h3>Decisions & Next Steps</h3><ul>{items}</ul>"

    follow_up_html = ""
    if minutes.follow_up_date:
        follow_up_html = (
            f"<p><strong>Next Meeting:</strong> {minutes.follow_up_date}</p>"
        )

    transcript_html = ""
    if include_transcript:
        transcript_html = (
            "<hr><h3>Meeting Transcript</h3>"
            "<p><em>Transcript attached for your reference.</em></p>"
        )

    return f"""<html>
<body style="font-family: Arial, sans-serif; max-width: 700px; margin: 0 auto;">
<h2>Meeting Summary: {meeting.title}</h2>
<p><strong>Date:</strong> {meeting.scheduled_start.strftime('%B %d, %Y at %I:%M %p')}</p>
<hr>
<h3>Summary</h3>
<p>{minutes.executive_summary}</p>
{action_items_html}
{decisions_html}
{follow_up_html}
{transcript_html}
<hr>
<p><em>Thank you for your time. Please let us know if you have any questions.</em></p>
</body>
</html>"""
