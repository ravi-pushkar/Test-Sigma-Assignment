"""Assembly of evaluation metrics into one machine-readable verdict."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from blast_agent.contracts import (
    AbsenceObservation,
    CodeSymbol,
    ImpactFinding,
    PullRequestChange,
    Requirement,
    ScreenState,
    TraceLink,
    UIElement,
    UserFlow,
)

from .metrics import (
    absence_metrics,
    impact_metrics,
    link_metrics,
    load_run_records,
    requirement_recall,
)
from .stability import pairwise_stability


def _unmapped_files(crawl_run: Path, code_run: Path) -> list[str]:
    """Load explicit unmapped files, falling back to symbol-free PR changes."""

    result: set[str] = set()
    for root in (crawl_run, code_run):
        list_path = root / "unmapped_files.json"
        if list_path.is_file():
            payload = json.loads(list_path.read_text(encoding="utf-8"))
            if not isinstance(payload, list):
                payload = [payload]
            for item in payload:
                result.add(
                    str(item.get("file")) if isinstance(item, dict) else str(item)
                )
        record_dir = root / "records" / "unmapped_files"
        if record_dir.is_dir():
            for path in sorted(record_dir.glob("*.json")):
                item = json.loads(path.read_text(encoding="utf-8"))
                result.add(str(item.get("file")) if isinstance(item, dict) else str(item))
    for change in load_run_records(code_run, "pr_changes", PullRequestChange):
        if not change.changed_symbol_ids:
            result.add(change.file)
    return sorted(result)


def _check(value: Any, passed: bool, *, threshold: Any = None) -> dict[str, Any]:
    result = {"status": "passed" if passed else "failed", "value": value}
    if threshold is not None:
        result["threshold"] = threshold
    return result


def _skipped(reason: str) -> dict[str, str]:
    return {"status": "skipped", "reason": reason}


def evaluate(
    crawl_run: Path,
    code_run: Path,
    docs_run: Path | None,
    gold_path: Path,
    stability_runs: list[Path],
) -> dict[str, Any]:
    """Evaluate persisted runs against a hand-labeled golden set."""

    crawl_root = Path(crawl_run)
    code_root = Path(code_run)
    gold = json.loads(Path(gold_path).read_text(encoding="utf-8"))

    screens = load_run_records(crawl_root, "screens", ScreenState)
    elements = load_run_records(crawl_root, "elements", UIElement)
    flows = load_run_records(crawl_root, "flows", UserFlow)
    links = load_run_records(crawl_root, "trace_links", TraceLink)
    impacts = load_run_records(crawl_root, "impacts", ImpactFinding)
    absences = load_run_records(crawl_root, "absences", AbsenceObservation)
    symbols = load_run_records(code_root, "code_symbols", CodeSymbol)
    requirements = (
        load_run_records(Path(docs_run), "requirements", Requirement)
        if docs_run is not None
        else []
    )

    requirement_result = requirement_recall(requirements, gold)
    link_result = link_metrics(links, elements, screens, symbols, gold)
    lookups = {
        "elements": elements,
        "screens": screens,
        "flows": flows,
        "symbols": symbols,
    }
    impact_result = impact_metrics(
        impacts, _unmapped_files(crawl_root, code_root), lookups, gold
    )
    absence_result = absence_metrics(absences, requirements, gold)
    stability_result = pairwise_stability(stability_runs)

    thresholds = dict(gold.get("thresholds", {}))
    checks: dict[str, dict[str, Any]] = {}
    if docs_run is None:
        checks["requirement_recall"] = _skipped("docs run not provided")
    elif not requirements:
        checks["requirement_recall"] = _skipped("docs run has no requirements")
    else:
        minimum = float(thresholds.get("requirement_recall_min", 0.0))
        checks["requirement_recall"] = _check(
            requirement_result["recall"],
            requirement_result["recall"] >= minimum,
            threshold=minimum,
        )

    link_minimum = float(thresholds.get("link_recall_min", 0.0))
    checks["link_recall"] = _check(
        link_result["recall"],
        link_result["recall"] >= link_minimum,
        threshold=link_minimum,
    )
    precision = 1.0 if not link_result["violations"] else 0.0
    checks["link_must_precision"] = _check(
        precision,
        not link_result["violations"],
        threshold=float(thresholds.get("link_must_precision", 1.0)),
    )
    checks["impact"] = _check(
        impact_result["overall_pass"], impact_result["overall_pass"]
    )

    if len(stability_runs) < 2:
        checks["stability"] = _skipped("fewer than two stability runs")
    else:
        stability_minimum = float(thresholds.get("stability_jaccard_min", 0.0))
        minimum_score = min(stability_result.values()) if stability_result else 1.0
        checks["stability"] = _check(
            minimum_score,
            minimum_score >= stability_minimum,
            threshold=stability_minimum,
        )

    if not requirements:
        checks["absence"] = _skipped("no requirement records")
    else:
        checks["absence"] = _check(
            absence_result["found"], absence_result["found"] >= 1, threshold=1
        )

    overall_pass = all(check["status"] != "failed" for check in checks.values())
    return {
        "requirements": requirement_result,
        "links": link_result,
        "impacts": impact_result,
        "absences": absence_result,
        "stability": stability_result,
        "thresholds": thresholds,
        "checks": checks,
        "overall_pass": overall_pass,
    }


__all__ = ["evaluate"]
