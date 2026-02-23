#!/usr/bin/env python3
"""Seed Solution Architect knowledge documents into the vector database.

Reads markdown files from data/knowledge/solution_architect/ and ingests them
through the standard IngestionPipeline. Each file's content_type is determined
by its filename prefix (e.g., competitor-analysis -> competitor_analysis).

Usage:
    uv run python scripts/seed_sa_knowledge.py
    uv run python scripts/seed_sa_knowledge.py --tenant-id acme --data-dir /path/to/docs
    uv run python scripts/seed_sa_knowledge.py --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path so we can import src modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

logger = logging.getLogger(__name__)

# ── File prefix to content_type mapping ──────────────────────────────────

FILE_CONTENT_TYPE_MAP: dict[str, str] = {
    "competitor-analysis": "competitor_analysis",
    "architecture-template": "architecture_template",
    "poc-templates": "poc_template",
}


def _resolve_content_type(filename: str) -> str | None:
    """Determine content_type from filename prefix.

    Iterates over FILE_CONTENT_TYPE_MAP and returns the content_type
    for the first prefix that matches the filename.

    Args:
        filename: The filename (not full path) to match against.

    Returns:
        The content_type string if a match is found, None otherwise.
    """
    for prefix, content_type in FILE_CONTENT_TYPE_MAP.items():
        if filename.startswith(prefix):
            return content_type
    return None


async def seed(tenant_id: str, data_dir: str, dry_run: bool = False) -> None:
    """Ingest SA knowledge documents and product docs into the vector store.

    Processes two directories:
    1. data_dir (SA knowledge): content_type overridden by filename prefix map.
    2. data/products/ (product docs): metadata_overrides=None so MetadataExtractor
       reads existing YAML frontmatter.

    Args:
        tenant_id: Tenant ID to associate with ingested chunks.
        data_dir: Directory containing the .md SA knowledge files.
        dry_run: If True, only report what would be ingested without
            connecting to Qdrant or generating embeddings.
    """
    from src.knowledge.config import KnowledgeBaseConfig
    from src.knowledge.embeddings import EmbeddingService
    from src.knowledge.ingestion.chunker import KnowledgeChunker
    from src.knowledge.ingestion.metadata_extractor import MetadataExtractor
    from src.knowledge.ingestion.pipeline import IngestionPipeline
    from src.knowledge.qdrant_client import QdrantKnowledgeStore

    data_path = Path(data_dir)
    if not data_path.is_dir():
        print(f"Error: data directory does not exist: {data_path}")
        sys.exit(1)

    # Resolve products directory relative to project root (two levels up from scripts/)
    project_root = Path(__file__).parent.parent
    products_path = project_root / "data" / "products"

    # Collect .md files from SA knowledge dir
    sa_files = sorted(data_path.glob("*.md"))
    # Collect top-level .md files from products dir (no subdirectories)
    product_files = sorted(products_path.glob("*.md")) if products_path.is_dir() else []

    if not sa_files and not product_files:
        print(f"No .md files found in {data_path} or {products_path}")
        sys.exit(1)

    print(f"Found {len(sa_files)} SA knowledge docs in {data_path}")
    for f in sa_files:
        ct = _resolve_content_type(f.name)
        print(f"  {f.name} -> content_type: {ct or '(auto-detect)'}")

    print(f"\nFound {len(product_files)} product docs in {products_path}")
    for f in product_files:
        print(f"  {f.name} -> content_type: (auto-detect from frontmatter)")

    if dry_run:
        print("\n[DRY RUN] No documents were ingested.")
        return

    # Initialize pipeline components
    config = KnowledgeBaseConfig()
    embedder = EmbeddingService(config)
    chunker = KnowledgeChunker(
        chunk_size=config.chunk_size,
        overlap_pct=config.chunk_overlap_pct,
    )
    extractor = MetadataExtractor()

    try:
        store = QdrantKnowledgeStore(config, embedder)
    except Exception as e:
        _handle_connection_error(e)
        return

    pipeline = IngestionPipeline(
        store=store,
        embedder=embedder,
        chunker=chunker,
        extractor=extractor,
    )

    sa_chunks = 0
    sa_errors = 0
    product_chunks = 0
    product_errors = 0

    # ── Pass 1: SA knowledge docs ─────────────────────────────────────────
    print(f"\nIngesting SA knowledge docs...")
    for md_file in sa_files:
        content_type = _resolve_content_type(md_file.name)
        metadata_overrides: dict[str, str] | None = None
        if content_type:
            metadata_overrides = {"content_type": content_type}

        try:
            result = await pipeline.ingest_document(
                file_path=md_file,
                tenant_id=tenant_id,
                metadata_overrides=metadata_overrides,
            )
            sa_chunks += result.chunks_created
            sa_errors += len(result.errors)

            status = "OK" if not result.errors else "ERRORS"
            print(f"  [{status}] {md_file.name}: {result.chunks_created} chunks")
            for err in result.errors:
                print(f"    Error: {err}")

        except Exception as e:
            error_msg = str(e)
            if _is_connection_error(e):
                _handle_connection_error(e)
                return
            sa_errors += 1
            print(f"  [FAIL] {md_file.name}: {error_msg}")

    # ── Pass 2: Product docs ──────────────────────────────────────────────
    if product_files:
        print(f"\nIngesting product docs...")
        for md_file in product_files:
            try:
                result = await pipeline.ingest_document(
                    file_path=md_file,
                    tenant_id=tenant_id,
                    metadata_overrides=None,
                )
                product_chunks += result.chunks_created
                product_errors += len(result.errors)

                status = "OK" if not result.errors else "ERRORS"
                print(f"  [{status}] {md_file.name}: {result.chunks_created} chunks")
                for err in result.errors:
                    print(f"    Error: {err}")

            except Exception as e:
                error_msg = str(e)
                if _is_connection_error(e):
                    _handle_connection_error(e)
                    return
                product_errors += 1
                print(f"  [FAIL] {md_file.name}: {error_msg}")

    total_errors = sa_errors + product_errors

    # Print summary
    print(f"\n{'=' * 50}")
    print(f"Seed Summary")
    print(f"{'=' * 50}")
    print(f"  Tenant:              {tenant_id}")
    print(f"  SA knowledge docs:   {len(sa_files)} files, {sa_chunks} chunks")
    print(f"  Product docs:        {len(product_files)} files, {product_chunks} chunks")
    print(f"  Total chunks:        {sa_chunks + product_chunks}")
    print(f"  Errors:              {total_errors}")

    if total_errors > 0:
        print(f"\nWarning: {total_errors} error(s) occurred during ingestion.")
        sys.exit(1)

    print("\nSA knowledge seed completed successfully.")


def _is_connection_error(exc: Exception) -> bool:
    """Check if an exception indicates a connection failure."""
    error_str = str(exc).lower()
    connection_indicators = [
        "connection refused",
        "connect call failed",
        "name or service not known",
        "no route to host",
        "connection reset",
        "timed out",
        "unreachable",
        "qdrant",
    ]
    return any(indicator in error_str for indicator in connection_indicators)


def _handle_connection_error(exc: Exception) -> None:
    """Print a helpful message when Qdrant is unavailable."""
    print(f"\nError: Could not connect to Qdrant vector database.")
    print(f"  Detail: {exc}")
    print(f"\nTo start Qdrant locally with Docker:")
    print(f"  docker run -d --name qdrant -p 6333:6333 -p 6334:6334 \\")
    print(f"    -v $(pwd)/qdrant_data:/qdrant/storage \\")
    print(f"    qdrant/qdrant:latest")
    print(f"\nOr set KNOWLEDGE_QDRANT_URL in your .env file for a remote instance.")
    print(f"\nTo test without Qdrant, use --dry-run to validate file parsing.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed Solution Architect knowledge documents into the vector database.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  uv run python scripts/seed_sa_knowledge.py\n"
            "  uv run python scripts/seed_sa_knowledge.py --tenant-id acme\n"
            "  uv run python scripts/seed_sa_knowledge.py --dry-run\n"
        ),
    )
    parser.add_argument(
        "--tenant-id",
        default="skyvera",
        help="Tenant ID for the ingested knowledge (default: skyvera)",
    )
    parser.add_argument(
        "--data-dir",
        default="data/knowledge/solution_architect",
        help="Directory containing SA knowledge markdown files (default: data/knowledge/solution_architect)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be ingested without actually connecting to Qdrant",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose logging output",
    )
    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING, format="%(name)s %(levelname)s: %(message)s")

    asyncio.run(seed(args.tenant_id, args.data_dir, args.dry_run))


if __name__ == "__main__":
    main()
