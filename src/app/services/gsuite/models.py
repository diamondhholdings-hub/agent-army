"""Pydantic schemas for GSuite email and chat message models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class EmailMessage(BaseModel):
    """Email message to send via Gmail API."""

    to: str
    subject: str
    body_html: str
    body_text: str | None = None
    thread_id: str | None = None
    in_reply_to: str | None = None
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)


class EmailThreadMessage(BaseModel):
    """A single message within an email thread."""

    sender: str
    snippet: str
    date: str


class EmailThread(BaseModel):
    """Email thread retrieved from Gmail API."""

    thread_id: str
    subject: str
    messages: list[EmailThreadMessage] = Field(default_factory=list)
    message_count: int = 0


class ChatMessage(BaseModel):
    """Chat message to send via Google Chat API."""

    space_name: str
    text: str
    thread_key: str | None = None


class SentEmailResult(BaseModel):
    """Result from sending an email via Gmail API."""

    message_id: str
    thread_id: str
    label_ids: list[str] = Field(default_factory=list)


class DraftResult(BaseModel):
    """Result from creating a Gmail draft."""

    draft_id: str
    message_id: str = ""
    thread_id: str = ""


class SentChatResult(BaseModel):
    """Result from sending a chat message via Google Chat API."""

    message_name: str
    create_time: str
