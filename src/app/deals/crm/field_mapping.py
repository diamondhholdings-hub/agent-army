"""Field ownership configuration and Notion property mappings for CRM sync.

Defines:
- DEFAULT_FIELD_OWNERSHIP: Which fields are agent-owned, human-owned, or shared
  for conflict resolution during bidirectional sync (RESEARCH.md Pitfall 6).
- NOTION_PROPERTY_MAP: Maps internal field names to Notion database property
  names and types for the NotionAdapter.
- to_notion_properties(): Converts internal dict to Notion API properties format.
- from_notion_properties(): Converts Notion properties to internal dict.
"""

from __future__ import annotations

from typing import Any

from src.app.deals.schemas import FieldOwnershipConfig


# ── Field Ownership Configuration ──────────────────────────────────────────
# Per RESEARCH.md Pitfall 6: explicit field ownership for conflict resolution

DEFAULT_FIELD_OWNERSHIP = FieldOwnershipConfig(
    agent_owned_fields=[
        "qualification_snapshot",
        "detection_confidence",
        "probability",
        "qualification_tracking",
        "stakeholder_map",
        "score_evidence",
    ],
    human_owned_fields=[
        "custom_notes",
        "manual_tags",
        "override_stage",
    ],
    shared_fields=[
        "deal_stage",
        "estimated_value",
        "close_date",
        "name",
    ],
)


# ── Notion Property Mappings ───────────────────────────────────────────────
# Maps internal field names to Notion database property names and types.
# Used by NotionAdapter for bidirectional property conversion.

NOTION_PROPERTY_MAP: dict[str, dict[str, str]] = {
    "name": {"notion_name": "Deal Name", "type": "title"},
    "deal_stage": {"notion_name": "Stage", "type": "select"},
    "estimated_value": {"notion_name": "Value", "type": "number"},
    "close_date": {"notion_name": "Close Date", "type": "date"},
    "product_line": {"notion_name": "Product", "type": "select"},
    "probability": {"notion_name": "Probability", "type": "number"},
    "source": {"notion_name": "Source", "type": "select"},
    "contact_name": {"notion_name": "Contact", "type": "rich_text"},
    "contact_email": {"notion_name": "Email", "type": "email"},
}


# ── Conversion Functions ───────────────────────────────────────────────────


def to_notion_properties(
    data: dict[str, Any],
    property_map: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Convert internal field dict to Notion API properties format.

    Maps each internal field to its Notion property name and wraps the value
    in the correct Notion property type structure.

    Args:
        data: Dict of internal field names to values.
        property_map: Optional custom property map. Defaults to NOTION_PROPERTY_MAP.

    Returns:
        Dict suitable for Notion API `properties` parameter.
    """
    if property_map is None:
        property_map = NOTION_PROPERTY_MAP

    properties: dict[str, Any] = {}

    for field_name, value in data.items():
        if field_name not in property_map or value is None:
            continue

        mapping = property_map[field_name]
        notion_name = mapping["notion_name"]
        prop_type = mapping["type"]

        if prop_type == "title":
            properties[notion_name] = {
                "title": [{"text": {"content": str(value)}}]
            }
        elif prop_type == "rich_text":
            properties[notion_name] = {
                "rich_text": [{"text": {"content": str(value)}}]
            }
        elif prop_type == "number":
            properties[notion_name] = {"number": float(value) if value is not None else None}
        elif prop_type == "select":
            properties[notion_name] = {"select": {"name": str(value)}}
        elif prop_type == "date":
            # Accept ISO string or datetime
            date_str = value if isinstance(value, str) else value.isoformat()
            properties[notion_name] = {"date": {"start": date_str}}
        elif prop_type == "email":
            properties[notion_name] = {"email": str(value)}

    return properties


def from_notion_properties(
    properties: dict[str, Any],
    property_map: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Convert Notion page properties to internal field dict.

    Extracts values from Notion's property type wrappers and maps them
    back to internal field names.

    Args:
        properties: Notion page `properties` dict.
        property_map: Optional custom property map. Defaults to NOTION_PROPERTY_MAP.

    Returns:
        Dict of internal field names to extracted values.
    """
    if property_map is None:
        property_map = NOTION_PROPERTY_MAP

    result: dict[str, Any] = {}

    # Build reverse map: notion_name -> (internal_name, type)
    reverse_map: dict[str, tuple[str, str]] = {}
    for internal_name, mapping in property_map.items():
        reverse_map[mapping["notion_name"]] = (internal_name, mapping["type"])

    for notion_name, prop_value in properties.items():
        if notion_name not in reverse_map:
            continue

        internal_name, prop_type = reverse_map[notion_name]
        extracted = _extract_notion_value(prop_value, prop_type)
        if extracted is not None:
            result[internal_name] = extracted

    return result


def _extract_notion_value(prop_value: dict[str, Any], prop_type: str) -> Any:
    """Extract a Python value from a Notion property value dict.

    Args:
        prop_value: The Notion property value structure.
        prop_type: The expected property type (title, rich_text, number, etc.).

    Returns:
        Extracted Python value, or None if empty/missing.
    """
    if prop_type == "title":
        title_arr = prop_value.get("title", [])
        if title_arr:
            return title_arr[0].get("text", {}).get("content")
        return None

    if prop_type == "rich_text":
        text_arr = prop_value.get("rich_text", [])
        if text_arr:
            return text_arr[0].get("text", {}).get("content")
        return None

    if prop_type == "number":
        return prop_value.get("number")

    if prop_type == "select":
        select_val = prop_value.get("select")
        if select_val:
            return select_val.get("name")
        return None

    if prop_type == "date":
        date_val = prop_value.get("date")
        if date_val:
            return date_val.get("start")
        return None

    if prop_type == "email":
        return prop_value.get("email")

    return None
