"""Contracts describing extracted requirements."""

from .common import ContractRecord, SourceSpan


class Requirement(ContractRecord):
    statement: str
    actor: str
    action: str
    object: str
    acceptance_clues: list[str] = []
    source_span: SourceSpan
    testable: bool = True
