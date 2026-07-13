"""Confidence scoring and persistence for deterministic trace links."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import TypeVar

from blast_agent.contracts import (
    CodeSymbol,
    ContractRecord,
    Requirement,
    ScreenState,
    TraceLink,
    UIElement,
    stable_id,
)
from blast_agent.crawl.artifact_store import ArtifactStore

from .candidates import (
    LinkCandidate,
    Signal,
    requirement_ui_candidates,
    ui_code_candidates,
)


STRONG_SIGNAL_KINDS = {
    "href-exact",
    "route-exact",
    "text-exact",
    "clue-element-exact",
}

RecordT = TypeVar("RecordT", bound=ContractRecord)


def _dedupe_signals(signals: Iterable[Signal]) -> list[Signal]:
    by_evidence: dict[str, Signal] = {}
    for signal in signals:
        current = by_evidence.get(signal.evidence)
        if current is None or (signal.weight, signal.kind) > (
            current.weight,
            current.kind,
        ):
            by_evidence[signal.evidence] = signal
    return [by_evidence[evidence] for evidence in sorted(by_evidence)]


def combined_confidence(signals: Iterable[Signal]) -> float:
    """Combine independent evidence using noisy-or after evidence deduplication."""

    remaining_probability = 1.0
    for signal in _dedupe_signals(signals):
        remaining_probability *= 1.0 - signal.weight
    return 1.0 - remaining_probability


def to_trace_links(
    candidates: Iterable[LinkCandidate],
    run_id: str,
    source_revision: str,
) -> list[TraceLink]:
    """Score candidates and turn them into validated trace-link contracts."""

    merged: dict[tuple[str, str, str], list[Signal]] = {}
    for candidate in candidates:
        key = (
            candidate.source_entity_id,
            candidate.target_entity_id,
            candidate.link_type,
        )
        merged.setdefault(key, []).extend(candidate.signals)

    links: list[TraceLink] = []
    for source_entity_id, target_entity_id, link_type in sorted(merged):
        signals = _dedupe_signals(merged[(source_entity_id, target_entity_id, link_type)])
        confidence = combined_confidence(signals)
        has_strong_signal = any(
            signal.kind in STRONG_SIGNAL_KINDS for signal in signals
        )
        if confidence >= 0.85 and has_strong_signal:
            review_status = "auto_accepted"
        elif confidence >= 0.55:
            review_status = "needs_review"
        else:
            review_status = "unresolved"

        links.append(
            TraceLink(
                id=stable_id(
                    "trace_link", source_entity_id, target_entity_id, link_type
                ),
                run_id=run_id,
                source="linking",
                source_revision=source_revision,
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                link_type=link_type,
                confidence=confidence,
                method="+".join(sorted({signal.kind for signal in signals})),
                evidence=[f"{signal.kind}:{signal.evidence}" for signal in signals],
                review_status=review_status,
            )
        )
    return links


def _load_records(
    root: Path,
    record_dir: str,
    model: type[RecordT],
) -> list[RecordT]:
    directory = root / "records" / record_dir
    if not directory.is_dir():
        return []
    return [
        model.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
        if path.is_file()
    ]


def link_run(
    run_root: Path,
    run_id: str,
    code_run_root: Path | None = None,
    docs_run_root: Path | None = None,
) -> dict[str, int]:
    """Load one run's records, generate links, persist them, and count outcomes."""

    run_root = Path(run_root)
    code_root = Path(code_run_root) if code_run_root is not None else run_root
    docs_root = Path(docs_run_root) if docs_run_root is not None else run_root
    elements = _load_records(run_root, "elements", UIElement)
    screens = _load_records(run_root, "screens", ScreenState)
    symbols = _load_records(code_root, "code_symbols", CodeSymbol)
    requirements = _load_records(docs_root, "requirements", Requirement)

    candidates = ui_code_candidates(elements, screens, symbols)
    candidates.extend(requirement_ui_candidates(requirements, elements, screens))

    revision_records = [*elements, *screens, *requirements, *symbols]
    source_revision = revision_records[0].source_revision if revision_records else "unknown"
    links = to_trace_links(candidates, run_id, source_revision)

    store = ArtifactStore(run_root)
    counts = {
        status: 0 for status in ("auto_accepted", "needs_review", "unresolved")
    }
    for link in links:
        store.save_record(link, "trace_links")
        counts[link.review_status] += 1
    return counts


__all__ = [
    "STRONG_SIGNAL_KINDS",
    "combined_confidence",
    "link_run",
    "to_trace_links",
]
