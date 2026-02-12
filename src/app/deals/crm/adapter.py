"""CRM adapter abstract base class -- defines the standard interface all CRM backends implement.

Every CRM backend (PostgreSQL, Notion, future Salesforce/HubSpot) implements this ABC.
The SyncEngine orchestrates data flow between the primary PostgreSQL adapter and any
configured external adapters.

Per RESEARCH.md Pattern 1: ABC-based adapter for explicit interface contracts and IDE support.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from src.app.deals.schemas import (
    ActivityCreate,
    ChangeRecord,
    ContactCreate,
    ContactUpdate,
    OpportunityCreate,
    OpportunityFilter,
    OpportunityRead,
    OpportunityUpdate,
)


class CRMAdapter(ABC):
    """Abstract interface for CRM backend operations.

    All CRM backends implement this interface. The SyncEngine coordinates
    data flow between the primary PostgreSQL adapter and any configured
    external adapters.

    Methods:
        create_opportunity: Create opportunity, return external ID string.
        update_opportunity: Update opportunity fields by external ID.
        get_opportunity: Fetch opportunity by external ID.
        list_opportunities: List opportunities matching filter criteria.
        create_contact: Create contact/stakeholder, return external ID.
        update_contact: Update contact fields by external ID.
        create_activity: Log an activity (email, call, meeting).
        get_changes_since: Fetch records changed since timestamp (for sync polling).
    """

    @abstractmethod
    async def create_opportunity(self, opportunity: OpportunityCreate) -> str:
        """Create opportunity, return external ID."""
        ...

    @abstractmethod
    async def update_opportunity(self, external_id: str, data: OpportunityUpdate) -> None:
        """Update opportunity fields by external ID."""
        ...

    @abstractmethod
    async def get_opportunity(self, external_id: str) -> OpportunityRead | None:
        """Fetch opportunity by external ID."""
        ...

    @abstractmethod
    async def list_opportunities(self, filters: OpportunityFilter) -> list[OpportunityRead]:
        """List opportunities matching filter criteria."""
        ...

    @abstractmethod
    async def create_contact(self, contact: ContactCreate) -> str:
        """Create contact/stakeholder, return external ID."""
        ...

    @abstractmethod
    async def update_contact(self, external_id: str, data: ContactUpdate) -> None:
        """Update contact fields by external ID."""
        ...

    @abstractmethod
    async def create_activity(self, activity: ActivityCreate) -> str:
        """Log an activity (email, call, meeting), return external ID."""
        ...

    @abstractmethod
    async def get_changes_since(self, since: datetime) -> list[ChangeRecord]:
        """Fetch records changed since timestamp (for sync polling)."""
        ...
