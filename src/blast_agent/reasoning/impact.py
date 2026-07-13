"""Deterministic graph traversal for pull-request blast-radius findings."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from blast_agent.contracts import ImpactFinding, stable_id


IMPACT_QUERY = """
MATCH (pr:PullRequest {number: $pr})-[:CHANGES]->(ch:Change)-[:TOUCHES]->(sym:CodeSymbol)
CALL {
  WITH ch, sym
  MATCH (el:UIElement)-[r:RENDERED_BY|HANDLED_BY]->(sym)
  WHERE r.review_status IN ['auto_accepted', 'needs_review']
  OPTIONAL MATCH (sc:Screen)-[:CONTAINS]->(el)
  OPTIONAL MATCH (flow:UserFlow)-[:HAS_STEP]->(:Interaction)-[:USES]->(el)
  OPTIONAL MATCH (req:Requirement)-[ri:IMPLEMENTED_BY]->(el)
  WHERE ri.review_status IN ['auto_accepted', 'needs_review']
  RETURN el.id AS element_id, el.name AS element_name,
         sc.id AS screen_id, sc.route_pattern AS screen_route,
         flow.id AS flow_id, flow.goal AS flow_goal,
         size(coalesce(flow.interaction_ids, [])) AS flow_step_count,
         req.id AS requirement_id, req.statement AS requirement_statement,
         toFloat(r.confidence) AS mapping_confidence,
         CASE WHEN ri IS NULL THEN toFloat(r.confidence)
              ELSE CASE WHEN r.confidence <= ri.confidence
                        THEN toFloat(r.confidence) ELSE toFloat(ri.confidence) END
         END AS path_confidence
  UNION ALL
  WITH ch, sym
  MATCH (sc2:Screen)-[r2:HANDLED_BY]->(sym)
  WHERE r2.review_status IN ['auto_accepted', 'needs_review']
  OPTIONAL MATCH (flow2:UserFlow)-[:HAS_STEP]->(interaction2:Interaction)
  WHERE interaction2.source_state_id = sc2.id OR interaction2.target_state_id = sc2.id
  RETURN null AS element_id, null AS element_name,
         sc2.id AS screen_id, sc2.route_pattern AS screen_route,
         flow2.id AS flow_id, flow2.goal AS flow_goal,
         size(coalesce(flow2.interaction_ids, [])) AS flow_step_count,
         null AS requirement_id, null AS requirement_statement,
         toFloat(r2.confidence) AS mapping_confidence,
         toFloat(r2.confidence) AS path_confidence
}
RETURN ch.id AS change_id, ch.file AS file, ch.change_type AS change_type,
       sym.id AS symbol_id, element_id, element_name, screen_id, screen_route,
       flow_id, flow_goal, flow_step_count, requirement_id,
       requirement_statement, mapping_confidence, path_confidence
ORDER BY symbol_id, element_id, screen_id, flow_id, requirement_id
"""


UNMAPPED_QUERY = """
MATCH (:PullRequest {number: $pr})-[:CHANGES]->(ch:Change)
OPTIONAL MATCH (ch)-[:TOUCHES]->(sym:CodeSymbol)
WITH ch, collect(DISTINCT sym) AS symbols
WHERE none(symbol IN symbols WHERE EXISTS {
  MATCH (ui)-[:RENDERED_BY|HANDLED_BY]->(symbol)
  WHERE ui:UIElement OR ui:Screen
})
RETURN ch.file AS file, ch.change_type AS change_type,
       CASE WHEN size(coalesce(ch.changed_symbol_ids, [])) = 0
            THEN 'no symbols extracted' ELSE 'no UI link found' END AS reason
ORDER BY file, change_type
"""


ENTITY_LOOKUP_QUERY = """
UNWIND $ids AS entity_id
MATCH (entity {id: entity_id})
RETURN entity.id AS id, labels(entity) AS labels,
       entity.name AS name, entity.route_pattern AS route,
       entity.goal AS goal, entity.statement AS statement,
       CASE WHEN entity:UserFlow THEN size(coalesce(entity.interaction_ids, []))
            ELSE null END AS step_count
ORDER BY id
"""


def _non_null_ids(row: dict[str, Any]) -> list[str]:
    return [
        str(row[key])
        for key in ("element_id", "screen_id", "flow_id", "requirement_id")
        if row.get(key) is not None
    ]


def build_findings(
    rows: list[dict[str, Any]],
    run_id: str,
    source_revision: str,
) -> list[ImpactFinding]:
    """Aggregate raw traversal rows into stable, deterministic findings.

    Severity is ``high`` when a changed symbol reaches a user flow and its
    strongest accepted code-to-UI edge is at least 0.8, ``medium`` when it
    reaches any UI element, and ``low`` for other mapped entities.  Finding
    confidence is the maximum code-to-UI edge confidence because that edge is
    the direct evidence that the changed symbol affects the interface.  When a
    requirement is traversed, its individual path confidence is the minimum of
    the code-to-UI and requirement-to-UI edges, but that conservative path
    value does not replace the finding-level direct-link confidence.

    Exactly one deterministic evidence path is retained per affected element.
    A path is ``change, symbol, element[, screen][, flow]``.  Screen-only
    handler links can create low/high findings but do not invent element paths.
    Symbols without an affected entity do not produce findings.
    """

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        symbol_id = row.get("symbol_id")
        if symbol_id is not None:
            grouped[str(symbol_id)].append(row)

    findings: list[ImpactFinding] = []
    for symbol_id in sorted(grouped):
        symbol_rows = grouped[symbol_id]
        affected_ids = sorted(
            {entity_id for row in symbol_rows for entity_id in _non_null_ids(row)}
        )
        if not affected_ids:
            continue

        confidences = [
            float(row["mapping_confidence"])
            for row in symbol_rows
            if row.get("mapping_confidence") is not None
        ]
        confidence = max(confidences, default=0.0)
        has_flow = any(row.get("flow_id") is not None for row in symbol_rows)
        has_element = any(row.get("element_id") is not None for row in symbol_rows)
        severity = (
            "high"
            if has_flow and confidence >= 0.8
            else "medium"
            if has_element
            else "low"
        )

        paths_by_element: dict[str, list[tuple[float, list[str]]]] = defaultdict(list)
        for row in symbol_rows:
            element_id = row.get("element_id")
            if element_id is None:
                continue
            path = [str(row["change_id"]), symbol_id, str(element_id)]
            if row.get("screen_id") is not None:
                path.append(str(row["screen_id"]))
            if row.get("flow_id") is not None:
                path.append(str(row["flow_id"]))
            paths_by_element[str(element_id)].append(
                (float(row.get("path_confidence") or 0.0), path)
            )
        paths = [
            sorted(candidates, key=lambda item: (-item[0], item[1]))[0][1]
            for _, candidates in sorted(paths_by_element.items())
        ]

        files = sorted({str(row.get("file") or "unknown file") for row in symbol_rows})
        findings.append(
            ImpactFinding(
                id=stable_id("impact", symbol_id, str(affected_ids)),
                run_id=run_id,
                source="reasoning",
                source_revision=source_revision,
                changed_symbol_id=symbol_id,
                path_entity_ids=paths,
                affected_entity_ids=affected_ids,
                severity=severity,
                confidence=confidence,
                summary=", ".join(files),
            )
        )

    order = {"high": 0, "medium": 1, "low": 2}
    return sorted(findings, key=lambda finding: (order[finding.severity], finding.id))


def compute_impacts(
    driver,
    pr_number: int,
    run_id: str,
    source_revision: str,
) -> tuple[list[ImpactFinding], list[dict]]:
    """Compute deterministic findings and explicit unmapped PR changes."""

    with driver.session() as session:
        rows = [dict(record) for record in session.run(IMPACT_QUERY, pr=pr_number)]
        unmapped = [
            dict(record) for record in session.run(UNMAPPED_QUERY, pr=pr_number)
        ]
    return build_findings(rows, run_id, source_revision), unmapped


def fetch_entity_lookups(driver, findings: list[ImpactFinding]) -> dict[str, dict]:
    """Fetch human-facing labels for entities referenced by findings."""

    ids = sorted({item for finding in findings for item in finding.affected_entity_ids})
    lookups: dict[str, dict] = {
        "elements": {},
        "screens": {},
        "flows": {},
        "requirements": {},
    }
    if not ids:
        return lookups
    with driver.session() as session:
        rows = [dict(record) for record in session.run(ENTITY_LOOKUP_QUERY, ids=ids)]
    for row in rows:
        labels = set(row.get("labels") or [])
        entity_id = str(row["id"])
        if "UIElement" in labels:
            lookups["elements"][entity_id] = str(row.get("name") or "Unnamed element")
        elif "Screen" in labels:
            lookups["screens"][entity_id] = str(row.get("route") or "Unknown route")
        elif "UserFlow" in labels:
            lookups["flows"][entity_id] = {
                "goal": str(row.get("goal") or "Unnamed flow"),
                "step_count": int(row.get("step_count") or 0),
            }
        elif "Requirement" in labels:
            lookups["requirements"][entity_id] = str(
                row.get("statement") or "Unnamed requirement"
            )
    return lookups


__all__ = [
    "ENTITY_LOOKUP_QUERY",
    "IMPACT_QUERY",
    "UNMAPPED_QUERY",
    "build_findings",
    "compute_impacts",
    "fetch_entity_lookups",
]
