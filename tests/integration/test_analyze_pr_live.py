"""Live graph coverage for the deterministic PR impact report."""

from __future__ import annotations

import os
from pathlib import Path

from neo4j import GraphDatabase
import pytest

from blast_agent.code_index.pr_diff import PR_META
from blast_agent.graph import GraphWriter
from blast_agent.reasoning import compute_impacts, fetch_entity_lookups, render_report


RUN_ID = "run-m3-nollm-4"
PR_NUMBER = 37045


def _settings() -> tuple[str, str, str]:
    dotenv = GraphWriter._read_dotenv(Path(".env"))
    return (
        os.environ.get("NEO4J_URI")
        or dotenv.get("NEO4J_URI")
        or "bolt://localhost:7687",
        os.environ.get("NEO4J_USER") or dotenv.get("NEO4J_USER") or "neo4j",
        os.environ.get("NEO4J_PASSWORD")
        or dotenv.get("NEO4J_PASSWORD")
        or "password",
    )


def _neo4j_has_pr() -> bool:
    uri, user, password = _settings()
    driver = None
    try:
        driver = GraphDatabase.driver(
            uri, auth=(user, password), connection_timeout=2.0
        )
        driver.verify_connectivity()
        with driver.session(database="neo4j") as session:
            return session.run(
                "MATCH (pr:PullRequest {number: $pr}) RETURN count(pr) > 0 AS found",
                pr=PR_NUMBER,
            ).single()["found"]
    except Exception:
        return False
    finally:
        if driver is not None:
            driver.close()


pytestmark = pytest.mark.skipif(
    not _neo4j_has_pr(), reason="Neo4j is unreachable or PR 37045 is not loaded"
)


def test_compute_and_render_live_pr_impacts() -> None:
    uri, user, password = _settings()
    driver = GraphDatabase.driver(
        uri, auth=(user, password), connection_timeout=3.0
    )
    try:
        findings, unmapped = compute_impacts(
            driver, PR_NUMBER, RUN_ID, str(PR_META["base_sha"])
        )
        assert len(findings) >= 1
        assert all(0 < finding.confidence <= 1 for finding in findings)

        affected_ids = sorted(
            {entity_id for finding in findings for entity_id in finding.affected_entity_ids}
        )
        with driver.session(database="neo4j") as session:
            routes = {
                record["route"]
                for record in session.run(
                    "UNWIND $ids AS id MATCH (screen:Screen)-[:CONTAINS]->(element:UIElement {id: id}) "
                    "RETURN DISTINCT screen.route_pattern AS route",
                    ids=affected_ids,
                )
            }
        assert routes & {
            "/{owner}/{repo}/issues/new",
            "/{owner}/{repo}/issues/{number}",
        }
        assert any(
            Path(str(change["file"])).suffix in {".css", ".md"}
            for change in unmapped
        )

        lookups = fetch_entity_lookups(driver, findings)
        report = render_report(
            findings,
            unmapped,
            {
                "pr": {
                    **PR_META,
                    "url": "https://github.com/go-gitea/gitea/pull/37045",
                    "files_changed": 21,
                },
                "run_id": RUN_ID,
                "source_revision": str(PR_META["base_sha"]),
                "generated_at": "2026-07-11T12:00:00+00:00",
                "crawl_stats": {
                    "screens": len(lookups["screens"]),
                    "elements": len(lookups["elements"]),
                    "flows": len(lookups["flows"]),
                    "requirements": len(lookups["requirements"]),
                },
                "entity_lookups": lookups,
            },
        )
    finally:
        driver.close()

    assert "# Blast-radius report: PR #37045" in report
    assert "## Impacts by risk" in report
    assert "## User flows to re-test" in report
    assert "## Requirements at risk" in report
    assert "## Not mapped to UI" in report
    assert "## Run identifiers" in report
