"""Materialize explicit observations of missing requirement coverage."""

from __future__ import annotations

from pathlib import Path

from blast_agent.contracts import AbsenceObservation, Requirement, TraceLink, stable_id
from blast_agent.crawl import ArtifactStore


def _load_records(root: Path, directory: str, model: type):
    path = root / "records" / directory
    if not path.is_dir():
        return []
    return [
        model.model_validate_json(item.read_text(encoding="utf-8"))
        for item in sorted(path.glob("*.json"))
        if item.is_file()
    ]


def record_absences(
    run_root: Path,
    run_id: str,
    source_revision: str,
    docs_run_root: Path | None = None,
) -> list[AbsenceObservation]:
    """Persist an absence for each requirement without a viable outgoing link."""

    run_root = Path(run_root)
    docs_root = Path(docs_run_root) if docs_run_root is not None else run_root
    requirements = _load_records(docs_root, "requirements", Requirement)
    links = _load_records(run_root, "trace_links", TraceLink)
    linked_requirement_ids = {
        link.source_entity_id
        for link in links
        if link.review_status in ("auto_accepted", "needs_review")
    }

    observations: list[AbsenceObservation] = []
    store = ArtifactStore(run_root)
    for requirement in requirements:
        if requirement.id in linked_requirement_ids:
            continue
        observation = AbsenceObservation(
            id=stable_id("absence", requirement.id, run_id),
            run_id=run_id,
            source="trace-analyzer",
            source_revision=source_revision,
            requirement_id=requirement.id,
            crawl_run_id=run_id,
            search_scope=f"crawl-run:{run_id};screens+elements+links",
            expected_evidence=requirement.acceptance_clues or [requirement.statement],
            confidence=0.7,
            explanation=(
                "No accepted or review-pending trace link from this requirement "
                "to any observed screen or element in this run."
            ),
        )
        store.save_record(observation, "absences")
        observations.append(observation)
    return observations


__all__ = ["record_absences"]
