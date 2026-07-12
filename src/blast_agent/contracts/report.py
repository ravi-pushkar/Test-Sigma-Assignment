"""Contracts for impact-analysis reports."""

from typing import Annotated, Literal

from pydantic import Field

from .common import ContractRecord


class ImpactFinding(ContractRecord):
    changed_symbol_id: str
    path_entity_ids: list[list[str]]
    affected_entity_ids: list[str]
    severity: Literal["high", "medium", "low"]
    confidence: Annotated[float, Field(ge=0, le=1)]
    summary: str
