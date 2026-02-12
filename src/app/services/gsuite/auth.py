"""GSuite authentication manager with service account and domain-wide delegation.

Handles credential creation and service instance caching to avoid
redundant credential builds per API request (Pitfall 1 from research).
"""

from __future__ import annotations

from typing import Any

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build

logger = structlog.get_logger(__name__)

# Gmail scopes for domain-wide delegation
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]

# Google Chat scope for service account (bot)
CHAT_SCOPES = [
    "https://www.googleapis.com/auth/chat.bot",
]


class GSuiteAuthManager:
    """Manages Google API authentication with service account credentials.

    Caches service instances per (api, user_email) tuple to avoid
    repeated credential builds and HTTP connection overhead.
    """

    def __init__(
        self,
        service_account_file: str,
        delegated_user_email: str,
    ) -> None:
        self._service_account_file = service_account_file
        self._delegated_user_email = delegated_user_email
        self._service_cache: dict[str, Any] = {}

    def _build_credentials(
        self,
        user_email: str | None,
        scopes: list[str],
    ) -> service_account.Credentials:
        """Create service account credentials with optional user delegation.

        Args:
            user_email: If provided, applies domain-wide delegation via
                with_subject() so the service account impersonates this user.
            scopes: OAuth2 scopes for the credentials.

        Returns:
            Service account credentials, optionally delegated.
        """
        credentials = service_account.Credentials.from_service_account_file(
            self._service_account_file,
            scopes=scopes,
        )
        if user_email:
            credentials = credentials.with_subject(user_email)
        return credentials

    def get_gmail_service(self, user_email: str | None = None) -> Any:
        """Get a cached Gmail API v1 service instance for the delegated user.

        Args:
            user_email: Email to impersonate. Defaults to the configured
                delegated_user_email.

        Returns:
            Gmail API Resource object.
        """
        email = user_email or self._delegated_user_email
        cache_key = f"gmail:{email}"

        if cache_key not in self._service_cache:
            logger.info(
                "building_gmail_service",
                user_email=email,
            )
            credentials = self._build_credentials(email, GMAIL_SCOPES)
            service = build("gmail", "v1", credentials=credentials)
            self._service_cache[cache_key] = service

        return self._service_cache[cache_key]

    def get_chat_service(self) -> Any:
        """Get a cached Google Chat API v1 service instance.

        Uses service account credentials directly (no user delegation)
        as Chat bots authenticate as the service account itself.

        Returns:
            Chat API Resource object.
        """
        cache_key = "chat"

        if cache_key not in self._service_cache:
            logger.info("building_chat_service")
            credentials = self._build_credentials(
                user_email=None,
                scopes=CHAT_SCOPES,
            )
            service = build("chat", "v1", credentials=credentials)
            self._service_cache[cache_key] = service

        return self._service_cache[cache_key]
