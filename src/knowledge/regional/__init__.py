"""Regional sales nuance data for APAC, EMEA, and Americas.

Provides structured access to region-specific cultural considerations,
pricing modifiers, compliance requirements, and communication guidance.
Regional data is also ingested into Qdrant for semantic search.
"""

from src.knowledge.regional.nuances import RegionalNuances, get_regional_context

__all__ = [
    "RegionalNuances",
    "get_regional_context",
]
