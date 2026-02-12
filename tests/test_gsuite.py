"""Tests for GSuite integration services.

All tests use mocked Google APIs -- no real credentials needed.
Validates auth caching, email MIME encoding with threading headers,
chat message threading, and async wrapping via asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import base64
import email
from email.policy import default as default_policy
from unittest.mock import MagicMock, patch

import pytest

from src.app.services.gsuite.auth import GSuiteAuthManager
from src.app.services.gsuite.chat import ChatService
from src.app.services.gsuite.gmail import GmailService
from src.app.services.gsuite.models import (
    ChatMessage,
    EmailMessage,
    EmailThread,
    EmailThreadMessage,
    SentChatResult,
    SentEmailResult,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_credentials():
    """Mock Google service account credentials."""
    with patch(
        "src.app.services.gsuite.auth.service_account.Credentials"
    ) as mock_creds_cls:
        mock_creds = MagicMock()
        mock_creds.with_subject.return_value = mock_creds
        mock_creds_cls.from_service_account_file.return_value = mock_creds
        yield mock_creds_cls


@pytest.fixture
def mock_build():
    """Mock googleapiclient.discovery.build."""
    with patch("src.app.services.gsuite.auth.build") as mock_build_fn:
        yield mock_build_fn


@pytest.fixture
def auth_manager(mock_credentials, mock_build):
    """Create a GSuiteAuthManager with mocked dependencies."""
    return GSuiteAuthManager(
        service_account_file="/fake/service-account.json",
        delegated_user_email="admin@example.com",
    )


@pytest.fixture
def gmail_service(auth_manager):
    """Create a GmailService with mocked auth manager."""
    return GmailService(
        auth_manager=auth_manager,
        default_user_email="admin@example.com",
    )


@pytest.fixture
def chat_service(auth_manager):
    """Create a ChatService with mocked auth manager."""
    return ChatService(auth_manager=auth_manager)


# ── Auth Caching Tests ───────────────────────────────────────────────────────


class TestGSuiteAuthManager:
    """Tests for GSuiteAuthManager credential and service caching."""

    def test_gmail_service_caches_per_user(
        self, auth_manager, mock_build
    ):
        """Two calls with the same user email return the same service object."""
        service1 = auth_manager.get_gmail_service("user@example.com")
        service2 = auth_manager.get_gmail_service("user@example.com")

        assert service1 is service2
        # build() should only be called once
        assert mock_build.call_count == 1

    def test_gmail_service_different_users_get_different_services(
        self, auth_manager, mock_build
    ):
        """Different user emails produce different cached service instances."""
        mock_build.side_effect = [MagicMock(), MagicMock()]

        service1 = auth_manager.get_gmail_service("user1@example.com")
        service2 = auth_manager.get_gmail_service("user2@example.com")

        assert service1 is not service2
        assert mock_build.call_count == 2

    def test_chat_service_caches_singleton(
        self, auth_manager, mock_build
    ):
        """Chat service is cached as singleton (no user delegation)."""
        service1 = auth_manager.get_chat_service()
        service2 = auth_manager.get_chat_service()

        assert service1 is service2
        assert mock_build.call_count == 1

    def test_gmail_defaults_to_delegated_user_email(
        self, auth_manager, mock_build
    ):
        """When no user_email is passed, uses the configured default."""
        auth_manager.get_gmail_service()

        # Should have used "admin@example.com" as the cache key
        assert "gmail:admin@example.com" in auth_manager._service_cache

    def test_credentials_with_subject_called_for_gmail(
        self, auth_manager, mock_credentials, mock_build
    ):
        """Gmail credentials use with_subject for domain-wide delegation."""
        auth_manager.get_gmail_service("delegate@example.com")

        mock_creds = mock_credentials.from_service_account_file.return_value
        mock_creds.with_subject.assert_called_once_with("delegate@example.com")

    def test_credentials_without_subject_for_chat(
        self, auth_manager, mock_credentials, mock_build
    ):
        """Chat credentials do NOT use with_subject (bot auth)."""
        auth_manager.get_chat_service()

        mock_creds = mock_credentials.from_service_account_file.return_value
        mock_creds.with_subject.assert_not_called()


# ── Gmail Service Tests ──────────────────────────────────────────────────────


class TestGmailService:
    """Tests for GmailService email sending and reading."""

    def test_build_mime_message_basic(self, gmail_service):
        """Basic email produces valid MIME with To, Subject, and HTML body."""
        email_msg = EmailMessage(
            to="recipient@example.com",
            subject="Test Subject",
            body_html="<p>Hello</p>",
        )

        raw = gmail_service._build_mime_message(email_msg)
        decoded = base64.urlsafe_b64decode(raw)
        parsed = email.message_from_bytes(decoded, policy=default_policy)

        assert parsed["To"] == "recipient@example.com"
        assert parsed["Subject"] == "Test Subject"
        # HTML body should be present
        body = parsed.get_body(preferencelist=("html",))
        assert body is not None
        assert "<p>Hello</p>" in body.get_content()

    def test_build_mime_message_with_threading_headers(self, gmail_service):
        """Email with in_reply_to sets In-Reply-To and References headers."""
        email_msg = EmailMessage(
            to="recipient@example.com",
            subject="Re: Test Subject",
            body_html="<p>Reply</p>",
            in_reply_to="<original-msg-id@example.com>",
        )

        raw = gmail_service._build_mime_message(email_msg)
        decoded = base64.urlsafe_b64decode(raw)
        parsed = email.message_from_bytes(decoded, policy=default_policy)

        assert parsed["In-Reply-To"] == "<original-msg-id@example.com>"
        assert parsed["References"] == "<original-msg-id@example.com>"

    def test_build_mime_message_with_cc_bcc(self, gmail_service):
        """Email with CC and BCC includes those headers."""
        email_msg = EmailMessage(
            to="recipient@example.com",
            subject="Test",
            body_html="<p>Body</p>",
            cc=["cc1@example.com", "cc2@example.com"],
            bcc=["bcc@example.com"],
        )

        raw = gmail_service._build_mime_message(email_msg)
        decoded = base64.urlsafe_b64decode(raw)
        parsed = email.message_from_bytes(decoded, policy=default_policy)

        assert "cc1@example.com" in parsed["Cc"]
        assert "cc2@example.com" in parsed["Cc"]
        assert "bcc@example.com" in parsed["Bcc"]

    def test_build_mime_message_with_text_fallback(self, gmail_service):
        """Email with body_text creates multipart with text and HTML parts."""
        email_msg = EmailMessage(
            to="recipient@example.com",
            subject="Test",
            body_html="<p>HTML body</p>",
            body_text="Plain text body",
        )

        raw = gmail_service._build_mime_message(email_msg)
        decoded = base64.urlsafe_b64decode(raw)
        parsed = email.message_from_bytes(decoded, policy=default_policy)

        # Should have both text and HTML parts
        text_body = parsed.get_body(preferencelist=("plain",))
        html_body = parsed.get_body(preferencelist=("html",))
        assert text_body is not None
        assert "Plain text body" in text_body.get_content()
        assert html_body is not None
        assert "<p>HTML body</p>" in html_body.get_content()

    async def test_send_email_includes_thread_id(
        self, gmail_service, mock_build
    ):
        """send_email includes threadId in payload when thread_id is set."""
        mock_service = gmail_service._auth.get_gmail_service()
        mock_send = (
            mock_service.users.return_value
            .messages.return_value
            .send.return_value
        )
        mock_send.execute.return_value = {
            "id": "msg-123",
            "threadId": "thread-456",
            "labelIds": ["SENT"],
        }

        email_msg = EmailMessage(
            to="recipient@example.com",
            subject="Re: Thread Test",
            body_html="<p>Reply</p>",
            thread_id="thread-456",
        )

        result = await gmail_service.send_email(email_msg)

        # Verify threadId was in the send body
        send_call = (
            mock_service.users.return_value
            .messages.return_value
            .send
        )
        call_kwargs = send_call.call_args
        body_arg = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
        assert body_arg["threadId"] == "thread-456"

        assert isinstance(result, SentEmailResult)
        assert result.message_id == "msg-123"
        assert result.thread_id == "thread-456"

    async def test_send_email_uses_asyncio_to_thread(
        self, gmail_service, mock_build
    ):
        """send_email wraps the Google API call in asyncio.to_thread."""
        mock_service = gmail_service._auth.get_gmail_service()
        mock_send = (
            mock_service.users.return_value
            .messages.return_value
            .send.return_value
        )
        mock_send.execute.return_value = {
            "id": "msg-123",
            "threadId": "thread-456",
            "labelIds": [],
        }

        email_msg = EmailMessage(
            to="test@example.com",
            subject="Test",
            body_html="<p>Test</p>",
        )

        with patch("src.app.services.gsuite.gmail.asyncio.to_thread") as mock_to_thread:
            mock_to_thread.return_value = {
                "id": "msg-123",
                "threadId": "thread-456",
                "labelIds": [],
            }
            await gmail_service.send_email(email_msg)
            mock_to_thread.assert_called_once()

    async def test_get_thread_returns_structured_data(
        self, gmail_service, mock_build
    ):
        """get_thread returns EmailThread with parsed message summaries."""
        mock_service = gmail_service._auth.get_gmail_service()
        mock_get = (
            mock_service.users.return_value
            .threads.return_value
            .get.return_value
        )
        mock_get.execute.return_value = {
            "id": "thread-789",
            "messages": [
                {
                    "id": "msg-1",
                    "snippet": "Hello there",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "sender@example.com"},
                            {"name": "Subject", "value": "Test Thread"},
                            {"name": "Date", "value": "Mon, 10 Feb 2026 10:00:00 +0000"},
                        ]
                    },
                },
                {
                    "id": "msg-2",
                    "snippet": "Reply here",
                    "payload": {
                        "headers": [
                            {"name": "From", "value": "replier@example.com"},
                            {"name": "Subject", "value": "Re: Test Thread"},
                            {"name": "Date", "value": "Mon, 10 Feb 2026 11:00:00 +0000"},
                        ]
                    },
                },
            ],
        }

        result = await gmail_service.get_thread("thread-789")

        assert isinstance(result, EmailThread)
        assert result.thread_id == "thread-789"
        assert result.subject == "Test Thread"
        assert result.message_count == 2
        assert result.messages[0].sender == "sender@example.com"
        assert result.messages[1].snippet == "Reply here"


# ── Chat Service Tests ───────────────────────────────────────────────────────


class TestChatService:
    """Tests for ChatService message sending."""

    async def test_send_message_basic(self, chat_service, mock_build):
        """send_message sends a basic text message to a space."""
        mock_service = chat_service._auth.get_chat_service()
        mock_create = (
            mock_service.spaces.return_value
            .messages.return_value
            .create.return_value
        )
        mock_create.execute.return_value = {
            "name": "spaces/ABC/messages/xyz",
            "createTime": "2026-02-11T10:00:00Z",
        }

        message = ChatMessage(
            space_name="spaces/ABC",
            text="Hello team!",
        )

        result = await chat_service.send_message(message)

        assert isinstance(result, SentChatResult)
        assert result.message_name == "spaces/ABC/messages/xyz"
        assert result.create_time == "2026-02-11T10:00:00Z"

    async def test_send_message_with_thread_key(
        self, chat_service, mock_build
    ):
        """send_message includes thread key and reply option when thread_key is set."""
        mock_service = chat_service._auth.get_chat_service()
        mock_create = (
            mock_service.spaces.return_value
            .messages.return_value
            .create.return_value
        )
        mock_create.execute.return_value = {
            "name": "spaces/ABC/messages/xyz",
            "createTime": "2026-02-11T10:00:00Z",
        }

        message = ChatMessage(
            space_name="spaces/ABC",
            text="Thread reply!",
            thread_key="deal-123",
        )

        result = await chat_service.send_message(message)

        # Verify the create call included thread info
        create_call = (
            mock_service.spaces.return_value
            .messages.return_value
            .create
        )
        call_kwargs = create_call.call_args.kwargs
        assert call_kwargs["messageReplyOption"] == "REPLY_MESSAGE_FALLBACK_TO_NEW_THREAD"
        body = call_kwargs["body"]
        assert body["thread"]["threadKey"] == "deal-123"
        assert body["text"] == "Thread reply!"

    async def test_send_message_uses_asyncio_to_thread(
        self, chat_service, mock_build
    ):
        """send_message wraps the Google API call in asyncio.to_thread."""
        message = ChatMessage(
            space_name="spaces/ABC",
            text="Test",
        )

        with patch("src.app.services.gsuite.chat.asyncio.to_thread") as mock_to_thread:
            mock_to_thread.return_value = {
                "name": "spaces/ABC/messages/xyz",
                "createTime": "2026-02-11T10:00:00Z",
            }
            await chat_service.send_message(message)
            mock_to_thread.assert_called_once()

    async def test_list_spaces_returns_structured_data(
        self, chat_service, mock_build
    ):
        """list_spaces returns list of dicts with name and displayName."""
        mock_service = chat_service._auth.get_chat_service()
        mock_list = (
            mock_service.spaces.return_value
            .list.return_value
        )
        mock_list.execute.return_value = {
            "spaces": [
                {"name": "spaces/AAA", "displayName": "Sales Team"},
                {"name": "spaces/BBB", "displayName": "Engineering"},
            ]
        }

        result = await chat_service.list_spaces()

        assert len(result) == 2
        assert result[0]["name"] == "spaces/AAA"
        assert result[0]["displayName"] == "Sales Team"
        assert result[1]["name"] == "spaces/BBB"


# ── Model Validation Tests ───────────────────────────────────────────────────


class TestModels:
    """Tests for Pydantic model validation."""

    def test_email_message_defaults(self):
        """EmailMessage has sensible defaults for optional fields."""
        msg = EmailMessage(
            to="test@example.com",
            subject="Test",
            body_html="<p>Hi</p>",
        )
        assert msg.thread_id is None
        assert msg.in_reply_to is None
        assert msg.cc == []
        assert msg.bcc == []
        assert msg.body_text is None

    def test_chat_message_defaults(self):
        """ChatMessage defaults thread_key to None."""
        msg = ChatMessage(space_name="spaces/ABC", text="Hello")
        assert msg.thread_key is None

    def test_email_thread_defaults(self):
        """EmailThread has empty messages list and zero count by default."""
        thread = EmailThread(thread_id="t-1", subject="Test")
        assert thread.messages == []
        assert thread.message_count == 0
