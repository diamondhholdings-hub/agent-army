"""Agentic RAG pipeline for knowledge base querying.

Provides query decomposition, multi-source retrieval, document grading,
query rewriting, and answer synthesis orchestrated as a state machine.

Components:
- QueryDecomposer: Breaks complex queries into source-targeted sub-queries
- MultiSourceRetriever: Fetches from products, methodology, regional, conversations
- ResponseSynthesizer: Produces grounded answers with source citations
- AgenticRAGPipeline: Orchestrates decompose -> retrieve -> grade -> synthesize
"""

from src.knowledge.rag.decomposer import QueryDecomposer, SubQuery
from src.knowledge.rag.pipeline import AgenticRAGPipeline, RAGResponse, RAGState
from src.knowledge.rag.retriever import MultiSourceRetriever, RetrievedChunk
from src.knowledge.rag.synthesizer import (
    ResponseSynthesizer,
    SourceCitation,
    SynthesizedResponse,
)

__all__ = [
    "AgenticRAGPipeline",
    "MultiSourceRetriever",
    "QueryDecomposer",
    "RAGResponse",
    "RAGState",
    "ResponseSynthesizer",
    "RetrievedChunk",
    "SourceCitation",
    "SubQuery",
    "SynthesizedResponse",
]
