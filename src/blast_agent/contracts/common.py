"""Shared primitives for versioned blast-agent contracts.

NATURAL_KEYS note
-----------------
Producers must create record IDs with ``stable_id(kind, *natural_key)`` using
the following natural keys:

* ScreenState: ``(url, visible_text_hash)``
* UIElement: ``(screen_id, role, name)``
* Interaction: ``(source_state_id, element_id, action, target_state_id)``
* UserFlow: ``(goal, start_state_id, end_state_id)``
* Requirement: ``(source_span.uri, statement)``
* CodeSymbol: ``(repo_sha, file, qualified_name)``
* PullRequestChange: ``(str(pr_number), file)``
* TraceLink: ``(source_entity_id, target_entity_id, link_type)``
* AbsenceObservation: ``(requirement_id, crawl_run_id)``
* ImpactFinding: ``(changed_symbol_id, str(sorted(affected_entity_ids)))``
"""

from hashlib import sha256

from pydantic import BaseModel, ConfigDict


SCHEMA_VERSION = "1.0.0"


def stable_id(kind: str, *parts: str) -> str:
    """Return a deterministic, normalized identifier for a contract record."""

    normalized = "\x1f".join(str(part).strip().casefold() for part in parts)
    digest = sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"{kind}:{digest}"


class ContractRecord(BaseModel):
    """Base fields present on every persisted contract record."""

    id: str
    schema_version: str = SCHEMA_VERSION
    run_id: str
    source: str
    source_revision: str

    model_config = ConfigDict(extra="forbid")


class SourceSpan(BaseModel):
    """A precise citation into source material."""

    uri: str
    heading_path: list[str] = []
    quote: str
    start_offset: int | None = None
    end_offset: int | None = None

    model_config = ConfigDict(extra="forbid")
