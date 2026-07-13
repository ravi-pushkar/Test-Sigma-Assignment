"""Documentation snapshot ingestion."""

from .loader import (
    DocSegment,
    extract_article_text,
    load_snapshot,
    restore_docs_snapshots,
    segment,
)
from .requirement_extractor import (
    CachedLLM,
    PROMPT_TEMPLATE,
    RESPONSE_SCHEMA,
    extract_requirements,
    ingest_docs,
)

__all__ = [
    "CachedLLM",
    "DocSegment",
    "PROMPT_TEMPLATE",
    "RESPONSE_SCHEMA",
    "extract_article_text",
    "extract_requirements",
    "ingest_docs",
    "load_snapshot",
    "restore_docs_snapshots",
    "segment",
]
