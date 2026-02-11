"""ESW product knowledge ingestion helpers.

Provides batch ingestion utilities for loading ESW product documentation
into the knowledge base vector store.
"""

from src.knowledge.products.esw_data import (
    ESW_DEFAULT_TENANT_ID,
    PRODUCT_DATA_DIR,
    ingest_all_esw_products,
    verify_product_retrieval,
)

__all__ = [
    "ESW_DEFAULT_TENANT_ID",
    "PRODUCT_DATA_DIR",
    "ingest_all_esw_products",
    "verify_product_retrieval",
]
