"""Cross-run stability signatures and pairwise Jaccard scoring."""

from __future__ import annotations

from itertools import combinations
from pathlib import Path
from typing import Any

from blast_agent.contracts import (
    CodeSymbol,
    ImpactFinding,
    ScreenState,
    TraceLink,
    UIElement,
    UserFlow,
)

from .metrics import load_run_records, resolved_link_triples


def jaccard(a: set[Any], b: set[Any]) -> float:
    """Return Jaccard similarity, defining two empty sets as identical."""

    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def run_signature(run_root: Path) -> dict[str, set[Any]]:
    """Build run-independent signatures from persisted crawl/link/impact records."""

    root = Path(run_root)
    screens = load_run_records(root, "screens", ScreenState)
    elements = load_run_records(root, "elements", UIElement)
    flows = load_run_records(root, "flows", UserFlow)
    links = load_run_records(root, "trace_links", TraceLink)
    symbols = load_run_records(root, "code_symbols", CodeSymbol)
    impacts = load_run_records(root, "impacts", ImpactFinding)

    screens_by_id = {record.id: record for record in screens}
    elements_by_id = {record.id: record for record in elements}
    symbols_by_id = {record.id: record for record in symbols}
    routes = {record.route_pattern for record in screens}
    element_pairs = {
        (record.name, screens_by_id[record.screen_id].route_pattern)
        for record in elements
        if record.screen_id in screens_by_id
    }
    impact_pairs: set[tuple[str, tuple[str, ...]]] = set()
    for finding in impacts:
        affected_routes: set[str] = set()
        for entity_id in finding.affected_entity_ids:
            if entity_id in screens_by_id:
                affected_routes.add(screens_by_id[entity_id].route_pattern)
            element = elements_by_id.get(entity_id)
            if element is not None and element.screen_id in screens_by_id:
                affected_routes.add(screens_by_id[element.screen_id].route_pattern)
        symbol = symbols_by_id.get(finding.changed_symbol_id)
        symbol_file = symbol.file if symbol is not None else finding.changed_symbol_id
        impact_pairs.add((symbol_file, tuple(sorted(affected_routes))))

    return {
        "screens": routes,
        "elements": element_pairs,
        "flows": {record.goal for record in flows},
        "links": resolved_link_triples(links, elements, screens, symbols),
        "impacts": impact_pairs,
    }


def pairwise_stability(run_roots: list[Path]) -> dict[str, float]:
    """Return the minimum pairwise Jaccard score for every signature category."""

    signatures = [run_signature(Path(root)) for root in run_roots]
    categories = ("screens", "elements", "flows", "links", "impacts")
    if len(signatures) < 2:
        return {category: 1.0 for category in categories}
    return {
        category: min(
            jaccard(left[category], right[category])
            for left, right in combinations(signatures, 2)
        )
        for category in categories
    }
