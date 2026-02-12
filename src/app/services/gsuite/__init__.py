"""GSuite integration services for Gmail and Google Chat APIs.

Provides async-wrapped services for sending/reading emails and chat
messages using Google service account authentication with domain-wide
delegation.
"""

from src.app.services.gsuite.auth import GSuiteAuthManager
from src.app.services.gsuite.chat import ChatService
from src.app.services.gsuite.gmail import GmailService
from src.app.services.gsuite.models import (
    ChatMessage,
    EmailMessage,
    EmailThread,
    SentChatResult,
    SentEmailResult,
)

__all__ = [
    "ChatMessage",
    "ChatService",
    "EmailMessage",
    "EmailThread",
    "GmailService",
    "GSuiteAuthManager",
    "SentChatResult",
    "SentEmailResult",
]
