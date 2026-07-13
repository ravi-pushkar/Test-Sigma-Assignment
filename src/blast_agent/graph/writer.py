"""Idempotently load persisted blast-agent contracts into Neo4j."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from neo4j import GraphDatabase

from .schema import CONSTRAINTS


def _records(root: Path, directory: str) -> list[dict[str, Any]]:
    record_dir = root / "records" / directory
    if not record_dir.is_dir():
        return []
    return [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(record_dir.glob("*.json"))
        if path.is_file()
    ]


def _properties(record: dict[str, Any]) -> dict[str, Any]:
    """Convert contract JSON to values accepted as Neo4j properties."""

    properties: dict[str, Any] = {}
    for key, value in record.items():
        if isinstance(value, dict):
            properties[key] = json.dumps(value, sort_keys=True, separators=(",", ":"))
        elif isinstance(value, list) and any(
            isinstance(item, (dict, list)) for item in value
        ):
            properties[key] = json.dumps(value, sort_keys=True, separators=(",", ":"))
        else:
            properties[key] = value
    return properties


class GraphWriter:
    """Write artifact records into a Neo4j database using repeatable MERGEs."""

    def __init__(self, driver, database: str = "neo4j") -> None:
        self.driver = driver
        self.database = database

    def apply_constraints(self) -> None:
        with self.driver.session(database=self.database) as session:
            for statement in CONSTRAINTS:
                session.run(statement).consume()

    def load_run(
        self,
        run_root: Path,
        code_run_root: Path | None = None,
        docs_run_root: Path | None = None,
    ) -> None:
        """Load crawl, code, requirement, absence, and trace-link records."""

        run_root = Path(run_root)
        code_root = Path(code_run_root) if code_run_root is not None else run_root
        docs_root = Path(docs_run_root) if docs_run_root is not None else run_root
        screens = _records(run_root, "screens")
        elements = _records(run_root, "elements")
        interactions = _records(run_root, "interactions")
        flows = _records(run_root, "flows")
        requirements = _records(docs_root, "requirements")
        absences = _records(run_root, "absences")
        symbols = _records(code_root, "code_symbols")
        changes = _records(code_root, "pr_changes")
        links = _records(run_root, "trace_links")

        all_run_records = [
            *screens,
            *elements,
            *interactions,
            *flows,
            *requirements,
            *absences,
        ]
        run_id = (
            screens[0].get("run_id")
            if screens
            else all_run_records[0].get("run_id") if all_run_records else run_root.name
        )
        source_revision = (
            screens[0].get("source_revision") if screens else "unknown"
        )

        self.apply_constraints()
        with self.driver.session(database=self.database) as session:
            session.run(
                "MERGE (run:CrawlRun {id: $id}) "
                "SET run.source_revision = $source_revision, run.run_id = $id",
                id=run_id,
                source_revision=source_revision,
            ).consume()
            self._load_crawl(session, run_id, screens, elements, interactions, flows)
            self._load_requirements_and_absences(
                session, requirements, absences
            )
            self._load_code(session, symbols, changes)
            self._load_links(session, links)

    @staticmethod
    def _load_crawl(
        session,
        run_id: str,
        screens: list[dict[str, Any]],
        elements: list[dict[str, Any]],
        interactions: list[dict[str, Any]],
        flows: list[dict[str, Any]],
    ) -> None:
        for screen in screens:
            session.run(
                "MERGE (screen:Screen {id: $id}) SET screen += $properties "
                "WITH screen MATCH (run:CrawlRun {id: $run_id}) "
                "MERGE (screen)-[:OBSERVED_IN]->(run)",
                id=screen["id"],
                properties=_properties(screen),
                run_id=run_id,
            ).consume()
        for element in elements:
            session.run(
                "MERGE (element:UIElement {id: $id}) SET element += $properties "
                "WITH element MATCH (screen:Screen {id: $screen_id}) "
                "MERGE (screen)-[:CONTAINS]->(element)",
                id=element["id"],
                properties=_properties(element),
                screen_id=element["screen_id"],
            ).consume()
        for interaction in interactions:
            session.run(
                "MERGE (interaction:Interaction {id: $id}) "
                "SET interaction += $properties "
                "WITH interaction "
                "MATCH (source:Screen {id: $source_id}), "
                "      (target:Screen {id: $target_id}) "
                "MERGE (source)-[:TRANSITIONS_TO {via: $id}]->(target) "
                "WITH interaction "
                "MATCH (element:UIElement {id: $element_id}) "
                "MERGE (interaction)-[:USES]->(element)",
                id=interaction["id"],
                properties=_properties(interaction),
                source_id=interaction["source_state_id"],
                target_id=interaction["target_state_id"],
                element_id=interaction["element_id"],
            ).consume()
        for flow in flows:
            session.run(
                "MERGE (flow:UserFlow {id: $id}) SET flow += $properties",
                id=flow["id"],
                properties=_properties(flow),
            ).consume()
            for order, interaction_id in enumerate(flow["interaction_ids"]):
                session.run(
                    "MATCH (flow:UserFlow {id: $flow_id}), "
                    "      (interaction:Interaction {id: $interaction_id}) "
                    "MERGE (flow)-[:HAS_STEP {order: $order}]->(interaction)",
                    flow_id=flow["id"],
                    interaction_id=interaction_id,
                    order=order,
                ).consume()

    @staticmethod
    def _load_requirements_and_absences(
        session,
        requirements: list[dict[str, Any]],
        absences: list[dict[str, Any]],
    ) -> None:
        for requirement in requirements:
            session.run(
                "MERGE (requirement:Requirement {id: $id}) "
                "SET requirement += $properties",
                id=requirement["id"],
                properties=_properties(requirement),
            ).consume()
        for absence in absences:
            session.run(
                "MERGE (absence:AbsenceObservation {id: $id}) "
                "SET absence += $properties "
                "WITH absence "
                "MATCH (requirement:Requirement {id: $requirement_id}), "
                "      (run:CrawlRun {id: $crawl_run_id}) "
                "MERGE (requirement)-[:HAS_ABSENCE]->(absence) "
                "MERGE (absence)-[:ASSESSED_IN]->(run)",
                id=absence["id"],
                properties=_properties(absence),
                requirement_id=absence["requirement_id"],
                crawl_run_id=absence["crawl_run_id"],
            ).consume()

    @staticmethod
    def _load_code(
        session,
        symbols: list[dict[str, Any]],
        changes: list[dict[str, Any]],
    ) -> None:
        for symbol in symbols:
            session.run(
                "MERGE (file:CodeFile {path: $file}) "
                "MERGE (symbol:CodeSymbol {id: $id}) SET symbol += $properties "
                "MERGE (file)-[:DECLARES]->(symbol)",
                file=symbol["file"],
                id=symbol["id"],
                properties=_properties(symbol),
            ).consume()
        for change in changes:
            session.run(
                "MERGE (pr:PullRequest {number: $number}) "
                "SET pr.title = $title, pr.base_sha = $base_sha, "
                "    pr.head_sha = $head_sha, pr.merge_commit_sha = $merge_sha, "
                "    pr.run_id = $run_id "
                "MERGE (file:CodeFile {path: $file}) "
                "MERGE (change:Change {id: $id}) SET change += $properties "
                "MERGE (pr)-[:CHANGES]->(change) "
                "MERGE (change)-[:OF_FILE]->(file)",
                number=change["pr_number"],
                title=change["title"],
                base_sha=change["base_sha"],
                head_sha=change["head_sha"],
                merge_sha=change.get("merge_commit_sha"),
                run_id=change["run_id"],
                file=change["file"],
                id=change["id"],
                properties=_properties(change),
            ).consume()
            for symbol_id in change.get("changed_symbol_ids", []):
                session.run(
                    "MATCH (change:Change {id: $change_id}), "
                    "      (symbol:CodeSymbol {id: $symbol_id}) "
                    "MERGE (change)-[:TOUCHES]->(symbol)",
                    change_id=change["id"],
                    symbol_id=symbol_id,
                ).consume()

    @staticmethod
    def _load_links(session, links: list[dict[str, Any]]) -> None:
        merge_and_set = (
            "{link_id: $link_id}]->(target) "
            "SET link.confidence = $confidence, link.method = $method, "
            "link.review_status = $review_status, link.evidence = $evidence"
        )
        queries = {
            "implements": (
                "MATCH (source:Requirement {id: $source_id}), (target {id: $target_id}) "
                "WHERE target:UIElement OR target:Screen "
                f"MERGE (source)-[link:IMPLEMENTED_BY {merge_and_set}"
            ),
            "rendered_by": (
                "MATCH (source:UIElement {id: $source_id}), "
                "      (target:CodeSymbol {id: $target_id}) "
                f"MERGE (source)-[link:RENDERED_BY {merge_and_set}"
            ),
            "handled_by": (
                "MATCH (source {id: $source_id}), "
                "      (target:CodeSymbol {id: $target_id}) "
                "WHERE source:Screen OR source:UIElement "
                f"MERGE (source)-[link:HANDLED_BY {merge_and_set}"
            ),
            "supports": (
                "MATCH (source {id: $source_id}), (target {id: $target_id}) "
                f"MERGE (source)-[link:SUPPORTED_BY {merge_and_set}"
            ),
            "uses": (
                "MATCH (source {id: $source_id}), (target {id: $target_id}) "
                f"MERGE (source)-[link:SUPPORTED_BY {merge_and_set}"
            ),
        }
        for trace_link in links:
            session.run(
                queries[trace_link["link_type"]],
                source_id=trace_link["source_entity_id"],
                target_id=trace_link["target_entity_id"],
                confidence=trace_link["confidence"],
                method=trace_link["method"],
                review_status=trace_link["review_status"],
                evidence=trace_link["evidence"],
                link_id=trace_link["id"],
            ).consume()

    @classmethod
    def from_env(cls) -> "GraphWriter":
        """Create a writer from environment variables or a local .env file."""

        dotenv = cls._read_dotenv(Path(".env"))
        uri = os.environ.get("NEO4J_URI") or dotenv.get("NEO4J_URI")
        user = os.environ.get("NEO4J_USER") or dotenv.get("NEO4J_USER")
        password = os.environ.get("NEO4J_PASSWORD") or dotenv.get("NEO4J_PASSWORD")
        if not uri or not user or not password:
            raise ValueError(
                "NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD must be configured"
            )
        return cls(GraphDatabase.driver(uri, auth=(user, password)))

    @staticmethod
    def _read_dotenv(path: Path) -> dict[str, str]:
        if not path.is_file():
            return {}
        values: dict[str, str] = {}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if key:
                values[key] = value
        return values

    def counts(self) -> dict[str, dict[str, int]]:
        """Count nodes by label and relationships by type."""

        with self.driver.session(database=self.database) as session:
            node_rows = session.run(
                "MATCH (n) UNWIND labels(n) AS label "
                "RETURN label, count(*) AS count ORDER BY label"
            )
            nodes = {row["label"]: row["count"] for row in node_rows}
            relationship_rows = session.run(
                "MATCH ()-[relationship]->() "
                "RETURN type(relationship) AS relationship_type, count(*) AS count "
                "ORDER BY relationship_type"
            )
            relationships = {
                row["relationship_type"]: row["count"] for row in relationship_rows
            }
        return {"nodes": nodes, "relationships": relationships}


__all__ = ["GraphWriter"]
