"""Async Gmail API service for sending and reading emails.

All Google API calls are wrapped in asyncio.to_thread() to avoid
blocking the event loop (Pitfall 7 from research). Email threading
uses In-Reply-To and References headers per RFC 2822 (Pitfall 2).
"""

from __future__ import annotations

import asyncio
import base64
from email.message import EmailMessage as StdlibEmailMessage
from typing import Any

import structlog

from src.app.services.gsuite.auth import GSuiteAuthManager
from src.app.services.gsuite.models import (
    EmailMessage,
    EmailThread,
    EmailThreadMessage,
    SentEmailResult,
)

logger = structlog.get_logger(__name__)


class GmailService:
    """Async wrapper around Gmail API for sending and reading emails."""

    def __init__(
        self,
        auth_manager: GSuiteAuthManager,
        default_user_email: str,
    ) -> None:
        self._auth = auth_manager
        self._default_user_email = default_user_email

    def _build_mime_message(self, email: EmailMessage) -> str:
        """Build an RFC 2822 compliant MIME message.

        Args:
            email: The EmailMessage with content and headers.

        Returns:
            Base64url-encoded raw message string for the Gmail API.
        """
        msg = StdlibEmailMessage()
        msg["To"] = email.to
        msg["Subject"] = email.subject

        if email.cc:
            msg["Cc"] = ", ".join(email.cc)
        if email.bcc:
            msg["Bcc"] = ", ".join(email.bcc)

        # Set threading headers per RFC 2822 (Pitfall 2)
        if email.in_reply_to:
            msg["In-Reply-To"] = email.in_reply_to
            msg["References"] = email.in_reply_to

        # Set HTML body with optional text fallback
        if email.body_text:
            msg.set_content(email.body_text)
            msg.add_alternative(email.body_html, subtype="html")
        else:
            msg.set_content(email.body_html, subtype="html")

        return base64.urlsafe_b64encode(msg.as_bytes()).decode()

    async def send_email(
        self,
        email: EmailMessage,
        user_email: str | None = None,
    ) -> SentEmailResult:
        """Send an email via Gmail API.

        Args:
            email: The email message to send.
            user_email: Sender email (for delegation). Defaults to
                the configured default_user_email.

        Returns:
            SentEmailResult with message_id, thread_id, and label_ids.
        """
        sender = user_email or self._default_user_email
        service = self._auth.get_gmail_service(sender)
        raw = self._build_mime_message(email)

        body: dict[str, Any] = {"raw": raw}
        if email.thread_id:
            body["threadId"] = email.thread_id

        def _send() -> dict:
            return (
                service.users()
                .messages()
                .send(userId="me", body=body)
                .execute()
            )

        logger.info(
            "sending_email",
            to=email.to,
            subject=email.subject,
            thread_id=email.thread_id,
        )
        result = await asyncio.to_thread(_send)

        return SentEmailResult(
            message_id=result.get("id", ""),
            thread_id=result.get("threadId", ""),
            label_ids=result.get("labelIds", []),
        )

    async def get_thread(
        self,
        thread_id: str,
        user_email: str | None = None,
    ) -> EmailThread:
        """Retrieve an email thread from Gmail.

        Args:
            thread_id: The Gmail thread ID.
            user_email: Email for delegation. Defaults to default_user_email.

        Returns:
            EmailThread with message summaries.
        """
        sender = user_email or self._default_user_email
        service = self._auth.get_gmail_service(sender)

        def _get() -> dict:
            return (
                service.users()
                .threads()
                .get(userId="me", id=thread_id, format="metadata")
                .execute()
            )

        logger.info("getting_thread", thread_id=thread_id)
        result = await asyncio.to_thread(_get)

        messages_data = result.get("messages", [])
        thread_messages: list[EmailThreadMessage] = []
        subject = ""

        for msg in messages_data:
            headers = {
                h["name"].lower(): h["value"]
                for h in msg.get("payload", {}).get("headers", [])
            }
            if not subject:
                subject = headers.get("subject", "")

            thread_messages.append(
                EmailThreadMessage(
                    sender=headers.get("from", ""),
                    snippet=msg.get("snippet", ""),
                    date=headers.get("date", ""),
                )
            )

        return EmailThread(
            thread_id=thread_id,
            subject=subject,
            messages=thread_messages,
            message_count=len(thread_messages),
        )

    async def list_threads(
        self,
        query: str = "",
        max_results: int = 10,
        user_email: str | None = None,
    ) -> list[EmailThread]:
        """List email threads matching a Gmail search query.

        Args:
            query: Gmail search query (e.g., "from:customer@example.com").
            max_results: Maximum number of threads to return.
            user_email: Email for delegation. Defaults to default_user_email.

        Returns:
            List of EmailThread objects with message summaries.
        """
        sender = user_email or self._default_user_email
        service = self._auth.get_gmail_service(sender)

        def _list() -> dict:
            return (
                service.users()
                .threads()
                .list(userId="me", q=query, maxResults=max_results)
                .execute()
            )

        logger.info("listing_threads", query=query, max_results=max_results)
        result = await asyncio.to_thread(_list)

        threads: list[EmailThread] = []
        for thread_data in result.get("threads", []):
            thread_id = thread_data.get("id", "")
            # Fetch full thread details for each result
            thread = await self.get_thread(thread_id, user_email=sender)
            threads.append(thread)

        return threads
