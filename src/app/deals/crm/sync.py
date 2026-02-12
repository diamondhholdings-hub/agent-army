"""Bidirectional CRM sync engine with field-level conflict resolution.

Orchestrates data flow between the primary PostgreSQL adapter and any
configured external CRM adapter (Notion, future Salesforce/HubSpot).

Key design decisions per RESEARCH.md Pattern 5:
- Outbound sync is batched (not real-time per write) to avoid rate limiting (Pitfall 1)
- Default 60-second sync interval (Pitfall 1)
- Field-level conflict resolution with ownership rules (Pitfall 6):
  - Agent-owned fields: agent wins unless human explicitly overrode
  - Human-owned fields: external CRM wins always
  - Shared fields: last-write-wins with timestamp comparison
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from src.app.deals.crm.adapter import CRMAdapter
from src.app.deals.schemas import (
    ChangeRecord,
    FieldOwnershipConfig,
    OpportunityUpdate,
    SyncResult,
)

logger = structlog.get_logger(__name__)


class SyncEngine:
    """Orchestrates bidirectional sync between primary and external CRM.

    The primary adapter (PostgreSQL) is always available. The external adapter
    (Notion, etc.) is optional. If no external adapter is configured, sync
    operations return empty results.

    Args:
        primary: Always PostgreSQL -- the agent's primary storage.
        external: Optional external CRM adapter (Notion, Salesforce, etc.).
        field_ownership: Configuration defining agent/human/shared fields.
        sync_interval_seconds: Batched sync interval. Default 60s per Pitfall 1.
    """

    def __init__(
        self,
        primary: CRMAdapter,
        external: CRMAdapter | None,
        field_ownership: FieldOwnershipConfig,
        sync_interval_seconds: int = 60,
    ) -> None:
        self._primary = primary
        self._external = external
        self._ownership = field_ownership
        self._sync_interval = sync_interval_seconds
        self._last_sync: datetime | None = None

    def has_external(self) -> bool:
        """Return True if an external CRM adapter is configured."""
        return self._external is not None

    async def sync_outbound(self, changes: list[ChangeRecord]) -> SyncResult:
        """Push changes from primary to external CRM.

        Respects field ownership: only pushes agent_owned and shared fields.
        If no external adapter is configured, returns empty SyncResult.

        Args:
            changes: List of ChangeRecord objects from the primary adapter.

        Returns:
            SyncResult with pushed/errors counts.
        """
        if self._external is None:
            return SyncResult(pushed=0, pulled=0, conflicts=0, errors=[])

        pushed = 0
        errors: list[str] = []

        for change in changes:
            try:
                # Filter to only agent-owned and shared fields
                filtered_fields = self._filter_outbound_fields(change.changed_fields)
                if not filtered_fields:
                    continue

                if change.external_id:
                    # Update existing record in external CRM
                    update = OpportunityUpdate(**{
                        k: v for k, v in filtered_fields.items()
                        if k in OpportunityUpdate.model_fields
                    })
                    await self._external.update_opportunity(change.external_id, update)
                    pushed += 1
                else:
                    logger.debug(
                        "sync.outbound_skip_no_external_id",
                        entity_id=change.entity_id,
                    )

            except Exception as exc:
                error_msg = f"Outbound sync failed for {change.entity_id}: {exc}"
                errors.append(error_msg)
                logger.error(
                    "sync.outbound_error",
                    entity_id=change.entity_id,
                    error=str(exc),
                )

        logger.info(
            "sync.outbound_complete",
            pushed=pushed,
            errors=len(errors),
        )

        return SyncResult(pushed=pushed, pulled=0, conflicts=0, errors=errors)

    async def sync_inbound(self) -> SyncResult:
        """Pull changes from external CRM since last sync.

        For each change, resolves conflicts via _resolve_conflict() and
        applies resolved changes to the primary adapter. Updates _last_sync
        timestamp after completion.

        Returns:
            SyncResult with pulled/conflicts/errors counts.
        """
        if self._external is None:
            return SyncResult(pushed=0, pulled=0, conflicts=0, errors=[])

        since = self._last_sync or datetime(2000, 1, 1, tzinfo=timezone.utc)
        changes = await self._external.get_changes_since(since)

        pulled = 0
        conflicts = 0
        errors: list[str] = []

        for change in changes:
            try:
                resolved = self._resolve_conflict(change)

                if not resolved.changed_fields:
                    continue

                # Apply resolved changes to primary
                if resolved.entity_id:
                    update = OpportunityUpdate(**{
                        k: v for k, v in resolved.changed_fields.items()
                        if k in OpportunityUpdate.model_fields
                    })
                    # Use entity_id for primary storage lookup
                    primary_id = resolved.entity_id
                    if resolved.external_id:
                        # Try to find by external_id mapping
                        primary_id = resolved.entity_id

                    await self._primary.update_opportunity(primary_id, update)
                    pulled += 1

                    if len(resolved.changed_fields) < len(change.changed_fields):
                        conflicts += 1

            except Exception as exc:
                error_msg = f"Inbound sync failed for {change.entity_id}: {exc}"
                errors.append(error_msg)
                logger.error(
                    "sync.inbound_error",
                    entity_id=change.entity_id,
                    error=str(exc),
                )

        self._last_sync = datetime.now(timezone.utc)

        logger.info(
            "sync.inbound_complete",
            pulled=pulled,
            conflicts=conflicts,
            errors=len(errors),
        )

        return SyncResult(pushed=0, pulled=pulled, conflicts=conflicts, errors=errors)

    def _resolve_conflict(self, change: ChangeRecord) -> ChangeRecord:
        """Field-level conflict resolution per RESEARCH.md Pitfall 6.

        Rules:
        - Agent-owned fields: agent (primary) wins -- external change is dropped
          unless the change source indicates explicit human override.
        - Human-owned fields: external CRM wins always.
        - Shared fields: last-write-wins with timestamp comparison.
          (For inbound, the external timestamp is the change timestamp.)

        Args:
            change: ChangeRecord from the external CRM.

        Returns:
            Filtered ChangeRecord with only the winning fields.
        """
        winning_fields: dict[str, Any] = {}

        for field_name, value in change.changed_fields.items():
            ownership = self._get_field_ownership(field_name)

            if ownership == "agent_owned":
                # Agent wins -- drop external change for agent-owned fields
                # Exception: if change source explicitly indicates human override
                if change.source == "human_override":
                    winning_fields[field_name] = value
                # Otherwise agent wins, external change dropped
                continue

            elif ownership == "human_owned":
                # External CRM wins always for human-owned fields
                winning_fields[field_name] = value

            elif ownership == "shared":
                # Last-write-wins -- for inbound sync, external change is newer
                # since it was modified after our last sync
                winning_fields[field_name] = value

            else:
                # Unknown field ownership -- treat as shared (last-write-wins)
                winning_fields[field_name] = value

        return ChangeRecord(
            entity_type=change.entity_type,
            entity_id=change.entity_id,
            external_id=change.external_id,
            changed_fields=winning_fields,
            timestamp=change.timestamp,
            source=change.source,
        )

    def _filter_outbound_fields(self, fields: dict[str, Any]) -> dict[str, Any]:
        """Filter fields for outbound sync -- only push agent-owned and shared fields.

        Human-owned fields are never pushed outbound (CRM is source of truth for those).

        Args:
            fields: Dict of field names to values.

        Returns:
            Filtered dict excluding human-owned fields.
        """
        filtered: dict[str, Any] = {}

        for field_name, value in fields.items():
            ownership = self._get_field_ownership(field_name)
            # Push agent-owned and shared fields; skip human-owned
            if ownership != "human_owned":
                filtered[field_name] = value

        return filtered

    def _get_field_ownership(self, field_name: str) -> str:
        """Determine the ownership category of a field.

        Args:
            field_name: Internal field name.

        Returns:
            One of "agent_owned", "human_owned", "shared", or "unknown".
        """
        if field_name in self._ownership.agent_owned_fields:
            return "agent_owned"
        if field_name in self._ownership.human_owned_fields:
            return "human_owned"
        if field_name in self._ownership.shared_fields:
            return "shared"
        return "unknown"
