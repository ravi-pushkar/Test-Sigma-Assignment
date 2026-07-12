"""Contracts linking evidence across requirements, UI, and code."""

from typing import Annotated, Literal

from pydantic import Field

from .common import ContractRecord


_Confidence = Annotated[float, Field(ge=0, le=1)]


class TraceLink(ContractRecord):
    source_entity_id: str
    target_entity_id: str
    link_type: Literal["implements", "rendered_by", "handled_by", "supports", "uses"]
    confidence: _Confidence
    method: str
    evidence: list[str]
    review_status: Literal["auto_accepted", "needs_review", "unresolved"]


class AbsenceObservation(ContractRecord):
    requirement_id: str
    crawl_run_id: str
    search_scope: str
    expected_evidence: list[str]
    confidence: _Confidence
    explanation: str
