"""Sales methodology frameworks for structured and semantic access.

Provides Pydantic models for MEDDIC, BANT, and SPIN selling methodologies
with rich examples, questions, and practical tips. Also provides a loader
for ingesting methodology content into Qdrant for semantic search.
"""

from src.knowledge.methodology.frameworks import (
    MethodologyExample,
    MethodologyFramework,
    MethodologyLibrary,
    MethodologyStep,
)

__all__ = [
    "MethodologyExample",
    "MethodologyFramework",
    "MethodologyLibrary",
    "MethodologyStep",
]
