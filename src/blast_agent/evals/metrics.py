"""Pure metrics implementing the hand-labeled golden-set match rules."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _record_dict(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return record
    model_dump = getattr(record, "model_dump", None)
    if model_dump is None:
        raise TypeError(f"expected a record dict or model, got {type(record)!r}")
    return model_dump()


def _records_by_id(records: Any) -> dict[str, dict[str, Any]]:
    if isinstance(records, dict):
        values = records.values()
    else:
        values = records
    result: dict[str, dict[str, Any]] = {}
    for value in values:
        record = _record_dict(value)
        if "id" in record:
            result[str(record["id"])] = record
    return result


def _requirement_matches(
    requirement: dict[str, Any], gold_requirement: dict[str, Any]
) -> bool:
    span = requirement.get("source_span") or {}
    text = " ".join(
        [
            str(requirement.get("statement") or ""),
            *(str(clue) for clue in requirement.get("acceptance_clues") or []),
        ]
    ).casefold()
    return str(span.get("uri") or "") == str(
        gold_requirement.get("source_uri") or ""
    ) and all(
        str(keyword).casefold() in text
        for keyword in gold_requirement.get("keywords") or []
    )


def requirement_recall(requirements: list[Any], gold: dict[str, Any]) -> dict[str, Any]:
    """Measure extraction recall using source URI and all-keyword containment."""

    records = [_record_dict(record) for record in requirements]
    expected = list(gold.get("requirements", {}).get("must_extract", []))
    recalled_ids = [
        str(item["id"])
        for item in expected
        if any(_requirement_matches(record, item) for record in records)
    ]
    recalled = set(recalled_ids)
    missed_ids = [
        str(item["id"]) for item in expected if str(item["id"]) not in recalled
    ]
    return {
        "recall": len(recalled_ids) / len(expected) if expected else 1.0,
        "recalled_ids": recalled_ids,
        "missed_ids": missed_ids,
        "extracted_total": len(records),
    }


def resolved_link_triples(
    links: list[Any], elements: list[Any], screens: list[Any], symbols: list[Any]
) -> set[tuple[str, str, str]]:
    """Resolve accepted/reviewable element-to-symbol links to golden triples."""

    element_by_id = _records_by_id(elements)
    screen_by_id = _records_by_id(screens)
    symbol_by_id = _records_by_id(symbols)
    triples: set[tuple[str, str, str]] = set()
    for raw_link in links:
        link = _record_dict(raw_link)
        if link.get("review_status") not in {"auto_accepted", "needs_review"}:
            continue
        element = element_by_id.get(str(link.get("source_entity_id") or ""))
        symbol = symbol_by_id.get(str(link.get("target_entity_id") or ""))
        if element is None or symbol is None:
            continue
        screen = screen_by_id.get(str(element.get("screen_id") or ""))
        if screen is None:
            continue
        triples.add(
            (
                str(element.get("name") or "").casefold(),
                str(screen.get("route_pattern") or ""),
                str(symbol.get("file") or ""),
            )
        )
    return triples


def _gold_triple(item: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(item.get("element_name") or "").casefold(),
        str(item.get("route") or ""),
        str(item.get("symbol_file") or ""),
    )


def link_metrics(
    links: list[Any],
    elements: list[Any],
    screens: list[Any],
    symbols: list[Any],
    gold: dict[str, Any],
) -> dict[str, Any]:
    """Measure required-link recall and report every forbidden-link match."""

    actual = resolved_link_triples(links, elements, screens, symbols)
    required = list(gold.get("links", {}).get("must_link", []))
    forbidden = list(gold.get("links", {}).get("must_not_link", []))
    matched = [item for item in required if _gold_triple(item) in actual]
    missed = [item for item in required if _gold_triple(item) not in actual]
    violations = [item for item in forbidden if _gold_triple(item) in actual]
    return {
        "recall": len(matched) / len(required) if required else 1.0,
        "matched": matched,
        "missed": missed,
        "violations": violations,
    }


def impact_metrics(
    impacts: list[Any],
    unmapped_files: list[str],
    lookups: dict[str, Any],
    gold: dict[str, Any],
) -> dict[str, Any]:
    """Check required affected routes/flows, unmapped files, and finding count."""

    findings = [_record_dict(record) for record in impacts]
    elements = _records_by_id(lookups.get("elements", {}))
    screens = _records_by_id(lookups.get("screens", {}))
    flows = _records_by_id(lookups.get("flows", {}))
    affected_ids = {
        str(entity_id)
        for finding in findings
        for entity_id in finding.get("affected_entity_ids") or []
    }
    affected_routes: set[str] = set()
    affected_goals: list[str] = []
    for entity_id in affected_ids:
        if entity_id in screens:
            affected_routes.add(str(screens[entity_id].get("route_pattern") or ""))
        if entity_id in elements:
            screen = screens.get(str(elements[entity_id].get("screen_id") or ""))
            if screen is not None:
                affected_routes.add(str(screen.get("route_pattern") or ""))
        if entity_id in flows:
            affected_goals.append(str(flows[entity_id].get("goal") or "").casefold())

    impact_gold = gold.get("impacts", {})
    route_results = {
        str(route): str(route) in affected_routes
        for route in impact_gold.get("required_affected_routes", [])
    }
    flow_results = [
        {
            "keywords": list(keywords),
            "covered": any(
                all(str(keyword).casefold() in goal for keyword in keywords)
                for goal in affected_goals
            ),
        }
        for keywords in impact_gold.get("required_affected_flow_goal_keywords", [])
    ]
    unmapped = set(unmapped_files)
    unmapped_results = {
        str(file): str(file) in unmapped
        for file in impact_gold.get("required_unmapped_files", [])
    }
    minimum = int(impact_gold.get("min_findings", 0))
    findings_count_pass = len(findings) >= minimum
    overall = (
        all(route_results.values())
        and all(item["covered"] for item in flow_results)
        and all(unmapped_results.values())
        and findings_count_pass
    )
    return {
        "required_routes": route_results,
        "required_flow_keyword_groups": flow_results,
        "required_unmapped_files": unmapped_results,
        "findings_count": len(findings),
        "min_findings": minimum,
        "findings_count_pass": findings_count_pass,
        "overall_pass": overall,
    }


def absence_metrics(
    absences: list[Any], requirements: list[Any], gold: dict[str, Any]
) -> dict[str, Any]:
    """Check expected crawl absences against their matched extracted requirements."""

    requirement_records = [_record_dict(record) for record in requirements]
    absence_requirement_ids = {
        str(_record_dict(record).get("requirement_id") or "") for record in absences
    }
    gold_requirements = {
        str(item["id"]): item
        for item in gold.get("requirements", {}).get("must_extract", [])
    }
    expected_entries = list(
        gold.get("requirements", {}).get("expected_absent_in_crawl", [])
    )
    found: list[str] = []
    missing: list[str] = []
    for entry in expected_entries:
        gold_id = str(entry["gold_id"])
        target = gold_requirements.get(gold_id)
        matching_ids = {
            str(requirement.get("id") or "")
            for requirement in requirement_records
            if target is not None and _requirement_matches(requirement, target)
        }
        (found if matching_ids & absence_requirement_ids else missing).append(gold_id)
    return {"expected": len(expected_entries), "found": len(found), "missing": missing}


def load_run_records(run_root: Path, kind: str, model_cls: Any) -> list[Any]:
    """Load and validate one persisted record kind from a run directory."""

    record_dir = Path(run_root) / "records" / kind
    if not record_dir.is_dir():
        return []
    return [
        model_cls.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(record_dir.glob("*.json"))
    ]
