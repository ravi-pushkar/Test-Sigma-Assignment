"""Read-side Cypher queries for coverage and impact analysis."""

from __future__ import annotations


COVERAGE_QUERY = """
MATCH (requirement:Requirement)
WHERE requirement.run_id = $run_id
OPTIONAL MATCH (requirement)-[implemented:IMPLEMENTED_BY]->()
WITH requirement,
     count(CASE WHEN implemented.review_status = 'auto_accepted' THEN 1 END) AS accepted_count,
     count(CASE WHEN implemented.review_status = 'needs_review' THEN 1 END) AS pending_count
OPTIONAL MATCH (requirement)-[:HAS_ABSENCE]->(absence:AbsenceObservation)-[:ASSESSED_IN]->(run:CrawlRun {id: $run_id})
WITH requirement, accepted_count, pending_count, count(DISTINCT absence) AS absence_count
RETURN requirement.id AS id,
       requirement.statement AS statement,
       accepted_count > 0 AS covered,
       accepted_count = 0 AND pending_count > 0 AS pending,
       absence_count > 0 AS absent,
       accepted_count,
       pending_count,
       absence_count
ORDER BY id
"""

IMPACT_SEED_QUERY = """
MATCH (:PullRequest {number: $pr_number})-[:CHANGES]->(:Change)-[:TOUCHES]->(symbol:CodeSymbol)
RETURN DISTINCT symbol.id AS id, symbol.file AS file, symbol.qualified_name AS qualified_name
ORDER BY id
"""


def requirement_coverage(driver, run_id: str) -> list[dict]:
    """Return requirement coverage rows for one crawl run."""

    with driver.session() as session:
        return [dict(record) for record in session.run(COVERAGE_QUERY, run_id=run_id)]


def changed_symbols(driver, pr_number: int) -> list[dict]:
    """Return the changed code symbols that seed impact analysis for a PR."""

    with driver.session() as session:
        return [
            dict(record)
            for record in session.run(IMPACT_SEED_QUERY, pr_number=pr_number)
        ]


__all__ = [
    "COVERAGE_QUERY",
    "IMPACT_SEED_QUERY",
    "changed_symbols",
    "requirement_coverage",
]
