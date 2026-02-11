"""ESW product ingestion helper and verification utilities.

Provides convenience functions for batch ingestion of ESW product
documentation and verification that ingested data is retrievable.

The PRODUCT_DATA_DIR points to the standard location for product
documentation files. ingest_all_esw_products() ingests all supported
documents in that directory through the IngestionPipeline.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from src.knowledge.ingestion.pipeline import IngestionPipeline, IngestionResult
from src.knowledge.qdrant_client import QdrantKnowledgeStore

logger = logging.getLogger(__name__)

# Default tenant ID for ESW product knowledge (shared across tenants)
ESW_DEFAULT_TENANT_ID: str = "esw-default"

# Standard directory for ESW product documentation
PRODUCT_DATA_DIR: Path = Path("data/products")


async def ingest_all_esw_products(
    pipeline: IngestionPipeline,
    data_dir: Path | None = None,
    tenant_id: str = ESW_DEFAULT_TENANT_ID,
) -> list[IngestionResult]:
    """Ingest all ESW product documents from the data directory.

    Walks the product data directory and ingests all supported document
    formats through the full pipeline.

    Args:
        pipeline: Configured IngestionPipeline instance.
        data_dir: Override for product data directory (defaults to PRODUCT_DATA_DIR).
        tenant_id: Tenant to ingest for (defaults to ESW_DEFAULT_TENANT_ID).

    Returns:
        List of IngestionResult, one per file processed.
    """
    directory = data_dir or PRODUCT_DATA_DIR

    if not directory.exists():
        logger.warning("Product data directory does not exist: %s", directory)
        return [
            IngestionResult(
                document_source=str(directory),
                errors=[f"Directory not found: {directory}"],
            )
        ]

    results = await pipeline.ingest_directory(
        dir_path=directory,
        tenant_id=tenant_id,
        recursive=True,
    )

    total_chunks = sum(r.chunks_created for r in results)
    total_errors = sum(len(r.errors) for r in results)
    logger.info(
        "ESW product ingestion complete: %d files, %d chunks, %d errors",
        len(results),
        total_chunks,
        total_errors,
    )

    return results


async def verify_product_retrieval(
    store: QdrantKnowledgeStore,
    tenant_id: str = ESW_DEFAULT_TENANT_ID,
) -> dict[str, Any]:
    """Verify that product knowledge is retrievable from the store.

    Runs sample queries against each product category and reports results.

    Args:
        store: Qdrant knowledge store to query.
        tenant_id: Tenant to query for (defaults to ESW_DEFAULT_TENANT_ID).

    Returns:
        Dict with 'total_chunks', 'categories', and 'sample_results'.
    """
    sample_queries = [
        ("subscription management", {"product_category": "monetization"}),
        ("usage-based pricing", {"product_category": "charging"}),
        ("invoice generation", {"product_category": "billing"}),
    ]

    total_chunks = 0
    sample_results: list[dict[str, Any]] = []
    categories_found: set[str] = set()

    for query_text, filters in sample_queries:
        try:
            results = await store.hybrid_search(
                query_text=query_text,
                tenant_id=tenant_id,
                filters=filters,
                top_k=3,
            )
            for chunk in results:
                categories_found.add(chunk.metadata.product_category)
                total_chunks += 1
                sample_results.append(
                    {
                        "query": query_text,
                        "category": chunk.metadata.product_category,
                        "content_preview": chunk.content[:100],
                        "content_type": chunk.metadata.content_type,
                    }
                )
        except Exception as e:
            logger.warning("Verification query '%s' failed: %s", query_text, e)
            sample_results.append(
                {
                    "query": query_text,
                    "error": str(e),
                }
            )

    return {
        "total_chunks": total_chunks,
        "categories": sorted(categories_found),
        "sample_results": sample_results,
    }
