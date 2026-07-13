"""Deterministic candidate generation and scoring for cross-layer links."""

from .candidates import (
    LinkCandidate,
    Signal,
    requirement_ui_candidates,
    ui_code_candidates,
)
from .scorer import STRONG_SIGNAL_KINDS, combined_confidence, link_run, to_trace_links

__all__ = [
    "LinkCandidate",
    "Signal",
    "STRONG_SIGNAL_KINDS",
    "combined_confidence",
    "link_run",
    "requirement_ui_candidates",
    "to_trace_links",
    "ui_code_candidates",
]
